"""SQLite 数据层：建表、论文/提取结果入库、查询分页、统计、运行记录。

契约参考：技术设计文档.md §4。
- WAL 模式；papers 以 (source, external_id) 唯一；upsert_paper 冲突返回 None
- extractions 以 paper_id 为主键（INSERT OR REPLACE 覆盖）
- runs 记录每次刷新（running -> success/partial/error）
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    abstract TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_papers_published ON papers (published);

CREATE TABLE IF NOT EXISTS extractions (
    paper_id INTEGER PRIMARY KEY REFERENCES papers (id) ON DELETE CASCADE,
    one_line TEXT NOT NULL DEFAULT '',
    methods TEXT NOT NULL DEFAULT '[]',
    datasets TEXT NOT NULL DEFAULT '[]',
    code_open_source TEXT NOT NULL DEFAULT 'unknown',
    code_evidence TEXT NOT NULL DEFAULT '',
    contribution_evidence TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'heuristic',
    provider TEXT,
    model TEXT,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    days INTEGER NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    extracted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    errors TEXT NOT NULL DEFAULT '[]'
);
"""

# 前端展示用列（papers LEFT JOIN extractions）
_PAPER_FIELDS = """
    p.id, p.source, p.external_id, p.doi, p.title, p.authors, p.abstract,
    p.published, p.url, p.fetched_at,
    e.one_line, e.methods, e.datasets, e.code_open_source, e.code_evidence,
    e.contribution_evidence, e.confidence, e.mode
"""
_PAPER_FROM = " FROM papers p LEFT JOIN extractions e ON e.paper_id = p.id "


