"""数据源抓取：arXiv / OpenAlex / Semantic Scholar（可选）。

契约参考：技术设计文档.md §6。
- arXiv 请求间隔 ≥3s（模块锁）；sortBy=submittedDate
- 429/503/超时/连接错误 3 次指数退避（3s→6s→12s），失败记 errors 不阻塞其他源
- 解析、倒排摘要还原、三键去重、航空相关性过滤、URL 仅保留 http(s)
"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"

USER_AGENT = "AviationHybridLitRadar/1.0 (research)"
TIMEOUT = (5, 25)
RETRY_DELAYS = (3.0, 6.0, 12.0)  # 3 次指数退避
ARXIV_MIN_INTERVAL = 3.0  # arXiv 官方要求请求间隔 ≥3s

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_LOCK = threading.Lock()
_ARXIV_LAST_CALL = 0.0


class SourceDisabled(Exception):
    """数据源未启用（如无 Semantic Scholar Key）。"""


@dataclass
class PaperIn:
    """抓取层论文条目（尚未入库）。"""

    source: str
    external_id: str
    title: str
    published: str
    url: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "doi": self.doi,
            "title": self.title,
            "authors": list(self.authors),
            "abstract": self.abstract,
            "published": self.published,
            "url": self.url,
        }


# ---------------- 通用工具 ----------------


def make_session(settings: config.Settings | None = None) -> requests.Session:
    session = requests.Session()
    ua = USER_AGENT
    mailto = (settings.openalex_mailto if settings else "") or ""
    if mailto:
        ua = f"{USER_AGENT} (mailto:{mailto})"
    session.headers.update({"User-Agent": ua, "Accept": "application/json, application/atom+xml"})
    return session


def _safe_url(url: str | None) -> str:
    """仅允许 http(s) 链接，其余丢弃。"""
    if not url:
        return ""
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else ""


def _flatten(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_abstract(text: str | None) -> str:
    """清洗摘要：去 HTML 标签与转义、压空白；只有标记/过短（<20 字符）视为缺失。

    S2/OpenAlex 偶有 "<div class=...><sub>4</sub></div>" 这类占位摘要，
    直接入库会让证据校验把 "4" 当成合法证据，故统一清洗。
    """
    cleaned = _flatten(html.unescape(_TAG_RE.sub(" ", text or "")))
    return cleaned if len(cleaned) >= 20 else ""


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def _cutoff(days: int) -> str:
    return (date.today() - timedelta(days=max(0, int(days)))).isoformat()


def _within_days(published: str, days: int) -> bool:
    """published(YYYY-MM-DD) 是否落在最近 days 天窗口内。days<=0 视为全部。"""
    if days <= 0:
        return True
    try:
        return date.fromisoformat(published[:10]) >= date.today() - timedelta(days=int(days))
    except (ValueError, TypeError):
        return False


# ---------------- 网络层：重试与限流 ----------------


def _rate_limit_arxiv() -> None:
    """模块内互斥锁保证 arXiv 请求启动间隔 ≥ ARXIV_MIN_INTERVAL。"""
    global _ARXIV_LAST_CALL
    with _ARXIV_LOCK:
        now = time.monotonic()
        wait = ARXIV_MIN_INTERVAL - (now - _ARXIV_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _ARXIV_LAST_CALL = time.monotonic()


def _get_with_retry(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    errors: list[str],
    source: str,
) -> requests.Response | None:
    """GET + 3 次指数退避。仅对 429/503 与连接错误/超时重试。失败返回 None 并记 errors。"""
    attempts = len(RETRY_DELAYS) + 1
    last_error = ""
    for attempt in range(attempts):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:  # 超时/连接错误
            last_error = f"网络错误 {type(exc).__name__}: {exc}"
            if attempt < len(RETRY_DELAYS):
                log.warning("%s: %s，%.0fs 后重试", source, last_error, RETRY_DELAYS[attempt])
                time.sleep(RETRY_DELAYS[attempt])
                continue
            errors.append(f"{source}: {last_error}（重试 {attempt} 次仍失败）")
            return None
        if resp.status_code in (429, 503):
            last_error = f"HTTP {resp.status_code}"
            if attempt < len(RETRY_DELAYS):
                log.warning("%s: %s，%.0fs 后重试", source, last_error, RETRY_DELAYS[attempt])
                time.sleep(RETRY_DELAYS[attempt])
                continue
            errors.append(f"{source}: {last_error}（重试 {attempt} 次仍失败）")
            return None
        if resp.status_code >= 400:
            errors.append(f"{source}: HTTP {resp.status_code}")
            return None
        return resp
    errors.append(f"{source}: {last_error or '未知错误'}")
    return None


# ---------------- arXiv ----------------


def build_arxiv_queries() -> list[str]:
    """每组关键词构造一条 search_query：all:"短语" OR ...，共 4 条。"""
    queries = []
    for terms in config.KEYWORD_GROUPS.values():
        parts = [f'all:"{term}"' for term in terms]
        queries.append(" OR ".join(parts))
    return queries


def parse_arxiv_atom(xml_text: str) -> list[PaperIn]:
    """解析 arXiv Atom XML -> PaperIn 列表。"""
    root = ET.fromstring(xml_text)
    papers: list[PaperIn] = []
    for entry in root.findall(f"{_ATOM}entry"):
        raw_id = _flatten(entry.findtext(f"{_ATOM}id"))
        title = _flatten(entry.findtext(f"{_ATOM}title"))
        if not raw_id or not title:
            continue
        # id 形如 http://arxiv.org/abs/2601.01234v1 -> 2601.01234
        short_id = raw_id.rstrip("/").rsplit("/", 1)[-1]
        external_id = re.sub(r"v\d+$", "", short_id)
        if not external_id:
            continue
        published = _flatten(entry.findtext(f"{_ATOM}published"))[:10]
        doi_el = entry.find("{http://arxiv.org/schemas/atom}doi")
        doi = _flatten(doi_el.text if doi_el is not None else "") or None
        authors = [
            _flatten(name.text)
            for name in entry.findall(f"{_ATOM}author/{_ATOM}name")
            if _flatten(name.text)
        ]
        papers.append(
            PaperIn(
                source="arxiv",
                external_id=external_id,
                title=title,
                published=published,
                url=f"https://arxiv.org/abs/{external_id}",
                abstract=_clean_abstract(entry.findtext(f"{_ATOM}summary")),
                authors=authors,
                doi=doi,
            )
        )
    return papers


def fetch_arxiv(
    days: int,
    limit: int,
    session: requests.Session | None = None,
    errors: list[str] | None = None,
) -> list[PaperIn]:
    """抓取 arXiv：每组一次请求，每组 max_results = max(5, limit//2)（TDD §6.1）。"""
    errors = errors if errors is not None else []
    session = session or make_session()
    per_group = max(5, int(limit) // 2)
    papers: list[PaperIn] = []
    for query in build_arxiv_queries():
        _rate_limit_arxiv()
        params = {
            "search_query": query,
            "start": 0,
            "max_results": per_group,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = _get_with_retry(session, ARXIV_API, params, errors, "arxiv")
        if resp is None:
            continue
        try:
            papers.extend(parse_arxiv_atom(resp.text))
        except ET.ParseError as exc:
            errors.append(f"arxiv: XML 解析失败 {exc}")
    # 时间窗口过滤
    papers = [p for p in papers if p.published and _within_days(p.published, days)]
    log.info("arxiv: 抓取 %s 篇（窗口 %s 天）", len(papers), days)
    return papers


# ---------------- OpenAlex ----------------


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    """OpenAlex 倒排摘要还原为顺序文本。"""
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        for idx in indexes or []:
            positions.append((int(idx), word))
    positions.sort()
    return " ".join(word for _, word in positions)


def parse_openalex_json(data: dict[str, Any]) -> list[PaperIn]:
    """解析 OpenAlex works 响应 -> PaperIn 列表（缺摘要 -> ""，URL 仅保留 http(s)）。"""
    papers: list[PaperIn] = []
    for work in (data or {}).get("results", []) or []:
        raw_id = (work.get("id") or "").rstrip("/")
        external_id = raw_id.rsplit("/", 1)[-1] if raw_id else ""
        title = _flatten(work.get("title") or work.get("display_name"))
        if not external_id or not title:
            continue
        doi = (work.get("doi") or "").strip()
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi) or None
        primary = work.get("primary_location") or {}
        url = _safe_url(primary.get("landing_page_url"))
        if not url and doi:
            url = _safe_url(f"https://doi.org/{doi}")
        if not url:
            continue  # 契约：外链只允许 http(s)
        published = (work.get("publication_date") or "").strip()
        if not published:
            year = work.get("publication_year")
            published = f"{year}-01-01" if year else ""
        if not published:
            continue
        authors = [
            _flatten((authorship.get("author") or {}).get("display_name"))
            for authorship in work.get("authorships", []) or []
        ]
        authors = [a for a in authors if a]
        papers.append(
            PaperIn(
                source="openalex",
                external_id=external_id,
                title=title,
                published=published[:10],
                url=url,
                abstract=_clean_abstract(_reconstruct_abstract(work.get("abstract_inverted_index"))),
                authors=authors,
                doi=doi,
            )
        )
    return papers


def fetch_openalex(
    days: int,
    limit: int,
    settings: config.Settings | None = None,
    session: requests.Session | None = None,
    errors: list[str] | None = None,
) -> list[PaperIn]:
    """抓取 OpenAlex：6 条短语检索串，每条 per-page = max(5, limit//2)。

    filter 用 title_and_abstract.search 提高精度；type 限定 article/review/preprint。
    可选 OPENALEX_API_KEY 走用户自己的配额（无 key 时是出口 IP 共享的免费额度）。
    """
    errors = errors if errors is not None else []
    settings = settings or config.load_settings()
    session = session or make_session(settings)
    per_query = max(5, int(limit) // 2)
    from_date = _cutoff(days)
    papers: list[PaperIn] = []
    for query in config.OPENALEX_QUERIES:
        params = {
            "filter": (
                f"from_publication_date:{from_date},"
                f"title_and_abstract.search:{query},"
                "type:article|review|preprint"
            ),
            "per-page": per_query,
            "sort": "publication_date:desc",
        }
        if settings.openalex_mailto:
            params["mailto"] = settings.openalex_mailto
        if settings.openalex_api_key:
            params["api_key"] = settings.openalex_api_key
        resp = _get_with_retry(session, OPENALEX_API, params, errors, "openalex")
        if resp is None:
            continue
        try:
            papers.extend(parse_openalex_json(resp.json()))
        except ValueError as exc:
            errors.append(f"openalex: JSON 解析失败 {exc}")
    papers = [p for p in papers if p.published and _within_days(p.published, days)]
    log.info("openalex: 抓取 %s 篇（窗口 %s 天）", len(papers), days)
    return papers


# ---------------- Semantic Scholar（可选） ----------------

S2_API_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,authors,publicationDate,externalIds,openAccessPdf"
# 无 Key bootstrap 专用：慢速重试（lead 2026-11-01 批准）
S2_BOOTSTRAP_RETRY_DELAYS = (20.0, 40.0, 60.0)
S2_BOOTSTRAP_MIN_INTERVAL = 5.0


def _parse_s2_items(items: list[dict[str, Any]]) -> list[PaperIn]:
    """S2 /paper/search 的 data 数组 -> PaperIn（URL 依次 fallback，仅保留 http(s)）。"""
    papers: list[PaperIn] = []
    for item in items or []:
        title = _flatten(item.get("title"))
        ext = item.get("externalIds") or {}
        external_id = str(ext.get("ArXiv") or item.get("paperId") or "").strip()
        published = (item.get("publicationDate") or "")[:10]
        if not title or not external_id or not published:
            continue
        doi = (str(ext.get("DOI")) if ext.get("DOI") else None) or None
        url = _safe_url((item.get("openAccessPdf") or {}).get("url"))
        if not url and ext.get("ArXiv"):
            url = _safe_url(f"https://arxiv.org/abs/{ext['ArXiv']}")
        if not url and doi:
            url = _safe_url(f"https://doi.org/{doi}")
        if not url:
            url = _safe_url(f"https://www.semanticscholar.org/paper/{item.get('paperId')}")
        if not url:
            continue
        authors = [_flatten((a or {}).get("name")) for a in item.get("authors", []) or []]
        papers.append(
            PaperIn(
                source="semantic_scholar",
                external_id=external_id,
                title=title,
                published=published,
                url=url,
                abstract=_clean_abstract(item.get("abstract")),
                authors=[a for a in authors if a],
                doi=doi,
            )
        )
    return papers


def _s2_get(
    session: requests.Session,
    params: dict[str, Any],
    errors: list[str],
    *,
    headers: dict[str, str] | None = None,
    retry_delays: tuple[float, ...] = RETRY_DELAYS,
) -> requests.Response | None:
    """S2 GET + 退避重试；429 优先使用响应 Retry-After（上限 90s，避免长时间挂起）。"""
    attempts = len(retry_delays) + 1
    for attempt in range(attempts):
        try:
            resp = session.get(S2_API_BASE, params=params, timeout=TIMEOUT, headers=headers)
        except requests.RequestException as exc:
            if attempt < len(retry_delays):
                log.warning("semantic_scholar: 网络错误 %s，%.0fs 后重试", type(exc).__name__, retry_delays[attempt])
                time.sleep(retry_delays[attempt])
                continue
            errors.append(f"semantic_scholar: 网络错误 {type(exc).__name__}: {exc}")
            return None
        if resp.status_code in (429, 503):
            if attempt < len(retry_delays):
                wait = retry_delays[attempt]
                try:
                    retry_after = float(resp.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    retry_after = 0.0
                if 0 < retry_after <= 90:
                    wait = retry_after
                log.warning("semantic_scholar: HTTP %s，%.0fs 后重试", resp.status_code, wait)
                time.sleep(wait)
                continue
            errors.append(f"semantic_scholar: HTTP {resp.status_code}（重试 {attempt} 次仍失败）")
            return None
        if resp.status_code >= 400:
            errors.append(f"semantic_scholar: HTTP {resp.status_code}")
            return None
        return resp
    return None


def fetch_semantic_scholar(
    days: int,
    limit: int,
    settings: config.Settings | None = None,
    session: requests.Session | None = None,
    errors: list[str] | None = None,
) -> list[PaperIn]:
    """Semantic Scholar 补充源；无 Key 抛 SourceDisabled，由 fetch_all 跳过。"""
    settings = settings or config.load_settings()
    if not settings.semantic_scholar_api_key:
        raise SourceDisabled("semantic_scholar: 未配置 API Key")
    errors = errors if errors is not None else []
    session = session or make_session(settings)
    per_query = max(5, int(limit) // 2)
    start = _cutoff(days)
    end = date.today().isoformat()
    headers = {"x-api-key": settings.semantic_scholar_api_key}
    papers: list[PaperIn] = []
    for query in config.S2_BOOTSTRAP_QUERIES[:2]:
        params = {
            "query": query,
            "fields": S2_FIELDS,
            "limit": per_query,
            "publicationDateOrYear": f"{start}:{end}",
        }
        resp = _s2_get(session, params, errors, headers=headers)
        if resp is None:
            continue
        try:
            papers.extend(_parse_s2_items((resp.json() or {}).get("data") or []))
        except ValueError as exc:
            errors.append(f"semantic_scholar: JSON 解析失败 {exc}")
    papers = [p for p in papers if p.published and _within_days(p.published, days)]
    return papers


def fetch_semantic_scholar_bootstrap(
    days: int = 90,
    per_query: int = 25,
    session: requests.Session | None = None,
    errors: list[str] | None = None,
) -> list[PaperIn]:
    """Semantic Scholar 无 Key 一次性 bootstrap（仅用于生成 seed，不进 fetch_all 常规刷新）。

    - 4 组查询（config.S2_BOOTSTRAP_QUERIES），每组 limit 20~30
    - 查询间隔 ≥5s；429/503 退避 20/40/60s 最多重试 3 次
    """
    errors = errors if errors is not None else []
    session = session or make_session()
    per_query = max(20, min(30, int(per_query)))
    start = _cutoff(days)
    end = date.today().isoformat()
    papers: list[PaperIn] = []
    for index, query in enumerate(config.S2_BOOTSTRAP_QUERIES):
        if index:
            time.sleep(S2_BOOTSTRAP_MIN_INTERVAL)
        params = {
            "query": query,
            "fields": S2_FIELDS,
            "limit": per_query,
            "publicationDateOrYear": f"{start}:{end}",
        }
        resp = _s2_get(session, params, errors, retry_delays=S2_BOOTSTRAP_RETRY_DELAYS)
        if resp is None:
            continue
        try:
            papers.extend(_parse_s2_items((resp.json() or {}).get("data") or []))
        except ValueError as exc:
            errors.append(f"semantic_scholar: JSON 解析失败 {exc}")
    papers = [p for p in papers if p.published and _within_days(p.published, days)]
    log.info("semantic_scholar bootstrap: 抓取 %s 篇（窗口 %s 天）", len(papers), days)
    return papers


# ---------------- 去重 / 相关性 / 汇总 ----------------


def dedupe(papers: list[PaperIn]) -> list[PaperIn]:
    """三键去重：(source, external_id) -> DOI -> 规范化标题。保持首次出现顺序。"""
    seen: set[tuple[str, str]] = set()
    result: list[PaperIn] = []
    for paper in papers:
        keys: list[tuple[str, str]] = [("source", f"{paper.source}:{paper.external_id}")]
        if paper.doi:
            keys.append(("doi", paper.doi.strip().lower()))
        norm = _norm_title(paper.title)
        if norm:
            keys.append(("title", norm))
        if any(key in seen for key in keys):
            continue
        seen.update(keys)
        result.append(paper)
    return result


def is_relevant(title: str, abstract: str = "") -> bool:
    """标题+摘要小写包含任一航空语境词。"""
    text = f"{title or ''} {abstract or ''}".lower()
    return any(term in text for term in config.AVIATION_TERMS)


def fetch_all(
    days: int = 90,
    limit: int = 20,
    settings: config.Settings | None = None,
    session: requests.Session | None = None,
) -> tuple[list[PaperIn], list[str]]:
    """按源抓取 -> 相关性过滤 -> 去重 -> 按发表时间倒序。单源失败不阻塞。"""
    settings = settings or config.load_settings()
    session = session or make_session(settings)
    errors: list[str] = []
    papers: list[PaperIn] = []

    for source, fetcher in (
        ("arxiv", lambda: fetch_arxiv(days, limit, session, errors)),
        ("openalex", lambda: fetch_openalex(days, limit, settings, session, errors)),
        (
            "semantic_scholar",
            lambda: fetch_semantic_scholar(days, limit, settings, session, errors),
        ),
    ):
        try:
            papers.extend(fetcher())
        except SourceDisabled as exc:
            log.info("%s 跳过：%s", source, exc)
        except Exception as exc:  # 单源失败不阻塞其他源
            log.exception("%s 抓取异常", source)
            errors.append(f"{source}: {type(exc).__name__}: {exc}")

    before = len(papers)
    papers = [p for p in papers if is_relevant(p.title, p.abstract)]
    relevant = len(papers)
    papers = dedupe(papers)
    papers.sort(key=lambda p: (p.published, p.source), reverse=True)
    log.info(
        "fetch_all: 原始 %s -> 相关性 %s -> 去重 %s（errors=%s）",
        before,
        relevant,
        len(papers),
        len(errors),
    )
    return papers, errors
