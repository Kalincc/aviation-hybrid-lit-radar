"""pytest 共享 fixture：临时 DB、禁用 LLM 的 Settings、TestClient。

所有测试零真实网络：抓取函数用假 session / monkeypatch，LLM 用假 client。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config, db  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> config.Settings:
    """测试用 Settings：无 DeepSeek Key（走启发式），DB 在临时目录。"""
    return config.Settings(
        deepseek_api_key="",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat",
        semantic_scholar_api_key="",
        openalex_mailto="",
        openalex_api_key="",
        port=8000,
        default_days=90,
        db_path=str(tmp_path / "radar.db"),
        data_dir=str(tmp_path),
    )


@pytest.fixture()
def db_file(tmp_path: Path) -> str:
    return str(tmp_path / "radar.db")


@pytest.fixture()
def conn(db_file: str):
    db.init_db(db_file)
    connection = db.connect(db_file)
    try:
        yield connection
    finally:
        db.close(connection)


@pytest.fixture()
def client(db_file: str, settings: config.Settings):
    from fastapi.testclient import TestClient

    from src.api import create_app

    app = create_app(db_path=db_file, settings=settings)
    with TestClient(app) as test_client:
        yield test_client
