# Artificial Analysis 效率散点图接入设计

## 目标

把 Artificial Analysis（AA）的三张「能力 vs 代价」散点图接入 `model_dashboard`：

| 编号 | 视图 | 数据源 | X 轴 | Y 轴 |
| --- | --- | --- | --- | --- |
| A | Coding Agent Index vs Cost per Task | `/agents/coding-agents` | `mean.costUsd`（USD/任务） | `indexScore × 100` |
| B | Intelligence Index vs Cost per Task | `/models`（默认 tab） | `intelligenceIndexCostPerTask.cost.total`（USD/任务） | `intelligenceIndex` |
| C | Intelligence Index vs Time per Task | `/models` | `intelligenceIndexTimePerTask`（秒/任务） | `intelligenceIndex` |

只读取 AA 已公开的页面数据，不引入新的第三方依赖；所有字段沿用现有抓取链路（HTML → Next flight payload → manifest）。

## 现状与差距

- Agent 归一化器 `normalize_artificial_analysis_html` 已把 `mean.costUsd`、`mean.agentWallTimeSec` 写入 `source.cost_usd_per_task` / `source.wall_time_seconds_per_task`，视图 A 的数据已具备。
- 模型归一化器 `normalize_artificial_analysis_models_html` 目前只落了：模型级 `intelligenceIndex`、`timescaleData.medianOutputSpeed`、`terminalBench40`，以及 variant 级的 `price1mInputTokens/price1mOutputTokens`、`intelligenceIndexCostPerTask.cost.total`。**缺** blended 价格、模型级单任务成本、模型级单任务耗时，因此视图 B/C 无法绘制。
- 前端尚无图表能力（页面内没有 SVG/canvas），需要自绘散点图。

## 方案

### 1. 数据解析（`model_dashboard/sources.py`）

`normalize_artificial_analysis_models_html` 在模型级 `source` 增加：

- `price_1m_blended`：`price1mBlended0To3To1`（AA 默认 3:1 输入/输出混合价，USD / 1M tokens）
- `price_1m_input` / `price_1m_output`：模型级标价
- `intelligence_cost_per_task`：`intelligenceIndexCostPerTask.cost.total`
- `intelligence_time_per_task`：`intelligenceIndexTimePerTask`（秒）

variant 级同步增加 `price_1m_blended`、`intelligence_cost_per_task`、`intelligence_time_per_task`，保留既有 `cost_usd_per_task` 以兼容快照对比。

字段放在 `source` 而非 `scores`：成本/耗时是「越低越好」的代价指标，进入 `scores` 会被 `calculate_scores` 与三方聚合分误用。

### 2. 散点数据构建（新增 `model_dashboard/efficiency.py`）

- `slugify(value)`：小写、非字母数字折叠为 `-`，用于生成与 AA URL 参数一致的可读键。
- `efficiency_key(row)`：
  - Agent：`slugify(f"{tool}-{model}")`，例如 `claude-code-fable-5-1-max-with-fallback`；
  - Model：`source.slug`，与 AA URL 的 `models=` 参数一致。
- `build_efficiency_overview(models, focus=None, scope="focus")` 产出：

```json
{
  "scope": "focus",
  "charts": [
    {
      "key": "agent_cost",
      "title": "Coding Agent 指数 vs 单任务成本",
      "source_url": "https://artificialanalysis.ai/agents/coding-agents",
      "x_label": "单任务成本", "x_unit": "USD", "x_lower_is_better": true,
      "y_label": "Coding Agent Index", "y_unit": "分",
      "points": [{"key": "...", "label": "...", "tool": "...", "effort": "...", "x": 1.2, "y": 61.6, "rank": 3, "focused": true}],
      "focus_total": 9, "focus_matched": 7, "missing": ["..."]
    }
  ],
  "focus": {"artificial_analysis_agent": [...], "artificial_analysis_model": [...]}
}
```

规则：

1. 只有 x、y 均为有限数字的点才进入 `points`；
2. `scope="focus"`（默认）只返回命中关注列表的点；`scope="all"` 返回全量并保留 `focused` 标记供前端高亮；
3. 默认关注项来自用户给出的 AA 链接（9 个 agent + 23 个 model slug），作为常量内置；
4. `missing` 暴露关注但未匹配到的键，便于发现 AA 改名/下架。

### 3. 接口（`model_dashboard/server.py`）

`GET /api/efficiency?scope=focus|all`；非法 scope 抛 `DashboardError`（中文提示），错误响应沿用现有 400 JSON 约定。

### 4. 前端（`model_dashboard/static/index.html`）

- 顶部导航新增 `data-view="efficiency"`「效率对比」；
- `loadData()` 并行拉取 `/api/efficiency`，失败降级为空态并在面板内提示；
- `renderEfficiencyPage()`：hero + scope 切换（关注项 / 全部）+ 三张自绘 SVG 散点图（viewBox 0 0 720 380，等距刻度、网格线、点标签仅关注项显示，`<title>` 提供原生 tooltip）+ 紧随其后的明细表（名称 / 能力分 / 成本 / 耗时）；
- 配色沿用 light 主题：轴与网格 `#e6e8ed`、文字 `#6c727e`、关注点 `#3567c9`、其余点 `#81a2e0`（透明度区分）。

### 5. 测试（新增 `tests/test_efficiency.py`）

- 模型归一化产出新字段（含 variant 级、缺失字段为 None）；
- `build_efficiency_overview`：三张图各自只取对应来源、丢弃缺轴值的点、focus 过滤与 `missing` 统计、`scope=all` 保留 `focused`、非法 scope 报错；
- HTTP：接口返回三张图、`scope` 非法返回 400。

