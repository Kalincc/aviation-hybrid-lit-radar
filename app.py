"""应用入口：`python app.py` 启动（127.0.0.1:8000）。

契约参考：技术设计文档.md §2、§8。
"""

from __future__ import annotations

import uvicorn

from src import config
from src.api import create_app

app = create_app()


if __name__ == "__main__":
    settings = config.load_settings()
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="info")
