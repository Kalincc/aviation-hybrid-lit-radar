"""刷新流水线 + seed 导入/导出 + CLI。

契约参考：技术设计文档.md §5.5（refresh 响应字段）、§7.2（缓存策略）、§13（seed 演示）。

用法：
    python -m src.pipeline --days 90 --limit 40
    python -m src.pipeline --load-seed
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from . import config, db, extractor, sources

log = logging.getLogger(__name__)


def _paper_payload(paper: sources.PaperIn, paper_id: int) -> dict[str, Any]:
    data = paper.to_dict()
    data["id"] = paper_id
    return data


def run_refresh(
    days: int = 90,
    limit: int = 20,
    extract: bool = True,
    db_path: str | Path | None = None,
    settings: config.Settings | None = None,
) -> dict[str, Any]:
    """抓取 -> 入库（新论文）-> LLM/启发式提取，返回 §5.5 refresh 响应字段。"""
    settings = settings or config.load_settings()
    db_file = str(db_path or settings.db_path)
    started = time.monotonic()
    db.init_db(db_file)

    errors: list[str] = []
    fetched = inserted = extracted = 0
    status = "success"
    llm_count = heuristic_count = 0

    with db.open_db(db_file) as conn:
        run_id = db.insert_run(conn, days)
        try:
            papers, source_errors = sources.fetch_all(days=days, limit=limit, settings=settings)
        except Exception as exc:  # noqa: BLE001 - 抓取层整体异常也要落 runs
            log.exception("fetch_all 异常")
            papers, source_errors = [], [f"fetch_all: {type(exc).__name__}: {exc}"]
        errors.extend(source_errors)
        fetched = len(papers)

        new_papers: list[dict[str, Any]] = []
        for paper in papers:
            paper_id = db.upsert_paper(conn, paper)
            if paper_id is not None:
                inserted += 1
                new_papers.append(_paper_payload(paper, paper_id))
        skipped = max(0, fetched - inserted)

        if extract and new_papers:
            # 缓存策略：只提取「新入库且尚无 extraction」的论文（新入库天然没有）
            targets = [p for p in new_papers if db.get_extraction(conn, int(p["id"])) is None]
            for result in extractor.extract_many(targets, settings):
                paper_id = result.get("paper_id")
                extraction = result.get("extraction")
                if paper_id is None or not extraction:
                    continue
                db.upsert_extraction(conn, int(paper_id), extraction)
                extracted += 1
                if extraction.get("mode") == "llm":
                    llm_count += 1
                else:
                    heuristic_count += 1

        # status：无错误 success；有源失败且有数据 partial；有源失败且零抓取 error
        if source_errors and fetched == 0:
            status = "error"
        elif source_errors:
            status = "partial"
        else:
            status = "success"
        db.finish_run(conn, run_id, status, fetched=fetched, inserted=inserted, extracted=extracted, errors=errors)

    duration_s = round(time.monotonic() - started, 1)
    log.info(
        "refresh 完成 run=%s status=%s fetched=%s inserted=%s extracted=%s(llm=%s heuristic=%s) duration=%.1fs",
        run_id,
        status,
        fetched,
        inserted,
        extracted,
        llm_count,
        heuristic_count,
        duration_s,
    )
    return {
        "run_id": run_id,
        "status": status,
        "fetched": fetched,
        "inserted": inserted,
        "extracted": extracted,
        "skipped": skipped,
        "llm_enabled": settings.llm_enabled,
        "errors": errors,
        "duration_s": duration_s,
    }


def load_seed(
    seed_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """离线导入 data/seed_papers.json（幂等：已存在的论文不重复插入）。"""
    path = Path(seed_path or config.SEED_PATH)
    if not path.exists():
        raise FileNotFoundError(f"seed 文件不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    papers = data.get("papers") or []
    db_file = str(db_path or config.DB_PATH)
    db.init_db(db_file)

    inserted = extracted = 0
    with db.open_db(db_file) as conn:
        for entry in papers:
            paper = {key: entry.get(key) for key in (
                "source", "external_id", "doi", "title", "authors",
                "abstract", "published", "url", "fetched_at",
            )}
            extraction = entry.get("extraction")
            paper_id = db.upsert_paper(conn, paper)
            if paper_id is None:
                # 已存在：仅当库中没有提取结果时补写（重复导入幂等）
                existing = db.get_paper_by_external(conn, paper["source"], paper["external_id"])
                if existing and extraction and db.get_extraction(conn, int(existing["id"])) is None:
                    db.upsert_extraction(conn, int(existing["id"]), extraction)
                    extracted += 1
                continue
            inserted += 1
            if extraction:
                db.upsert_extraction(conn, int(paper_id), extraction)
                extracted += 1
        # 记录一次「离线导入」run：让 meta.last_refresh / runs 在演示时可见
        run_id = db.insert_run(conn, int(data.get("window_days") or 90))
        db.finish_run(
            conn,
            run_id,
            "success",
            fetched=len(papers),
            inserted=inserted,
            extracted=extracted,
            errors=[],
        )

    result = {
        "seed_file": str(path),
        "papers": len(papers),
        "inserted": inserted,
        "skipped": len(papers) - inserted,
        "extracted": extracted,
        "run_id": run_id,
    }
    log.info("load_seed 完成：%s", result)
    return result


def export_seed(
    db_path: str | Path | None = None,
    seed_path: str | Path | None = None,
    window_days: int = 90,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把当前库导出为 seed JSON（真实抓取 + 真实提取结果）。"""
    db_file = str(db_path or config.DB_PATH)
    path = Path(seed_path or config.SEED_PATH)
    with db.open_db(db_file) as conn:
        items = db.all_papers_with_extractions(conn)
        source_counts = db.source_counts(conn)
        stats = db.stats(conn, days=0)

    papers = []
    for item in items:
        papers.append(
            {
                "source": item["source"],
                "external_id": item["external_id"],
                "doi": item.get("doi"),
                "title": item["title"],
                "authors": item.get("authors") or [],
                "abstract": item.get("abstract") or "",
                "published": item["published"],
                "url": item["url"],
                "fetched_at": item["fetched_at"],
                "extraction": item.get("extraction"),
            }
        )
    data = {
        "generated_at": db.now_iso(),
        "window_days": int(window_days),
        "paper_count": len(papers),
        "source_counts": source_counts,
        "stats": stats,
        "papers": papers,
    }
    if extra:
        data.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    llm = sum(1 for p in papers if (p.get("extraction") or {}).get("mode") == "llm")
    heuristic = sum(1 for p in papers if (p.get("extraction") or {}).get("mode") == "heuristic")
    result = {
        "seed_file": str(path),
        "papers": len(papers),
        "llm_extractions": llm,
        "heuristic_extractions": heuristic,
        "source_counts": source_counts,
    }
    log.info("export_seed 完成：%s", result)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Aviation Hybrid Lit Radar 抓取/提取流水线")
    parser.add_argument("--days", type=int, default=90, help="抓取时间窗口（天）")
    parser.add_argument("--limit", type=int, default=40, help="每源每查询的候选数量基数")
    parser.add_argument("--no-extract", action="store_true", help="只抓取入库，不做提取")
    parser.add_argument("--load-seed", action="store_true", help="离线导入 data/seed_papers.json")
    parser.add_argument("--seed", default=None, help="seed 文件路径（默认 data/seed_papers.json）")
    parser.add_argument("--db", default=None, help="数据库路径（默认 data/radar.db）")
    args = parser.parse_args(argv)

    config.setup_logging()
    if args.load_seed:
        result = load_seed(args.seed, args.db)
    else:
        result = run_refresh(
            days=args.days,
            limit=args.limit,
            extract=not args.no_extract,
            db_path=args.db,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
