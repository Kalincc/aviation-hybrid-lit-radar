# UI-SPEC.md — 看板视觉与交互落地规范
配套：`design-system/aviation-hybrid-lit-radar/MASTER.md`（ui-ux-pro-max 生成）＋ `技术设计文档.md` §9。
本文件是前端实现的唯一视觉/交互依据；与 MASTER 冲突时以本文件为准（更具体）。

## 1. 设计系统摘要（来自 ui-ux-pro-max）

| 项 | 选择 |
| --- | --- |
| Pattern | Portfolio Grid（卡片网格 + 分类筛选 + 快速加载） |
| Style | **Swiss Modernism 2.0**（网格系统、理性、克制的学术感） |
| Variance / Motion / Density | 4 / 3 / **8（Dense Dashboard）** |
| Typography | 标题衬线（学术感）：EB Garamond / Crimson Text；正文无衬线 |
| Avoid | 低层级混乱、无筛选、视觉杂乱 |

**离线约束**：不加载 Google Fonts/CDN。标题栈：`Georgia, "Times New Roman", "Noto Serif SC", "Songti SC", SimSun, serif`；正文栈：`Inter, system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif`；数字：`"SF Mono", Consolas, monospace` 用于统计值。

## 2. Design Tokens（`:root` CSS 变量，必须原样使用）

```css
:root {
  /* color */
  --color-primary: #1E3A5F;
  --color-on-primary: #FFFFFF;
  --color-secondary: #2563EB;
  --color-accent: #A16207;
  --color-background: #F8FAFC;
  --color-foreground: #0F172A;
  --color-card: #FFFFFF;
  --color-card-foreground: #0F172A;
  --color-muted: #E9EEF5;
  --color-muted-foreground: #475569;
  --color-border: #CBD5E1;
  --color-destructive: #DC2626;
  --color-success: #166534;
  --color-success-bg: #DCFCE7;
  --color-danger: #991B1B;
  --color-danger-bg: #FEE2E2;
  --color-info-bg: #DBEAFE;
  --color-ring: #1E3A5F;

  /* type */
  --font-display: Georgia, "Times New Roman", "Noto Serif SC", "Songti SC", SimSun, serif;
  --font-sans: Inter, system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  --font-mono: "SF Mono", Consolas, "Courier New", monospace;
  --text-xs: 12px; --text-sm: 13px; --text-base: 14px;
  --text-md: 16px; --text-lg: 20px; --text-xl: 28px; --text-2xl: 36px;

  /* space (4px base, dense) */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-7: 48px;

  /* radius & shadow */
  --radius-sm: 6px; --radius-md: 10px; --radius-lg: 14px; --radius-pill: 999px;
  --shadow-card: 0 1px 2px rgba(15, 23, 42, .06), 0 1px 3px rgba(15, 23, 42, .10);
  --shadow-hover: 0 4px 12px rgba(15, 23, 42, .10), 0 2px 4px rgba(15, 23, 42, .06);

  /* motion */
  --dur-fast: 150ms; --dur-base: 200ms; --dur-slow: 300ms;
  --ease: cubic-bezier(.2, .6, .3, 1);
}
```

深色模式为 P1，不实现。

