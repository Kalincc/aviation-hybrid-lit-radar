"""配置模块：Settings、关键词组、相关性词表、标签规则、路径常量。

契约参考：技术设计文档.md §3。
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ---------- 路径常量 ----------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "radar.db"
SEED_PATH = DATA_DIR / "seed_papers.json"
ENV_PATH = BASE_DIR / ".env"

APP_VERSION = "1.0.0"

# ---------- 检索关键词组（PRD §5.2）----------
# 组内 OR，跨组独立请求。
KEYWORD_GROUPS: dict[str, list[str]] = {
    "G1": [
        "hybrid-electric aircraft",
        "hybrid electric propulsion",
        "series hybrid aircraft",
        "parallel hybrid aircraft",
        "turboelectric propulsion",
        "distributed electric propulsion",
    ],
    "G2": [
        "energy management strategy aircraft",
        "power split hybrid aircraft",
        "equivalent consumption minimization aircraft",
        "state of charge hybrid aircraft",
        "power allocation hybrid aircraft",
    ],
    "G3": [
        "mode transition aircraft",
        "mode switching propulsion",
        "bumpless transfer",
        "smooth transition hybrid",
        "transient response hybrid propulsion",
    ],
    "G4": [
        "model predictive control hybrid aircraft",
        "dynamic programming energy management aircraft",
        "reinforcement learning energy management aircraft",
        "fuzzy logic energy management aircraft",
    ],
}

# OpenAlex 检索串（TDD §6.1，短语匹配 title+abstract，约 6 条）
OPENALEX_QUERIES: list[str] = [
    '"hybrid electric aircraft"',
    '"hybrid-electric aircraft"',
    '"energy management" aircraft',
    "turboelectric propulsion",
    '"fuel cell" aircraft',
    '"hybrid electric propulsion"',
]

# Semantic Scholar 一次性 bootstrap 检索组（seed 生成用，不进 refresh 常规流程；lead 2026-11-01 批准）
S2_BOOTSTRAP_QUERIES: list[str] = [
    "hybrid electric aircraft energy management",
    "hybrid electric propulsion aircraft",
    "aircraft mode transition hybrid powertrain",
    "turboelectric distributed propulsion aircraft",
]

# ---------- 相关性过滤词（PRD §5.4）----------
AVIATION_TERMS: tuple[str, ...] = (
    "aircraft",
    "aviation",
    "aerospace",
    "aero",
    "evtol",
    "uav",
    "air transport",
    "airborne",
    "propulsion",
    "airline",
    "rotorcraft",
    "helicopter",
    "drone",
    "flight",
    "avionics",
)

# ---------- 标签规则（TDD §3，顺序匹配，最多 3 个）----------
TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "能量管理",
        (
            "energy management",
            "power split",
            "power allocation",
            "state of charge",
            "fuel consumption",
            "energy distribution",
            "能量管理",
            "功率分配",
        ),
    ),
    (
        "模式切换",
        (
            "mode transition",
            "mode switching",
            "bumpless",
            "smooth transition",
            "transient",
            "power smoothing",
            "模式切换",
            "平顺",
        ),
    ),
    (
        "控制算法",
        (
            "model predictive control",
            "mpc",
            "fuzzy logic",
            "sliding mode",
            "pid control",
            "control strategy",
            "controller",
            "控制算法",
            "控制策略",
        ),
    ),
    (
        "电推进架构",
        (
            "hybrid-electric",
            "hybrid electric",
            "electric propulsion",
            "turboelectric",
            "series hybrid",
            "parallel hybrid",
            "distributed propulsion",
            "evtol",
            "electrified powertrain",
            "电推进",
            "混合动力",
        ),
    ),
    (
        "电池储能",
        (
            "battery",
            "energy storage",
            "fuel cell",
            "supercapacitor",
            "lithium",
            "电池",
            "储能",
        ),
    ),
    (
        "优化方法",
        (
            "optimization",
            "optimisation",
            "optimal",
            "dynamic programming",
            "reinforcement learning",
            "genetic algorithm",
            "convex",
            "particle swarm",
            "优化",
        ),
    ),
    (
        "实验仿真",
        (
            "experiment",
            "simulation",
            "simulink",
            "hardware-in-the-loop",
            "test bench",
            "flight test",
            "wind tunnel",
            "实验",
            "仿真",
        ),
    ),
]

TAG_VOCAB = [tag for tag, _ in TAG_RULES]
MAX_TAGS = 3

SOURCE_LABELS = {
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
}


def compute_tags(title: str, methods: list[str] | None = None, abstract: str = "") -> list[str]:
    """按 TDD §3 规则打标：title + methods + abstract 小写匹配，词表顺序取前 3 个。"""
    text = " ".join(
        [
            (title or "").lower(),
            " ".join(methods or []).lower(),
            (abstract or "").lower(),
        ]
    )
    tags: list[str] = []
    for tag, terms in TAG_RULES:
        if any(term in text for term in terms):
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


# ---------- Settings ----------
@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    semantic_scholar_api_key: str = ""
    openalex_mailto: str = ""
    openalex_api_key: str = ""  # 可选；无 key 走免费额度（每日有限）
    port: int = 8000
    default_days: int = 90
    db_path: str = str(DB_PATH)
    data_dir: str = str(DATA_DIR)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger(__name__).warning("环境变量 %s 不是整数：%r，使用默认 %s", name, raw, default)
        return default


def load_settings() -> Settings:
    """读取 .env + 环境变量（环境变量优先）。"""
    load_dotenv(ENV_PATH, override=False)
    return Settings(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=(os.getenv("DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com"),
        deepseek_model=(os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-chat"),
        semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip(),
        openalex_mailto=os.getenv("OPENALEX_MAILTO", "").strip(),
        openalex_api_key=os.getenv("OPENALEX_API_KEY", "").strip(),
        port=_env_int("PORT", 8000),
        default_days=_env_int("DEFAULT_DAYS", 90),
        db_path=os.getenv("DB_PATH", "").strip() or str(DB_PATH),
        data_dir=os.getenv("DATA_DIR", "").strip() or str(DATA_DIR),
    )


def setup_logging(level: str | int | None = None) -> None:
    """日志输出到 stderr（不打印 Key）。重复调用不会叠加 handler。"""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=level or os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
