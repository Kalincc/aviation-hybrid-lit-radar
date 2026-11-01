# AGENTS.md — Aviation Hybrid Lit Radar

> 本文件是仓库内的协作契约。任何人（人或 AI Agent）改动前先读本文件。
> 项目目标：为「航空混合动力系统 · 能量管理 · 模式切换平顺性」方向搭建一个
> 真实文献自动追踪与结构化提取的可视化看板（MVP，课程作业二）。

## 1. 技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.14 + FastAPI + SQLite（stdlib `sqlite3`，无 ORM） | `app.py` 为入口 |
| LLM | DeepSeek，OpenAI 兼容 SDK（`openai` 包） | 无 Key 自动降级为启发式 |
| 数据源 | arXiv API、OpenAlex API（均免 Key）；Semantic Scholar 可选 | 见 `src/sources.py` |
| 前端 | 原生 HTML / CSS / JavaScript，无构建工具、无 CDN、离线可用 | `static/` |
| 测试 | pytest + httpx（FastAPI TestClient） | `tests/` |

禁止擅自新增第三方依赖；如确需，先向 Lead 说明理由并同步更新 `requirements.txt`。

## 2. 目录与所有权

| 路径 | 所有者 | 说明 |
| --- | --- | --- |
| `src/*.py`、`app.py`、`tests/` | backend-dev | 后端、抓取、提取、测试 |
| `data/seed_papers.json` | backend-dev | 真实抓取 + 提取的演示种子数据（禁止编造） |
| `static/index.html`、`static/css/`、`static/js/` | frontend-dev | 看板全部前端资产 |
| `docs/`、`README.md`、`AGENTS.md`、`研究说明.md`、`技术设计文档.md`、`progress.md`、`design-system/`、`.env*`、`requirements.txt` | lead | 文档、设计、契约、验收 |

跨所有权改动必须先告知对应负责人（Lead 协调）。不要删除别人未完成的工作。

## 3. 常用命令

```bash
# 建议在 E:\aviation-hybrid-lit-radar 下使用项目虚拟环境
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 启动看板（默认 http://127.0.0.1:8000）
.venv/Scripts/python.exe app.py

# 跑测试
.venv/Scripts/python.exe -m pytest -q

# 命令行抓取 + 提取（可选）
.venv/Scripts/python.exe -m src.pipeline --days 90 --limit 40

# 用种子数据启动（无网络时演示）
.venv/Scripts/python.exe -m src.pipeline --load-seed
```

## 4. 编码规则（ponytail：最小完整改动）

- 用能完整解决问题的最小改动；不提前抽象、不引入用不到的层。
- YAGNI：MVP 之外的需求先记入 `progress.md` 的 backlog，不实现。
- 每个非平凡 bug 先写一个会失败的测试，再修复。
- 改文件前先读；不要大段重写别人的文件。
- 中文 UI 文案；代码注释用中文或英文皆可，但同一文件保持一致。
- 交付前必须：`pytest` 全绿 + 手动打开页面点一遍（见 `docs/UI-SPEC.md` 验收清单）。

## 5. 数据真实性铁律

- 所有论文条目必须来自 arXiv / OpenAlex / Semantic Scholar **真实 API 响应**，禁止编造标题、作者、日期、链接。
- LLM 提取的每条结论必须带 `evidence`（摘要原文引用）；无法从摘要确定的字段一律 `unknown` / 空数组。
- 前端不得展示「假数据」；没有 Key 或 LLM 失败时使用启发式提取，并在 UI 明确标注「启发式」。
- 种子数据 `data/seed_papers.json` 同样必须是真实抓取结果（可只保留 40~60 篇）。

## 6. 接口契约

`技术设计文档.md` 第 5 节的 REST API 定义是唯一契约。
前端按契约调用，后端按契约返回。任何字段增删改，须 Lead 同意并同文档一起更新。

## 7. 沟通与进度

- 完成一块工作 / 遇到阻塞：用 `send_message` 向 lead 汇报（一句话结论 + 证据路径）。
- 每个重要节点在 `progress.md` 追加一行（时间、负责人、事件）。
- 只建本地 git 仓库，不 push 到远端（用户要求）。
