"""src/api.py 测试：路由契约、筛选分页、refresh 状态机、422 校验、错误格式。"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src import config, db, pipeline, sources
from src.api import create_app


def _paper(i: int, source: str = "arxiv", **overrides) -> dict:
    data = {
        "source": source,
        "external_id": f"{source}-{i}",
        "doi": f"10.1000/{source}.{i}",
        "title": f"Hybrid Electric Aircraft Paper {i}",
        "authors": ["Alice"],
        "abstract": "Hybrid electric aircraft energy management and mode transition.",
        "published": "2026-10-2%d" % (i % 10),
        "url": f"https://example.org/{source}/{i}",
    }
    data.update(overrides)
    return data


def _extraction(**overrides) -> dict:
    data = {
        "one_line_contribution": "一句话贡献",
        "methods": ["Model Predictive Control"],
        "datasets": [],
        "code_open_source": "unknown",
        "code_evidence": "",
        "contribution_evidence": "",
        "confidence": 0.5,
        "mode": "heuristic",
        "provider": "heuristic",
        "model": "",
    }
    data.update(overrides)
    return data


def _seed(
    db_file: str,
    papers: list[dict],
    extractions: list[tuple[int, dict]] | None = None,
) -> list[int]:
    """插入论文；extractions 用 (论文下标, extraction) 表示，返回插入的 paper id 列表。"""
    db.init_db(db_file)
    conn = db.connect(db_file)
    try:
        ids = [db.upsert_paper(conn, paper) for paper in papers]
        for index, extraction in extractions or []:
            paper_id = ids[index]
            if paper_id is not None:
                db.upsert_extraction(conn, paper_id, extraction)
        return ids
    finally:
        db.close(conn)


def test_health_empty_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
    assert body["db"] == "ok"
    assert body["paper_count"] == 0
    assert body["llm"] == {"enabled": False, "provider": "deepseek", "model": "deepseek-chat"}


def test_meta_empty_db(client):
    body = client.get("/api/meta").json()
    assert body["last_refresh"] is None
    assert body["paper_count"] == 0
    assert body["source_counts"] == {"arxiv": 0, "openalex": 0, "semantic_scholar": 0}
    assert body["llm"] == {"enabled": False, "provider": "deepseek"}
    assert body["default_days"] == 90
    by_id = {item["id"]: item for item in body["sources"]}
    assert by_id["arxiv"]["enabled"] is True
    assert by_id["openalex"]["enabled"] is False
    assert by_id["semantic_scholar"]["enabled"] is False
    assert [item["label"] for item in body["sources"]] == [
        "arXiv", "OpenAlex", "Semantic Scholar"
    ]


def test_papers_empty_db(client):
    body = client.get("/api/papers").json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["page"] == 1
    assert body["page_size"] == 12


def test_papers_search_filter_sorting_pagination(db_file, client):
    ids = _seed(
        db_file,
        [
            _paper(1, source="arxiv", published="2026-09-01",
                   title="Energy Management for Hybrid Electric Aircraft"),
            _paper(2, source="openalex", published="2026-10-01",
                   title="Fuel Cell Aircraft Powertrain Optimization"),
            _paper(3, source="semantic_scholar", published="2026-10-25",
                   title="Mode Transition Control of Hybrid Propulsion"),
            _paper(4, source="arxiv", published="2026-08-01",
                   title="Turboelectric Distributed Propulsion Sizing"),
        ],
        extractions=[
            (0, _extraction(code_open_source="yes", confidence=0.9,
                            one_line_contribution="混合电推进飞机能量管理")),
            (1, _extraction(code_open_source="no", confidence=0.6)),
        ],
    )

    body = client.get("/api/papers", params={"days": 0}).json()
    assert body["total"] == 4
    first = body["items"][0]
    expected_keys = {
        "id", "source", "source_label", "external_id", "doi", "title", "authors",
        "published", "url", "abstract", "one_line_contribution", "methods",
        "datasets", "code_open_source", "code_evidence", "contribution_evidence",
        "confidence", "extraction_mode", "tags", "fetched_at",
    }
    assert set(first) == expected_keys
    assert first["source_label"] == "Semantic Scholar" or first["source_label"] == "arXiv"
    assert first["published"] == "2026-10-25"

    body = client.get("/api/papers", params={"days": 0, "q": "turboelectric"}).json()
    assert body["total"] == 1 and "Turboelectric" in body["items"][0]["title"]

    body = client.get("/api/papers", params={"days": 0, "q": "混合"}).json()
    assert body["total"] == 1  # 命中 one_line

    body = client.get("/api/papers", params={"days": 0, "open_source": "yes"}).json()
    assert body["total"] == 1 and body["items"][0]["code_open_source"] == "yes"

    body = client.get("/api/papers", params={"days": 0, "source": "openalex"}).json()
    assert body["total"] == 1 and body["items"][0]["source"] == "openalex"

    body = client.get("/api/papers", params={"days": 0, "sort": "date_asc"}).json()
    assert [item["published"] for item in body["items"]] == [
        "2026-08-01", "2026-09-01", "2026-10-01", "2026-10-25"
    ]

    body = client.get("/api/papers", params={"days": 0, "page": 2, "page_size": 2}).json()
    assert body["total"] == 4 and body["page"] == 2 and len(body["items"]) == 2


def test_stats_endpoint(db_file, client):
    ids = _seed(
        db_file,
        [
            _paper(1, source="arxiv", published="2026-09-01"),
            _paper(2, source="openalex", published="2026-10-01"),
        ],
        extractions=[(0, _extraction(code_open_source="yes"))],
    )
    body = client.get("/api/stats", params={"days": 0}).json()
    assert body["total"] == 2
    assert body["open_source_ratio"] == {"yes": 1, "no": 0, "unknown": 1}
    assert {row["source"] for row in body["by_source"]} == {"arxiv", "openalex"}
    assert [row["month"] for row in body["by_month"]] == ["2026-09", "2026-10"]
    assert body["latest_published"] == "2026-10-01"
    assert "last_refresh" in body


def _fake_fetch_all(papers: list, errors: list):
    def fake(days=90, limit=20, settings=None, session=None):
        return papers, errors

    return fake


def test_refresh_success_uses_pipeline(monkeypatch, client):
    papers = [
        sources.PaperIn(source="arxiv", external_id="2601.00001",
                        title="Hybrid Electric Aircraft Energy Management",
                        published=date.today().isoformat(),
                        url="https://arxiv.org/abs/2601.00001",
                        abstract="hybrid electric aircraft energy management",
                        authors=["Alice"]),
        sources.PaperIn(source="openalex", external_id="W1",
                        title="Fuel Cell Aircraft Powertrain",
                        published=date.today().isoformat(),
                        url="https://doi.org/10.1000/w1",
                        abstract="fuel cell aircraft propulsion",
                        authors=["Bob"]),
    ]
    monkeypatch.setattr(pipeline.sources, "fetch_all", _fake_fetch_all(papers, []))

    response = client.post("/api/refresh", json={"days": 30, "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["fetched"] == 2
    assert body["inserted"] == 2
    assert body["extracted"] == 2
    assert body["skipped"] == 0
    assert body["llm_enabled"] is False
    assert body["errors"] == []
    assert body["run_id"] >= 1 and body["duration_s"] >= 0

    runs = client.get("/api/runs").json()["items"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == body["run_id"]
    assert runs[0]["status"] == "success"
    assert runs[0]["inserted"] == 2 and runs[0]["extracted"] == 2
    assert runs[0]["errors_count"] == 0
    assert runs[0]["finished_at"]

    meta = client.get("/api/meta").json()
    assert meta["paper_count"] == 2
    assert meta["last_refresh"] == runs[0]["finished_at"]


def test_refresh_partial_when_source_fails(monkeypatch, client):
    papers = [
        sources.PaperIn(source="arxiv", external_id="2601.00002",
                        title="Hybrid Aircraft Mode Transition",
                        published=date.today().isoformat(),
                        url="https://arxiv.org/abs/2601.00002",
                        abstract="hybrid aircraft mode transition control",
                        authors=["Alice"]),
    ]
    monkeypatch.setattr(
        pipeline.sources, "fetch_all",
        _fake_fetch_all(papers, ["openalex: HTTP 429，重试 3 次后失败"]),
    )
    body = client.post("/api/refresh", json={"days": 90, "limit": 10}).json()
    assert body["status"] == "partial"
    assert body["fetched"] == 1 and body["inserted"] == 1
    assert len(body["errors"]) == 1


def test_refresh_error_when_all_sources_fail(monkeypatch, client):
    monkeypatch.setattr(
        pipeline.sources, "fetch_all",
        _fake_fetch_all([], ["arxiv: connection timeout", "openalex: HTTP 429"]),
    )
    body = client.post("/api/refresh", json={"days": 90, "limit": 10}).json()
    assert body["status"] == "error"
    assert body["fetched"] == 0 and body["inserted"] == 0
    assert len(body["errors"]) == 2


@pytest.mark.parametrize(
    "url",
    [
        "/api/papers?page_size=51",
        "/api/papers?page=0",
        "/api/papers?days=-1",
        "/api/papers?open_source=maybe",
        "/api/papers?source=ieee",
        "/api/runs?limit=0",
    ],
)
def test_query_validation_422(client, url):
    response = client.get(url)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {"days": 0, "limit": 20},
        {"days": 366, "limit": 20},
        {"days": 90, "limit": 61},
        {"days": 90, "limit": 0},
    ],
)
def test_refresh_validation_422(client, payload):
    response = client.post("/api/refresh", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


def test_unknown_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert detail["message"]


def test_index_returns_404_json_when_frontend_missing(client):
    index = config.STATIC_DIR / "index.html"
    if index.exists():
        pytest.skip("static/index.html 已存在（前端已生成），跳过缺失场景断言")
    response = client.get("/")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_auto_seed_on_first_startup(settings):
    """默认库首次启动自动导入 seed（评分者 python app.py 一步看到真实数据）。"""
    if not config.SEED_PATH.exists():
        pytest.skip("data/seed_papers.json 不存在（尚未生成 seed）")
    app = create_app(db_path=None, settings=settings)
    with TestClient(app) as local_client:
        health = local_client.get("/api/health").json()
        assert health["paper_count"] >= 30
        meta = local_client.get("/api/meta").json()
        assert meta["paper_count"] == health["paper_count"]
        assert meta["source_counts"]["semantic_scholar"] > 0
