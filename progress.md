# progress.md — 进度日志

## 当前状态（2026-11-01 15:30）
- 阶段：**全部里程碑完成（M1–M5），已交付**（本地 git 提交）
- 仓库：`E:\aviation-hybrid-lit-radar`（本地 git，不推远端）
- 数据：**143 篇真实论文**（OpenAlex 95 + Semantic Scholar 46 + arXiv 2；默认 90 天视图 103 篇），seed 可复现
- 测试：`pytest` **48 passed / 1 skipped**
- 启动：`.venv/Scripts/python.exe app.py` → http://127.0.0.1:8000
- 作业一：已交付至 `E:\deepseek_harness_workplace\ai_homework\ass1`（docx+pdf 3 页，已验收；**排版升级版已生成，待用户确认后替换 PDF**）

## 角色
| 角色 | 负责 |
| --- | --- |
| Lead | 需求、PRD/TDD/UI-SPEC、设计系统、集成验收、文档、最终汇报 |
| backend-dev | 抓取 / LLM 提取 / SQLite / FastAPI / pytest / 种子数据 |
| frontend-dev | `static/` 看板页面、交互、SVG 图表、视觉验收 |
| data-analyst（外部） | 作业一（NGSIM 数据分析报告），与本仓库无关 |

## 里程碑
| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| M1 | 仓库骨架、AGENTS、PRD、TDD、UI-SPEC、设计系统（ui-ux-pro-max） | ✅ 2026-11-01 |
| M2 | 后端实现 + 单测 + 真实种子数据（48→143 篇） | ✅ 2026-11-01 |
| M3 | 前端看板实现 + 四断点/无障碍/XSS 验收 | ✅ 2026-11-01 |
| M4 | 集成联调、真实刷新（OpenAlex+DeepSeek）、pytest、真实数据演示 | ✅ 2026-11-01 |
| M5 | 文档收口、README、真实截图、本地 git 提交 | ✅ 2026-11-01 |

## 日志
- 2026-11-01 Lead：完成仓库骨架；ui-ux-pro-max 生成设计系统（Swiss Modernism 2.0 / navy #1E3A5F / Dense Dashboard）并持久化到 `design-system/`；写入 `研究说明.md`、`技术设计文档.md`、`docs/UI-SPEC.md`、`AGENTS.md`、`.env.example`。
- 2026-11-01 Lead：创建 venv 并安装依赖，验证 Python 3.14 兼容（fastapi 0.162.0 / pydantic 2.14.2 / openai 3.42.0）；生成 UI-SPEC。
- 2026-11-01 backend-dev：实现 `src/config.py`、`src/sources.py`、`src/db.py`、`src/extractor.py`、`src/pipeline.py`、`src/api.py`、`app.py`、`tests/`（48 用例）。
- 2026-11-01 frontend-dev：实现 `static/index.html` + `css/styles.css` + `js/app.js` + `favicon.svg`；四断点、对比度、键盘、XSS 注入、reduced-motion 自检通过。
- 2026-11-01 Lead：用户提供 DeepSeek API Key，已写入 `.env`（gitignore 保护），真实调用 `deepseek-chat` 验证可用。
- 2026-11-01 Lead：OpenAlex 无 Key 免费额度（出口 IP 共享 $0.1/天）耗尽（429，UTC 0 点重置）。决策：seed 用 Semantic Scholar bootstrap（真实 API、429 退避）抓取 46 篇 + arXiv 2 篇；`meta.sources.enabled` 语义微调为「已配 Key 或库中已有数据」，同步更新 TDD §5.2/§6、PRD §5.3、`.env.example`（新增可选 `OPENALEX_API_KEY`）。
- 2026-11-01 Lead：交付前重置演示 DB → 首次启动自动导入 seed（run 记录 `抓取 48 / 入库 48 / 提取 48`），last_refresh 14:16；重拍真实截图。
- 2026-11-01 Lead：**用户提供免费 OpenAlex API Key** 并写入 `.env`；真实 `POST /api/refresh`（days=180, limit=60, extract=true）成功：run#2 `抓取 97 / 入库 95 / 提取 95 / 0 错误 / 42.9 s`；库 **143 篇**（OpenAlex 95 + S2 46 + arXiv 2，默认 90 天视图 103 篇）；seed 重新导出 143 篇（LLM 106 / 启发式 37）。
- 2026-11-01 Lead：前端用真实刷新数据重拍 7 张截图（dashboard 1440/1024/768/375、搜索态、refresh-loading、refresh-toast），旧 mock 截图删除；四断点无横向滚动复测通过。
- 2026-11-01 Lead：README 全面更新（数据源/限额/seed 溯源/143 篇/真实刷新记录）；pytest 最终 **48 passed / 1 skipped**；本地 git 提交。
- 2026-11-01 作业一（独立交付）：data-analyst 完成 NGSIM 数据分析报告 docx+pdf（3 页 A4）、4 张 300dpi 复合图、清洗数据与可复现脚本；Lead 完成视觉验收与数字复核。
- 2026-11-01 Lead：作业一报告用 `nature-paper2word`（md-to-word 3.2.0）重排版：3 页 A4、三线表、图题在下/表题在上、无表格跨页；Word 预览版交付用户确认，确认后替换正式 docx/PDF 与桌面副本。

## Backlog（P1，后续可选）
- URL 查询参数同步、深色模式、CSV 导出、`/` 快捷键聚焦搜索、定时自动刷新（APScheduler）、配置 `SEMANTIC_SCHOLAR_API_KEY` 后 refresh 也可抓 S2。