## 3. 布局（1440 桌面基准）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ◈ Aviation Hybrid Lit Radar     航空混动 · 能量管理 · 模式切换               │
│   最后更新 2026-11-01 13:20            [7天|30天|90天|180天|全部] [⟳ 刷新数据] │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌文献总数 42┐ ┌开源占比 24%┐ ┌近30天新增 12┐ ┌最近发表 10-26┐                │
├─────────────────────────────────────────────────────────────┬───────────────┤
│ [🔍 搜索标题、摘要或一句话贡献…]  开源[全部·开源·闭源·未知]  │ 月度趋势 ▁▃▅▂ │
│ 排序[最新优先▾]   共 42 篇 · 时间窗口 90 天                 │ 标签分布 ▇▅▃  │
│ ┌─────────────────────────────────────────────────────┐    │ 开源状态 ◔   │
│ │ [arXiv] 2026-10-26            [✓ 开源]               │    │ 抓取记录      │
│ │ 论文标题（链接 ↗）                                    │    │              │
│ │ 作者 A, B, C …                                       │    │              │
│ │ 一句话贡献：提出……，油耗降低 12%                      │    │              │
│ │ [MPC] [test bench]  [证据摘录 ▾] 置信度 86% · LLM     │    │              │
│ └─────────────────────────────────────────────────────┘    │              │
│ （重复 12 张卡片）                                           │              │
├─────────────────────────────────────────────────────────────┴───────────────┤
│ 数据来源：arXiv · OpenAlex · Semantic Scholar（可选）  仅供科研参考，以原文为准 │
└─────────────────────────────────────────────────────────────────────────────┘
```

- 最大宽度 `1360px`，页面左右 padding `24px`；主网格 `grid-template-columns: minmax(0, 1fr) 380px; gap: 24px`；
- 顶栏 `position: sticky; top: 0; z-index: 20`，背景 `--color-card`，下边框 1px `--color-border`；
- 统计卡：`grid-template-columns: repeat(4, 1fr); gap: 12px`。

## 4. 组件规范

### 4.1 顶栏
- 左：logo（内联 SVG 20×20，primary 底、白色雷达/机翼图形，圆角 6px）+ 主标题（`--font-display` 20px/600）+ 副标题（13px muted）。
- 右：`最后更新 HH:mm`（12px muted，前置时钟图标）；时间窗口为**分段控件**（button 组，选中态 primary 底白字，未选中 card 底边框，`aria-pressed`）；刷新按钮 primary，图标+文字，height 40px。

### 4.2 统计卡
- 白底、1px border、radius-md、padding 16px；label 12px muted；value `--text-xl` serif 600 `font-variant-numeric: tabular-nums`；subtext 12px muted（如「较上窗口 +3」可不做）。
- 数字加载中显示 skeleton 条。

### 4.3 搜索与筛选
- 搜索框高 40px，左内嵌放大镜 SVG 16px，placeholder 见文案表；输入防抖 300ms；`type="search"`。
- 筛选分组：小标签（12px muted）+ 分段 chip；chip 高 32px、padding 0 12px、radius-pill；选中 primary 底白字，hover `--color-muted`；键盘可聚焦。
- 排序：原生 `<select>`（样式化，高 40px）。
- 结果计数行：13px muted，`aria-live="polite"`；示例「共 42 篇 · 时间窗口 90 天 · 关键词 “energy”」。

### 4.4 文献卡片（核心）
```
[来源徽标] 2026-10-26        [开源徽标]
标题（16px/600，链接，hover 下划线，外链图标 14px）
作者：A, B, C 等 3 人（13px muted，超 2 行截断）
一句话贡献（14px，color foreground，2~3 行，前面加 4px primary 竖线）
[方法1] [方法2] [数据集：xxx]（chips：12px，muted 底）
▸ 证据摘录（details/summary，展开显示英文原句 blockquote，13px，左边框 2px secondary）
底栏：置信度 86%（细进度条 60px） · LLM提取/启发式 · 查看原文 ↗
```
- 卡片白底、radius-md、padding 16px、border、`transition: box-shadow/border-color 200ms`；hover 升 `--shadow-hover`，`cursor: pointer`（标题可点）。
- 开源徽标：`✓ 开源`（success 配色）/`✕ 闭源`（danger 配色）/`? 未知`（muted 配色）。
- 来源徽标：arXiv（红字 `#B91C1C`/`#FEE2E2`）、OpenAlex（蓝字 `#1D4ED8`/`--color-info-bg`）、Semantic Scholar（紫字 `#6D28D9`/`#EDE9FE`）。
- 模式徽标：`LLM`（secondary 底白字）/`启发式`（accent 文字 + `#FEF3C7` 底）。
- 置信度条：轨道 `--color-muted`，填充按值渐变（<50% accent，≥50% secondary）；`title` 提示。
- 启发式条目的「一句话贡献」若为摘要截断，卡片标注「摘要直摘」。

### 4.5 图表卡（手写 SVG）
- 卡结构：标题 14px/600 + 副标题 12px muted；SVG 自适应宽度，高 160~180px。
- 月度趋势：柱状，x=月（如 05、06…），y 隐藏网格仅 0 线，柱色 primary，hover 显示 `<title>`「2026-05 · 3 篇」；空数据 → 「暂无数据」。
- 标签分布：横向条形 top7，标签 12px，条色 secondary，数值右对齐。
- 开源状态：环形（donut）三段 yes/no/unknown（success/danger/muted），中心显示总数；下方 12px 图例。
- 抓取记录：最近 3 条，状态点（success 绿/partial 琥珀/error 红）+ 时间 + 「抓取 38 · 入库 12 · 提取 12」。
- 每张图 `role="img"` + `aria-label` 概述；颜色不唯一依赖（配文字图例）。

