"""src/db.py 测试：建表幂等、upsert 去重、筛选/分页/排序、stats、run 生命周期。"""

from __future__ import annotations

from datetime import date, timedelta

from src import db


def _paper(i: int, source: str = "arxiv", published: str | None = None, **overrides) -> dict:
    data = {
        "source": source,
        "external_id": f"{source}-{i}",
        "doi": f"10.1000/{source}.{i}",
        "title": f"Hybrid Electric Aircraft Paper {i}",
        "authors": ["Alice", "Bob"],
        "abstract": "A hybrid electric aircraft energy management study.",
        "published": published or date.today().isoformat(),
        "url": f"https://example.org/{source}/{i}",
    }
    data.update(overrides)
    return data


def _extraction(**overrides) -> dict:
    data = {
        "one_line_contribution": "",
        "methods": [],
        "datasets": [],
        "code_open_source": "unknown",
        "code_evidence": "",
        "contribution_evidence": "",
        "confidence": 0.3,
        "mode": "heuristic",
        "provider": "heuristic",
        "model": "",
    }
    data.update(overrides)
    return data


def _seed(conn) -> dict[str, int]:
    ids = {
        "a": db.upsert_paper(
            conn, _paper(1, source="arxiv", published="2026-09-01",
                         title="Energy Management for Hybrid Electric Aircraft")
        ),
        "b": db.upsert_paper(
            conn, _paper(2, source="openalex", published="2026-10-01",
                         title="Fuel Cell Aircraft Powertrain Optimization")
        ),
        "c": db.upsert_paper(
            conn, _paper(3, source="semantic_scholar", published="2026-10-25",
                         title="Mode Transition Control of Hybrid Propulsion")
        ),
        "d": db.upsert_paper(
            conn, _paper(4, source="arxiv", published="2026-08-01",
                         title="Turboelectric Distributed Propulsion Sizing")
        ),
    }
    db.upsert_extraction(conn, ids["a"], _extraction(code_open_source="yes", confidence=0.9))
    db.upsert_extraction(conn, ids["b"], _extraction(code_open_source="no", confidence=0.5))
    db.upsert_extraction(conn, ids["d"], _extraction(code_open_source="unknown", confidence=0.1))
    return ids


def test_init_db_idempotent(tmp_path):
    path = str(tmp_path / "idem.db")
    db.init_db(path)
    db.init_db(path)
    with db.open_db(path) as conn:
        assert db.paper_count(conn) == 0


def test_upsert_paper_duplicate_not_inserted(conn):
    paper_id = db.upsert_paper(conn, _paper(1))
    assert paper_id is not None
    assert db.upsert_paper(conn, _paper(1)) is None
    assert db.paper_count(conn) == 1


def test_extraction_upsert_and_missing_list(conn):
    first = db.upsert_paper(conn, _paper(1))
    db.upsert_paper(conn, _paper(2))
    assert len(db.papers_missing_extraction(conn)) == 2

    db.upsert_extraction(
        conn,
        first,
        _extraction(one_line_contribution="一句话", methods=["Model Predictive Control"],
                    code_open_source="yes", code_evidence="The code is available.",
                    contribution_evidence="x", confidence=0.9, mode="llm",
                    provider="deepseek", model="deepseek-chat"),
    )
    missing = db.papers_missing_extraction(conn)
    assert len(missing) == 1 and missing[0]["id"] != first

    got = db.get_extraction(conn, first)
    assert got is not None and got["mode"] == "llm" and got["confidence"] == 0.9

    db.upsert_extraction(conn, first, _extraction(confidence=0.5))
    assert db.get_extraction(conn, first)["confidence"] == 0.5


def test_list_papers_filters_sorting_and_pagination(conn):
    _seed(conn)

    total, items = db.list_papers(conn, days=0)
    assert total == 4
    assert [item["published"] for item in items] == [
        "2026-10-25", "2026-10-01", "2026-09-01", "2026-08-01"
    ]

    total, date_asc = db.list_papers(conn, days=0, sort="date_asc")
    assert [item["published"] for item in date_asc] == [
        "2026-08-01", "2026-09-01", "2026-10-01", "2026-10-25"
    ]

    total, by_confidence = db.list_papers(conn, days=0, sort="confidence_desc")
    assert total == 4
    assert by_confidence[0]["confidence"] == 0.9
    assert by_confidence[-1]["confidence"] == 0.0  # 无 extraction 视为 0

    total, by_query = db.list_papers(conn, q="turboelectric", days=0)
    assert total == 1 and "Turboelectric" in by_query[0]["title"]

    total, by_source = db.list_papers(conn, source="arxiv", days=0)
    assert total == 2

    total, open_yes = db.list_papers(conn, open_source="yes", days=0)
    assert total == 1 and open_yes[0]["code_open_source"] == "yes"

    total, page_two = db.list_papers(conn, days=0, page=2, page_size=2)
    assert total == 4 and len(page_two) == 2

    total, windowed = db.list_papers(conn, days=60)
    assert total == 2  # 只保留 2026-10-01 与 2026-10-25


def test_paper_row_to_item_parses_json_and_computes_fields(conn):
    db.upsert_paper(conn, _paper(1))
    total, items = db.list_papers(conn, days=0)
    item = items[0]
    assert item["authors"] == ["Alice", "Bob"]
    assert item["methods"] == [] and item["datasets"] == []
    assert item["source_label"] == "arXiv"
    assert item["extraction_mode"] == "heuristic"
    assert isinstance(item["tags"], list)
    assert item["fetched_at"]


def test_stats_aggregation(conn):
    _seed(conn)
    result = db.stats(conn, days=0)
    assert result["total"] == 4
    assert result["open_source_ratio"] == {"yes": 1, "no": 1, "unknown": 2}
    by_source = {row["source"]: row["count"] for row in result["by_source"]}
    assert by_source == {"arxiv": 2, "openalex": 1, "semantic_scholar": 1}
    assert [row["month"] for row in result["by_month"]] == ["2026-08", "2026-09", "2026-10"]
    counts = [row["count"] for row in result["by_tag"]]
    assert counts == sorted(counts, reverse=True)
    assert result["latest_published"] == "2026-10-25"


def test_run_lifecycle(conn):
    run_id = db.insert_run(conn, days=30)
    items = db.list_runs(conn, limit=5)
    assert len(items) == 1
    assert items[0]["run_id"] == run_id and items[0]["status"] == "running"
    assert items[0]["finished_at"] is None
    assert db.last_refresh(conn) is None

    db.finish_run(conn, run_id, status="partial", fetched=10, inserted=3, extracted=2,
                  errors=["openalex: HTTP 429"])
    item = db.list_runs(conn, limit=5)[0]
    assert item["status"] == "partial"
    assert (item["fetched"], item["inserted"], item["extracted"]) == (10, 3, 2)
    assert item["errors_count"] == 1
    assert item["finished_at"] and db.last_refresh(conn) == item["finished_at"]


def test_paper_count_days_window(conn):
    today = date.today()
    db.upsert_paper(conn, _paper(1, published=(today - timedelta(days=5)).isoformat()))
    db.upsert_paper(conn, _paper(2, published=(today - timedelta(days=200)).isoformat()))
    assert db.paper_count(conn, days=30) == 1
    assert db.paper_count(conn, days=0) == 2