def now_iso() -> str:
    """当前 UTC 时间 ISO8601（带时区）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path_default() -> str:
    return str(config.DB_PATH)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """打开连接：WAL、外键、Row 工厂、busy_timeout。"""
    path = str(db_path or db_path_default())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def close(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error:  # pragma: no cover - 关闭失败不影响业务
        pass


@contextmanager
def open_db(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """短连接上下文：API 每次请求 / pipeline 单次刷新使用。"""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        close(conn)


def init_db(db_path: str | Path | None = None) -> None:
    """建表（幂等）+ 打开 WAL。"""
    with open_db(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


# ---------------- JSON 小工具 ----------------


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _loads_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _loads_dict(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# ---------------- papers ----------------


def upsert_paper(conn: sqlite3.Connection, paper: dict[str, Any] | Any) -> int | None:
    """入库论文；冲突（同 source+external_id）不新增并返回 None，否则返回新 id。"""
    data = paper.to_dict() if hasattr(paper, "to_dict") else dict(paper)
    params = (
        str(data.get("source") or ""),
        str(data.get("external_id") or ""),
        (str(data["doi"]) if data.get("doi") else None),
        str(data.get("title") or ""),
        _dumps(list(data.get("authors") or [])),
        str(data.get("abstract") or ""),
        str(data.get("published") or "")[:10],
        str(data.get("url") or ""),
        str(data.get("fetched_at") or now_iso()),
    )
    cur = conn.execute(
        "INSERT INTO papers (source, external_id, doi, title, authors, abstract, published, url, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (source, external_id) DO NOTHING",
        params,
    )
    conn.commit()
    return int(cur.lastrowid) if cur.rowcount == 1 else None


def get_paper(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT {_PAPER_FIELDS} {_PAPER_FROM} WHERE p.id = ?", (int(paper_id),)).fetchone()
    return paper_row_to_item(row) if row else None


def get_paper_by_external(conn: sqlite3.Connection, source: str, external_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_PAPER_FIELDS} {_PAPER_FROM} WHERE p.source = ? AND p.external_id = ?",
        (source, external_id),
    ).fetchone()
    return paper_row_to_item(row) if row else None


def paper_count(conn: sqlite3.Connection, days: int = 0) -> int:
    """论文总数；days>0 时只统计窗口内。"""
    if days and days > 0:
        cutoff = (date.today() - timedelta(days=int(days))).isoformat()
        row = conn.execute("SELECT COUNT(*) AS n FROM papers WHERE published >= ?", (cutoff,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()
    return int(row["n"] if row else 0)


def _build_filter(
    q: str = "",
    open_source: str = "",
    source: str = "",
    days: int = 0,
    params: list[Any] | None = None,
) -> tuple[str, list[Any]]:
    params = list(params or [])
    clauses: list[str] = []
    if q:
        like = f"%{q.strip()}%"
        clauses.append("(p.title LIKE ? OR p.abstract LIKE ? OR e.one_line LIKE ?)")
        params.extend([like, like, like])
    if open_source:
        clauses.append("COALESCE(e.code_open_source, 'unknown') = ?")
        params.append(open_source)
    if source:
        clauses.append("p.source = ?")
        params.append(source)
    if days and days > 0:
        clauses.append("p.published >= ?")
        params.append((date.today() - timedelta(days=int(days))).isoformat())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_papers(
    conn: sqlite3.Connection,
    q: str = "",
    open_source: str = "",
    source: str = "",
    days: int = 0,
    sort: str = "date_desc",
    page: int = 1,
    page_size: int = 12,
) -> tuple[int, list[dict[str, Any]]]:
    """按筛选条件分页查询论文，返回 (total, items)。"""
    where, params = _build_filter(q, open_source, source, days)
    total = int(conn.execute(f"SELECT COUNT(*) AS n {_PAPER_FROM} {where}", params).fetchone()["n"])
    order = {
        "date_desc": "p.published DESC, p.id DESC",
        "date_asc": "p.published ASC, p.id ASC",
        "confidence_desc": "COALESCE(e.confidence, 0) DESC, p.published DESC, p.id DESC",
    }.get(sort or "date_desc", "p.published DESC, p.id DESC")
    offset = (max(1, int(page)) - 1) * int(page_size)
    rows = conn.execute(
        f"SELECT {_PAPER_FIELDS} {_PAPER_FROM} {where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, int(page_size), offset],
    ).fetchall()
    return total, [paper_row_to_item(row) for row in rows]


def papers_missing_extraction(conn: sqlite3.Connection, limit: int = 0) -> list[dict[str, Any]]:
    """尚未有提取结果的论文（按入库时间倒序）。"""
    sql = f"SELECT {_PAPER_FIELDS} {_PAPER_FROM} WHERE e.paper_id IS NULL ORDER BY p.id DESC"
    params: list[Any] = []
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [paper_row_to_item(row) for row in conn.execute(sql, params).fetchall()]


def paper_row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    """DB 行 -> API 论文条目（JSON 字段反序列化 + tags 计算）。"""
    item = {
        "id": int(row["id"]),
        "source": row["source"],
        "source_label": config.SOURCE_LABELS.get(row["source"], row["source"]),
        "external_id": row["external_id"],
        "doi": row["doi"],
        "title": row["title"],
        "authors": [str(a) for a in _loads_list(row["authors"])],
        "published": row["published"],
        "url": row["url"],
        "abstract": row["abstract"] or "",
        "one_line_contribution": row["one_line"] or "",
        "methods": [str(m) for m in _loads_list(row["methods"])],
        "datasets": [str(d) for d in _loads_list(row["datasets"])],
        "code_open_source": row["code_open_source"] or "unknown",
        "code_evidence": row["code_evidence"] or "",
        "contribution_evidence": row["contribution_evidence"] or "",
        "confidence": float(row["confidence"] or 0.0),
        "extraction_mode": row["mode"] or "heuristic",
        "tags": config.compute_tags(
            row["title"] or "",
            _loads_list(row["methods"]),
            row["abstract"] or "",
        ),
        "fetched_at": row["fetched_at"],
    }
    return item


# ---------------- extractions ----------------


def upsert_extraction(conn: sqlite3.Connection, paper_id: int, extraction: dict[str, Any]) -> None:
    """写入/覆盖提取结果（paper_id 主键）。"""
    data = extraction or {}
    mode = str(data.get("mode") or data.get("extraction_mode") or "heuristic")
    conn.execute(
        "INSERT OR REPLACE INTO extractions ("
        "paper_id, one_line, methods, datasets, code_open_source, code_evidence, "
        "contribution_evidence, confidence, mode, provider, model, extracted_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            int(paper_id),
            str(data.get("one_line_contribution") or data.get("one_line") or ""),
            _dumps(list(data.get("methods") or [])),
            _dumps(list(data.get("datasets") or [])),
            str(data.get("code_open_source") or "unknown"),
            str(data.get("code_evidence") or ""),
            str(data.get("contribution_evidence") or ""),
            float(data.get("confidence") or 0.0),
            mode,
            data.get("provider"),
            data.get("model"),
            str(data.get("extracted_at") or now_iso()),
        ),
    )
    conn.commit()


def get_extraction(conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM extractions WHERE paper_id = ?", (int(paper_id),)).fetchone()
    if not row:
        return None
    return {
        "one_line_contribution": row["one_line"],
        "methods": _loads_list(row["methods"]),
        "datasets": _loads_list(row["datasets"]),
        "code_open_source": row["code_open_source"],
        "code_evidence": row["code_evidence"],
        "contribution_evidence": row["contribution_evidence"],
        "confidence": float(row["confidence"] or 0.0),
        "mode": row["mode"],
        "provider": row["provider"],
        "model": row["model"],
        "extracted_at": row["extracted_at"],
    }


def all_papers_with_extractions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """导出用：全部论文 + 可选提取结果（按发表时间倒序）。"""
    rows = conn.execute(
        f"SELECT {_PAPER_FIELDS}, e.provider AS e_provider, e.model AS e_model, e.extracted_at AS e_extracted_at "
        f"{_PAPER_FROM} ORDER BY p.published DESC, p.id DESC"
    ).fetchall()
    out = []
    for row in rows:
        item = paper_row_to_item(row)
        has_extraction = row["mode"] is not None
        extraction = None
        if has_extraction:
            extraction = {
                "one_line_contribution": item["one_line_contribution"],
                "methods": item["methods"],
                "datasets": item["datasets"],
                "code_open_source": item["code_open_source"],
                "code_evidence": item["code_evidence"],
                "contribution_evidence": item["contribution_evidence"],
                "confidence": item["confidence"],
                "mode": item["extraction_mode"],
                "provider": row["e_provider"],
                "model": row["e_model"],
                "extracted_at": row["e_extracted_at"],
            }
        out.append(
            {
                "source": item["source"],
                "external_id": item["external_id"],
                "doi": item["doi"],
                "title": item["title"],
                "authors": item["authors"],
                "abstract": item["abstract"],
                "published": item["published"],
                "url": item["url"],
                "fetched_at": item["fetched_at"],
                "extraction": extraction,
            }
        )
    return out


# ---------------- stats ----------------


def source_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT source, COUNT(*) AS n FROM papers GROUP BY source").fetchall()
    return {row["source"]: int(row["n"]) for row in rows}


def latest_published(conn: sqlite3.Connection, days: int = 0) -> str | None:
    where, params = _build_filter("", "", "", days)
    row = conn.execute(f"SELECT MAX(p.published) AS m FROM papers p {where}", params).fetchone()
    return row["m"] if row and row["m"] else None


def stats(conn: sqlite3.Connection, days: int = 0) -> dict[str, Any]:
    """看板统计：总数、开源三态、来源分布、月度分布、标签分布、最新发表、最近刷新。"""
    where, params = _build_filter("", "", "", days)
    base = f"FROM papers p LEFT JOIN extractions e ON e.paper_id = p.id {where}"

    total = int(conn.execute(f"SELECT COUNT(*) AS n {base}", params).fetchone()["n"])
    os_rows = conn.execute(
        f"SELECT COALESCE(e.code_open_source, 'unknown') AS k, COUNT(*) AS n {base} GROUP BY k",
        params,
    ).fetchall()
    open_source_ratio = {"yes": 0, "no": 0, "unknown": 0}
    for row in os_rows:
        key = row["k"] if row["k"] in open_source_ratio else "unknown"
        open_source_ratio[key] += int(row["n"])

    by_source = [
        {
            "source": row["source"],
            "label": config.SOURCE_LABELS.get(row["source"], row["source"]),
            "count": int(row["n"]),
        }
        for row in conn.execute(
            f"SELECT p.source, COUNT(*) AS n {base} GROUP BY p.source ORDER BY n DESC, p.source",
            params,
        ).fetchall()
    ]

    by_month = [
        {"month": row["m"], "count": int(row["n"])}
        for row in conn.execute(
            f"SELECT substr(p.published, 1, 7) AS m, COUNT(*) AS n {base} GROUP BY m HAVING m <> '' ORDER BY m ASC",
            params,
        ).fetchall()
    ]

    tag_counter: dict[str, int] = {}
    for row in conn.execute(
        f"SELECT p.title, p.abstract, e.methods {base}", params
    ).fetchall():
        for tag in config.compute_tags(row["title"] or "", _loads_list(row["methods"]), row["abstract"] or ""):
            tag_counter[tag] = tag_counter.get(tag, 0) + 1
    by_tag = [
        {"tag": tag, "count": count}
        for tag, count in sorted(tag_counter.items(), key=lambda kv: (-kv[1], config.TAG_VOCAB.index(kv[0]) if kv[0] in config.TAG_VOCAB else 99))
    ]

    return {
        "total": total,
        "open_source_ratio": open_source_ratio,
        "by_source": by_source,
        "by_month": by_month,
        "by_tag": by_tag,
        "latest_published": latest_published(conn, days),
        "last_refresh": last_refresh(conn),
    }


# ---------------- runs ----------------


def insert_run(conn: sqlite3.Connection, days: int) -> int:
    """开始一次刷新，返回 run_id。"""
    cur = conn.execute(
        "INSERT INTO runs (started_at, days, status) VALUES (?, ?, 'running')",
        (now_iso(), int(days)),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    fetched: int = 0,
    inserted: int = 0,
    extracted: int = 0,
    errors: Iterable[str] | None = None,
) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, status = ?, fetched = ?, inserted = ?, extracted = ?, errors = ? WHERE id = ?",
        (now_iso(), status, int(fetched), int(inserted), int(extracted), _dumps(list(errors or [])), int(run_id)),
    )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    if not row:
        return None
    return {
        "run_id": int(row["id"]),
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "days": int(row["days"]),
        "fetched": int(row["fetched"]),
        "inserted": int(row["inserted"]),
        "extracted": int(row["extracted"]),
        "errors": _loads_list(row["errors"]),
    }


def list_runs(conn: sqlite3.Connection, limit: int = 5) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [
        {
            "run_id": int(row["id"]),
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "days": int(row["days"]),
            "fetched": int(row["fetched"]),
            "inserted": int(row["inserted"]),
            "extracted": int(row["extracted"]),
            "errors_count": len(_loads_list(row["errors"])),
        }
        for row in rows
    ]


def last_refresh(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT finished_at FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["finished_at"] if row else None


def last_run_errors(conn: sqlite3.Connection, run_id: int) -> list[str]:
    row = conn.execute("SELECT errors FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    return _loads_list(row["errors"]) if row else []
