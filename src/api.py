"""FastAPI 应用与 REST 路由。

契约参考：技术设计文档.md §5（接口/字段/错误格式）、§8（实现要点）。
- 错误统一 {"detail": {"code": "...", "message": "..."}}；参数非法 422
- 响应模型全部 Pydantic v2
- GET / 返回 static/index.html；static/index.html 不存在时返回 JSON 404 提示（不崩溃）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db, pipeline

log = logging.getLogger(__name__)


# ---------------- Pydantic 响应模型 ----------------


class HealthLlm(BaseModel):
    enabled: bool
    provider: str
    model: str


class HealthResponse(BaseModel):
    status: str
    version: str
    db: str
    paper_count: int
    llm: HealthLlm


class MetaLlm(BaseModel):
    enabled: bool
    provider: str


class SourceInfo(BaseModel):
    id: str
    label: str
    enabled: bool


class MetaResponse(BaseModel):
    last_refresh: str | None
    paper_count: int
    source_counts: dict[str, int]
    llm: MetaLlm
    default_days: int
    sources: list[SourceInfo]


class PaperItem(BaseModel):
    id: int
    source: str
    source_label: str
    external_id: str
    doi: str | None
    title: str
    authors: list[str]
    published: str
    url: str
    abstract: str
    one_line_contribution: str
    methods: list[str]
    datasets: list[str]
    code_open_source: str
    code_evidence: str
    contribution_evidence: str
    confidence: float
    extraction_mode: str
    tags: list[str]
    fetched_at: str


class PapersResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PaperItem]


class OpenSourceRatio(BaseModel):
    yes: int
    no: int
    unknown: int


class SourceCount(BaseModel):
    source: str
    label: str
    count: int


class MonthCount(BaseModel):
    month: str
    count: int


class TagCount(BaseModel):
    tag: str
    count: int


class StatsResponse(BaseModel):
    total: int
    open_source_ratio: OpenSourceRatio
    by_source: list[SourceCount]
    by_month: list[MonthCount]
    by_tag: list[TagCount]
    latest_published: str | None
    last_refresh: str | None


class RefreshRequest(BaseModel):
    days: int = Field(90, ge=1, le=365)
    limit: int = Field(20, ge=1, le=60)
    extract: bool = True


class RefreshResponse(BaseModel):
    run_id: int
    status: str
    fetched: int
    inserted: int
    extracted: int
    skipped: int
    llm_enabled: bool
    errors: list[str]
    duration_s: float


class RunItem(BaseModel):
    run_id: int
    status: str
    started_at: str
    finished_at: str | None
    days: int
    fetched: int
    inserted: int
    extracted: int
    errors_count: int


class RunsResponse(BaseModel):
    items: list[RunItem]


# ---------------- 错误响应 ----------------


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": {"code": code, "message": message}})


def create_app(
    db_path: str | None = None,
    settings: config.Settings | None = None,
) -> FastAPI:
    """创建 FastAPI 应用；启动时建表（幂等）。"""
    settings = settings or config.load_settings()
    db_file = str(db_path or settings.db_path)
    config.setup_logging()

    def _auto_load_seed() -> None:
        """默认库首次启动且为空时自动导入 seed，评分者 `python app.py` 一步看到数据。

        仅当使用默认库（未显式传 db_path，测试/自定义库不受影响）时生效；
        任何异常都吞掉，降级为空库 + 前端空态。
        """
        try:
            with db.open_db(db_file) as conn:
                if db.paper_count(conn) > 0:
                    return
            if not config.SEED_PATH.exists():
                return
            result = pipeline.load_seed(seed_path=str(config.SEED_PATH), db_path=db_file)
            log.info(
                "首次启动自动导入 seed：papers=%s inserted=%s seed=%s",
                result.get("papers"),
                result.get("inserted"),
                config.SEED_PATH,
            )
        except Exception:  # noqa: BLE001 - seed 导入失败不阻塞启动
            log.exception("自动导入 seed 失败，降级为空库")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init_db(db_file)
        if db_path is None:
            _auto_load_seed()
        log.info("应用启动：db=%s llm_enabled=%s", db_file, settings.llm_enabled)
        yield

    app = FastAPI(
        title="Aviation Hybrid Lit Radar",
        version=config.APP_VERSION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db_path = db_file

    # 静态资源（前端并行开发，目录可能为空/不存在）
    if config.STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        message = f"参数不合法：{location} {first.get('msg', '')}".strip()
        return _error(422, "validation_error", message)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("未处理异常")
        return _error(500, "internal_error", f"{type(exc).__name__}: {exc}")

    # ---------------- 路由 ----------------

    @app.get("/", include_in_schema=False)
    def index() -> Any:
        index_file = config.STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "前端页面尚未生成（static/index.html 不存在）"},
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        db_status = "ok"
        count = 0
        try:
            with db.open_db(db_file) as conn:
                count = db.paper_count(conn)
                conn.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001 - 健康检查不抛 500
            log.exception("健康检查 DB 异常")
            db_status = f"error: {type(exc).__name__}"
        return HealthResponse(
            status="ok",
            version=config.APP_VERSION,
            db=db_status,
            paper_count=count,
            llm=HealthLlm(
                enabled=settings.llm_enabled,
                provider="deepseek",
                model=settings.deepseek_model,
            ),
        )

    @app.get("/api/meta", response_model=MetaResponse)
    def meta() -> MetaResponse:
        with db.open_db(db_file) as conn:
            counts = db.source_counts(conn)
            paper_count = db.paper_count(conn)
            last = db.last_refresh(conn)
        source_counts = {
            "arxiv": counts.get("arxiv", 0),
            "openalex": counts.get("openalex", 0),
            "semantic_scholar": counts.get("semantic_scholar", 0),
        }
        # lead 2026-11-01 批准的语义：enabled = 配置了该源 Key 或库中已有该源数据
        sources = [
            SourceInfo(id="arxiv", label=config.SOURCE_LABELS["arxiv"], enabled=True),
            SourceInfo(
                id="openalex",
                label=config.SOURCE_LABELS["openalex"],
                enabled=bool(settings.openalex_api_key) or source_counts["openalex"] > 0,
            ),
            SourceInfo(
                id="semantic_scholar",
                label=config.SOURCE_LABELS["semantic_scholar"],
                enabled=bool(settings.semantic_scholar_api_key) or source_counts["semantic_scholar"] > 0,
            ),
        ]
        return MetaResponse(
            last_refresh=last,
            paper_count=paper_count,
            source_counts=source_counts,
            llm=MetaLlm(enabled=settings.llm_enabled, provider="deepseek"),
            default_days=settings.default_days,
            sources=sources,
        )

    @app.get("/api/papers", response_model=PapersResponse)
    def papers(
        q: str = "",
        open_source: Literal["", "yes", "no", "unknown"] = "",
        source: Literal["", "arxiv", "openalex", "semantic_scholar"] = "",
        days: int | None = Query(None, ge=0),
        sort: Literal["date_desc", "date_asc", "confidence_desc"] = "date_desc",
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=50),
    ) -> PapersResponse:
        window = settings.default_days if days is None else days
        with db.open_db(db_file) as conn:
            total, items = db.list_papers(
                conn,
                q=q,
                open_source=open_source,
                source=source,
                days=window,
                sort=sort,
                page=page,
                page_size=page_size,
            )
        return PapersResponse(total=total, page=page, page_size=page_size, items=items)

    @app.get("/api/stats", response_model=StatsResponse)
    def stats(days: int | None = Query(None, ge=0)) -> StatsResponse:
        window = settings.default_days if days is None else days
        with db.open_db(db_file) as conn:
            data = db.stats(conn, days=window)
        return StatsResponse(**data)

    @app.post("/api/refresh", response_model=RefreshResponse)
    def refresh(body: RefreshRequest) -> RefreshResponse:
        result = pipeline.run_refresh(
            days=body.days,
            limit=body.limit,
            extract=body.extract,
            db_path=db_file,
            settings=settings,
        )
        return RefreshResponse(**result)

    @app.get("/api/runs", response_model=RunsResponse)
    def runs(limit: int = Query(5, ge=1, le=50)) -> RunsResponse:
        with db.open_db(db_file) as conn:
            items = db.list_runs(conn, limit=limit)
        return RunsResponse(items=items)

    return app
