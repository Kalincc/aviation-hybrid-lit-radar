"""src/sources.py 测试：真实 fixture 解析、429 重试、去重、相关性、查询构造。

零真实网络：所有 HTTP 均用假 Session，sleep 用 monkeypatch 跳过。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src import config, sources
from src.sources import PaperIn

FIXTURES = Path(__file__).parent / "fixtures"


def _arxiv_xml() -> str:
    return (FIXTURES / "arxiv_sample.xml").read_text(encoding="utf-8")


def _openalex_data() -> dict:
    return json.loads((FIXTURES / "openalex_sample.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", payload: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload


def test_parse_arxiv_atom_fields_and_version_strip():
    papers = sources.parse_arxiv_atom(_arxiv_xml())
    assert len(papers) == 2
    for paper in papers:
        assert paper.source == "arxiv"
        assert paper.external_id and not re.search(r"v\d+$", paper.external_id)
        assert paper.url == f"https://arxiv.org/abs/{paper.external_id}"
        assert paper.title and paper.abstract
        assert len(paper.published) == 10 and paper.published[4] == "-"
        assert isinstance(paper.authors, list) and paper.authors


def test_parse_openalex_inverted_abstract_restored():
    papers = sources.parse_openalex_json(_openalex_data())
    assert len(papers) == 3
    first = papers[0]
    # 倒排索引还原后应能读到完整句子
    assert first.abstract.startswith("Abstract")
    assert "Sustainable Aviation Fuel" in first.abstract
    assert first.doi == "10.1007/978-3-032-37207-9_81"
    assert first.url.startswith("https://doi.org/")
    assert first.authors and first.published
    for paper in papers:
        assert paper.source == "openalex"
        assert paper.abstract


def test_arxiv_retry_on_429_then_success(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda _seconds: None)
    calls = {"n": 0}
    xml = _arxiv_xml()

    class FakeSession:
        def get(self, url, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(429)
            return FakeResponse(200, text=xml)

    errors: list[str] = []
    papers = sources.fetch_arxiv(days=0, limit=10, session=FakeSession(), errors=errors)
    assert calls["n"] == 5  # 1 次 429 + 重试成功 1 次 + 其余 3 组查询
    assert len(papers) == 8  # fixture 每查询 2 篇 × 4 组
    assert errors == []


def test_arxiv_gives_up_after_three_retries(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda _seconds: None)

    class Always429:
        def get(self, url, params=None, timeout=None):
            return FakeResponse(429)

    errors: list[str] = []
    papers = sources.fetch_arxiv(days=0, limit=10, session=Always429(), errors=errors)
    assert papers == []
    assert len(errors) == 4  # 每组查询各记 1 条错误
    assert all("429" in message for message in errors)


def test_dedupe_by_external_id_doi_and_title():
    papers = [
        PaperIn(source="arxiv", external_id="2601.00001", title="Hybrid Electric Aircraft Energy Management",
                published="2026-10-01", url="https://arxiv.org/abs/2601.00001"),
        PaperIn(source="openalex", external_id="W1", title="Different title A",
                published="2026-10-02", url="https://doi.org/10.1234/ABC", doi="10.1234/ABC"),
        PaperIn(source="semantic_scholar", external_id="S1", title="Different title B",
                published="2026-10-03", url="https://doi.org/10.1234/abc", doi="10.1234/abc"),
        PaperIn(source="openalex", external_id="W2", title="Hybrid-Electric Aircraft Energy Management!",
                published="2026-10-04", url="https://doi.org/10.5555/other",
                doi="10.5555/other"),
    ]
    unique = sources.dedupe(papers)
    assert len(unique) == 2
    assert unique[0].external_id == "2601.00001"
    assert unique[1].external_id == "W1"


def test_is_relevant_filters_ground_vehicles():
    assert sources.is_relevant(
        "Model predictive control for hybrid electric aircraft energy management",
        "Simulation results for a regional aircraft.",
    )
    assert not sources.is_relevant(
        "Hybrid electric vehicle energy management for passenger cars",
        "A ground vehicle powertrain test bench.",
    )


def test_build_arxiv_queries_has_four_groups():
    queries = sources.build_arxiv_queries()
    assert len(queries) == 4
    assert all(" OR " in query for query in queries)
    joined = " ".join(queries).lower()
    assert "hybrid" in joined and "energy management" in joined


def test_fetch_openalex_builds_search_filter_and_optional_key():
    settings = config.Settings(openalex_api_key="test-key", openalex_mailto="me@example.org")
    captured: list[dict] = []
    payload = _openalex_data()

    class FakeSession:
        def get(self, url, params=None, timeout=None):
            captured.append(dict(params or {}))
            return FakeResponse(200, payload=payload)

    errors: list[str] = []
    papers = sources.fetch_openalex(days=90, limit=40, settings=settings, session=FakeSession(), errors=errors)
    assert len(captured) == len(config.OPENALEX_QUERIES)  # 6 条查询
    params = captured[0]
    assert "from_publication_date:" in params["filter"]
    assert "title_and_abstract.search:" in params["filter"]
    assert "type:article|review|preprint" in params["filter"]
    assert params["per-page"] == 20  # max(5, 40//2)
    assert params["api_key"] == "test-key"
    assert params["mailto"] == "me@example.org"
    assert len(papers) >= 3 and not errors
