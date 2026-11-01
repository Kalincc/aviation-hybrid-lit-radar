# progress.md — 进度日志

## 当前状态
- 阶段：**全部里程碑完成（M1–M5），已交付并提交**
- 仓库：`E:\aviation-hybrid-lit-radar`（本地 git，不推远端）
- 作业一：已交付至 `E:\deepseek_harness_workplace\ai_homework\ass1`（docx+pdf 3 页，已验收）
- 启动：`.venv/Scripts/python.exe app.py` → http://127.0.0.1:8000

## 角色
| 角色 | 负责 |
| --- | --- |
| Lead | 需求、PRD/TDD/UI-SPEC、设计系统、集成验收、文档 |
| backend-dev | 抓取 / LLM 提取 / SQLite / FastAPI / pytest / 种子数据 |
| frontend-dev | `static/` 看板页面、交互、SVG 图表、视觉验收 |
| data-analyst（外部） | 作业一（NGSIM 数据分析报告），与本仓库无关 |

## 里程碑
| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| M1 | 仓库骨架、AGENTS、PRD、TDD、UI-SPEC、设计系统（ui-ux-pro-max） | ✅ 2026-11-01 |
| M2 | 后端实现 + 单测 + 真实种子数据 | 🔄 进行中 |
| M3 | 前端看板实现 | 🔄 进行中 |
| M4 | 集成联调、真实数据演示、pytest、验收 | ⬜ 未开始 |

## 日志
- 2026-11-01 Lead：完成仓库骨架；ui-ux-pro-max 生成设计系统（Swiss Modernism 2.0 / navy #1E3A5F / Dense Dashboard）并持久化到 `design-system/`；写入 `研究说明.md`、`技术设计文档.md`、`docs/UI-SPEC.md`、`AGENTS.md`、`.env.example`。
- 2026-11-01 Lead：创建 venv 并安装依赖，验证 Python 3.14 兼容（fastapi 0.162.0 / pydantic 2.14.2 / openai 3.42.0）；ui-ux-pro-max 设计系统生成完毕。
- 2026-11-01 backend-dev：开始实现 `src/config.py`、`src/sources.py`（进行中）。
- 2026-11-01 frontend-dev：开始实现 `static/index.html`、`static/css/styles.css`、`static/js/app.js`（进行中）。
- 2026-11-01 Lead：用户提供 DeepSeek API Key，已写入 `.env`（gitignore 保护），真实调用 `deepseek-chat` 验证可用（返回正常、用量 9+1 tokens）。
- 2026-11-01 Lead：前端 Phase A/B 完成并真实联调（46 篇默认 90 天视图 / 48 篇全部；四断点无横向滚动、0 console 错误、0 外部请求；已交付 docs/screenshots 真实截图）。frontend-dev 任务完成。
- 2026-11-01 Lead：交付前重置演示 DB（旧 run 记录 48/0/0 不自然）→ 由 Lead 托管的服务首次启动自动导入 seed，run 记录为 success `抓取 48 / 入库 48 / 提取 48`，last_refresh 2026-11-01 14:16；同步重拍真实截图。
- 2026-11-01 Lead：最终验收——`pytest` 48 passed / 1 skipped；四个断点真实截图重拍（1440/1024/768/375 全页 + 搜索态）；README §9、AGENTS.md 数据源说明收口；`task-1 / task-2 / task-3` 全部 completed。
- 2026-11-01 Lead：OpenAlex 无 Key 免费额度今日耗尽（429，UTC 0 点重置）。决策：seed 用 Semantic Scholar bootstrap（真实 API、429 退避）抓取 ≥30 篇；`meta.sources.enabled` 语义微调为「已配 Key 或库中已有数据」，同步更新 TDD §5.2/§6、PRD §5.3、`.env.example`（新增可选 `OPENALEX_API_KEY`）。
- 2026-11-01 作业一（独立交付）：data-analyst 完成 NGSIM 数据分析报告 `数据分析报告.docx` + `.pdf`（3 页 A4）、4 张 300dpi 复合图、清洗数据与可复现脚本；Lead 已完成 PDF 逐页视觉验收、关键数字复核与文档元数据修正。

## Backlog（P1，禁止现在做）
- URL 查询参数同步、深色模式、CSV 导出、`/` 快捷键聚焦搜索、定时自动刷新（APScheduler）。