### 4.6 状态与反馈
- **加载骨架**：3 张卡片骨架 + 统计卡数字骨架，shimmer 动画；`prefers-reduced-motion` 时静态灰块。
- **空库**：内联 SVG 插画 + 「还没有入库文献」+ 说明「点击右上角「刷新数据」，抓取最近 90 天的航空混动文献」+ 主按钮「立即抓取」。
- **无结果**：放大镜插画 + 「没有符合条件的文献」+ 次按钮「清空筛选」。
- **错误横幅**：页面顶部卡片下方，红色左边框 3px、浅红底，文案 + 「重试」按钮；`role="alert"`。
- **Toast**：底部居中，深色底白字，3s 自动消失；「已更新：新增 12 篇，提取 12 篇」。
- **刷新进行中**：按钮文案「抓取中…」，禁用，页面顶部显示细进度条（不确定进度，indeterminate）。

## 5. 文案表（中文，必须一致）

| 位置 | 文案 |
| --- | --- |
| 页面标题 `<title>` | Aviation Hybrid Lit Radar · 航空混动文献雷达 |
| 主标题 / 副标题 | Aviation Hybrid Lit Radar / 航空混动 · 能量管理 · 模式切换平顺性 |
| 搜索占位 | 搜索标题、摘要或一句话贡献… |
| 筛选标签 | 开源状态 / 来源 / 排序 |
| 排序选项 | 最新优先 / 最早优先 / 置信度优先 |
| 刷新按钮 | 刷新数据 → 抓取中… |
| 统计卡 | 文献总数 / 开源占比 / 近30天新增 / 最近发表 |
| 结果计数 | 共 {n} 篇 · 时间窗口 {days} 天 |
| 空库 | 还没有入库文献；点击「刷新数据」抓取最近 90 天的航空混动文献 |
| 无结果 | 没有符合条件的文献；试试清空筛选或更换关键词 |
| 错误 | 数据加载失败：{message}；检查后端服务是否已启动（python app.py） |
| 页脚 | 数据来源：arXiv · OpenAlex · Semantic Scholar（可选）。提取结果由大模型辅助生成，仅供科研参考，请以原文为准。 |
| 无 Key 提示 | 当前为启发式提取模式（未配置 DeepSeek API Key 或调用失败），结论可能不精确。 |
| 证据空态 | 摘要未提及代码开源信息 / 该条目无可用摘要 |

## 6. 响应式

| 断点 | 变化 |
| --- | --- |
| ≥1280 | 主网格 1fr + 380px；统计卡 4 列 |
| 1024–1279 | 主网格 1fr + 340px；统计卡 4 列；字号不变 |
| 768–1023 | 单列：列表在上、图表 2 列在下；顶栏允许两行；统计卡 2×2 |
| 375–767 | 单列全部；工具条纵向堆叠；统计卡 2×2；字号 -1px；卡片 padding 12px |

任何断点**不得出现横向滚动条**。

## 7. 无障碍

- 所有可点击元素 `<button>`/`<a>`，`cursor:pointer`；最小点击区 32×32（移动端 44×44）；
- 键盘可达：搜索、chip、刷新、卡片标题、证据 summary 均可用 Tab 聚焦；`:focus-visible` 外圈 `2px solid var(--color-ring)` + 2px offset；
- 文本对比度 ≥4.5:1（正文 `#0F172A` on `#F8FAFC` ≈ 16:1；muted `#475569` ≈ 7:1）；
- 图标一律内联 SVG（Lucide 风格线性图标：search / refresh / external-link / chevron-down / clock / copy），**禁止用 emoji 当图标**；
- 动态区域用 `aria-live="polite"`（结果计数、刷新完成、错误用 `role="alert"`）；
- 表单控件有可见 label 或 `aria-label`；
- 尊重 `prefers-reduced-motion: reduce`：关闭 shimmer、hover 位移与过渡动画。

## 8. 动效

- hover：卡片阴影/边框 200ms；按钮 150ms；chip 150ms；
- 列表渲染：可选 120ms 淡入（stagger 20ms），reduced-motion 关闭；
- 不使用 GSAP 等外部库（MASTER 的 ScrollTrigger 方案不引入；本页为数据密集型看板，滚动动效无收益）。

## 9. 验收清单（前端自检）

- [ ] 1440/1024/768/375 四个宽度截图无横向滚动、无重叠；
- [ ] 首屏 skeleton → 数据渲染 <2s（本地）；
- [ ] 搜索 300ms 防抖、筛选组合正确、清空筛选可用；
- [ ] 刷新按钮 loading/禁用/完成 toast 全链路；
- [ ] 空库/无结果/错误三种状态可人工触发验证；
- [ ] 无 Key 提示条可见且不遮挡内容；
- [ ] 键盘 Tab 走查一遍所有交互；focus 可见；
- [ ] 页面无 emoji 图标、无 CDN 请求（DevTools Network 检查）；
- [ ] DevTools 控制台无报错；
- [ ] 输出 `docs/` 外的前端文件仅 `static/` 下 3 个文件（+ 可选 favicon）。
