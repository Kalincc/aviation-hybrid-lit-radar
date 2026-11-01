# progress.md — 进度日志

## 当前状态
- 阶段：**M1 完成，M2/M3 进行中**
- 仓库：`E:\aviation-hybrid-lit-radar`（本地 git，不推远端）
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
- 2026-11-01 Lead：创建 venv 并安装依赖（验证 Python 3.14 兼容性）。

## Backlog（P1，禁止现在做）
- URL 查询参数同步、深色模式、CSV 导出、`/` 快捷键聚焦搜索、定时自动刷新（APScheduler）。