### 6. 数据刷新

存量快照（2026-09-21）不含模型级 cost/time，需执行一次「同步 AA Model 全榜 / AA Agent 全榜」才能出图。同步会写入 `var/sqlite/fox-airank-deepeval.db` 并保留历史快照，不改变其它来源（Arena、LLM Stats、本地 excel）的数据。

## 实现记录（2026-09-25）

- `codex-gpt-6-luna-max-reasoning-effort-max` 在 AA 当前数据里的键是 `codex-gpt-6-luna-max`（旧分享链接标签过期），关注项已按当前标签校正。
- 同步结果：AA Model 673 条（新增 23 / 更新 650）、AA Agent 20 条（新增 5 / 更新 15）。
- 关注项命中：Agent 9/9；Model 成本 21/23、耗时 20/23，未命中的 `k2-horizon-375b-a23b`、`gpt-5-5-pro`（AA 未发布该指标）与 `claude-opus-5-5`（缺 time per task）会在面板里显式提示。
- 验证：`python3 -m unittest discover -s tests` 183 项通过；`node --check` 校验内联脚本；用 jsdom 冒烟渲染 `#efficiency`，关注项模式 50 个点、全部模式 325 个点，无运行时错误。

### 7. 高性价比象限（Most attractive quadrant）

每张图额外计算「高性价比象限」并绘制：以**能力中位数**与**代价中位数**把画布切成四块，左上区域（能力高于中位数、代价低于中位数）用浅蓝底 + 两条虚线中位数分割线标出，区域内标注命中数量；明细表同步用 `★ 高性价比` 标记并给整行加底色。

- 后端：`attractive_quadrant(points)` 返回 `{"label", "hint", "x_max", "y_min", "count"}`，按当前可见点（focus/all 各自的点集）计算，不足 2 个点时为 `None`。
- 前端：`efficiencyScatter` 在网格线之前绘制矩形，避免遮挡点；对数轴下同样用像素投影，视觉位置保持一致。
- 实测命中：关注项模式 Agent 1 个、Model 成本 5 个、Model 耗时 6 个；全部模式分别为 2 / 19 / 28 个。Agent 图命中极少，说明强模型普遍更贵。

### 7.1 Pareto 前沿包络线

每张散点图额外画出二维 Pareto 前沿（x 越小越好、y 越大越好）：按 x 升序扫描，只要 y 严格超过此前所有点的最大 y 就进入前沿，得到左上包络线。

- 后端 `scatter_pareto_keys(points)` 返回按成本升序的 `pareto_keys`，写入每张图；单点时也返回该点。
- 前端用金色（`#aa8040`）阶梯折线连接：从左侧轴水平进入第一个点，之后「水平 → 竖直」逐级上升，末端延伸到绘图区右边缘；前沿点用金色描边加粗，非前沿点保持蓝色，图例增加「Pareto 前沿 N 个」，明细表新增「Pareto」列（★ 前沿）。
- 与「高性价比象限」互补：象限给的是**中位数划分的区域**，前沿给的是**不可再优化的取舍边界**——落在前沿上的点不存在"更便宜还更强"的替代项。
- 实测：关注项模式 Agent 5/9、Model 成本 7/21、Model 耗时 5/20 落在前沿；全部模式分别为 10/20、14/156、12/149。

### 8. 三维平衡算法（能力 / 成本 / 耗时）

目标：在「能力越高越好、单任务成本越低越好、单任务耗时越低越好」三个维度上给出最优选择，而不是只按单一榜单排名。

算法分两步：

1. **Pareto 前沿（无权重、客观筛选）**：若存在另一条记录能力 ≥、成本 ≤、耗时 ≤ 且至少一项严格更优，则当前记录被支配，不进入前沿。前沿上的条目互不支配，代表真实的取舍边界。
2. **加权归一化打分（有偏好、可解释排序）**：
   - 能力：min-max 归一化（0–100，越大越好）；
   - 成本 / 耗时：min-max 归一化后取反（越便宜/越快得分越高）；
   - **跨度超过 20 倍时改用 log10 归一化**，避免 0.08 USD 与 13 USD 这类极端值把差异压成 0/1；
   - `balance_score = Σ wᵢ × normᵢ × 100`，默认权重 能力 40% / 成本 30% / 耗时 30%。
3. **缺维度不参与排名**：缺少任一维度的条目进入 `incomplete` 列表（前端提示缺什么），避免用 0 分假装便宜/快。

预置权重：均衡（0.4/0.3/0.3）、能力优先（0.6/0.2/0.2）、省钱优先（0.2/0.5/0.3）、省时优先（0.2/0.3/0.5），通过 `GET /api/efficiency?weights=capability:0.6,cost:0.2,time:0.2` 传入；权重必须三项齐全、介于 0–1 且合计 100%，否则返回 400。

实测（关注项模式，均衡权重）：

| 组 | 最优 | 能力 | 成本 (USD) | 耗时 (秒) | 平衡分 | 前沿 |
| --- | --- | --- | --- | --- | --- | --- |
| Coding Agent | Codex – GPT-6 Sol (max) | 56.66 | 2.99 | 1338 | 62.77 | 7/9 |
| Model | GPT-6 Sol (medium) | 39.78 | 0.25 | 60 | 68.88 | 10/20 |

切换到「能力优先」后 Agent 最优变为 Codex – GPT-6 Astra (max)（61.65 / 7.47 USD），Model 最优变为 Claude Opus 5.5 High Effort（53.58 / 1.82 USD）——权重改变会显著改变结论，因此界面上把权重前置展示。
