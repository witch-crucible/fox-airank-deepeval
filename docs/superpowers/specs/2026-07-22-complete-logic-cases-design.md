# 补全 logic_analysis 空 case + 工具支持review 设计

## 背景

`cases/logic_analysis/` 下有 3 个空目录（`async_search_race`、`access_policy`、
`cart_event_trace`），未纳入 `benchmark/specs.json`，也没有 `case.json` /
`TASK.md`。README 声明 logic_analysis 应有 4 个 case，实际已有 4 个可用
（`comment_implementation`、`commit_consistency`、`fragmented_business_rule`、
`result_process`），这 3 个是未完成的规划项。

工具支持方面，`tools.json` 目前配置 codex / claude-code / qwen / opencode 四个
工具，Qoder 未安装，本次不新增真实接入，只做既有配置的健壮性 review。

## 目标

1. 为 3 个空 case 设计与现有 4 个 logic_analysis case 同等严谨度的场景、
   `TASK.md`、数据文件、`case.json`，并在 `benchmark/specs.json` 登记
   `expected` 答案（固定词表、可精确比对）。
2. 更新 `tests/test_benchmark.py` 中的 case 数量断言（10 → 13）。
3. Review `tools.json` 四个现有工具命令的健壮性（非交互参数是否正确、是否有
   遗漏的一致性问题），不新增 Qoder 真实配置。

## 新 case 设计

每个 case 遵循现有协议：只读分析，产出 `result.json` 的 `answer` 字段，字段
必须使用固定词表以保证可自动判分。

### 1. `logic-async-search-race`（异步竞态合约偏差）

- 目录：`cases/logic_analysis/async_search_race/`
- 文件：`search.js`（含 doc-comment 契约：只有最新一次请求的结果允许
  `render`，更早发起、更晚返回的请求必须丢弃）+ 实现有 bug：`render(suggestions)`
  无条件调用，未比较 `token === latestToken`。
- 与 `comment_implementation` 同构（读注释找实现偏差），但场景换成异步竞态。
- `answer`：
  ```json
  {
    "contract_violated": true,
    "unguarded_call": "render(suggestions)",
    "missing_condition": "token === latestToken"
  }
  ```
  两个字段是从源码直接抄写的 JS 语句/表达式。

### 2. `logic-access-policy`（访问策略声明与实现不一致）

- 目录：`cases/logic_analysis/access_policy/`
- 文件：`ACCESS_POLICY.md`（角色 × 订单状态权限矩阵声明）+ `permissions.js`
  （实现，存在一处偏差：`submitted` 状态下 `editor` 本应仅可查看，代码却允许
  编辑）。
- 与 `commit_consistency`（声明 vs 实现）同构，换成策略文档 vs 权限代码。
- `answer`：
  ```json
  {
    "policy_matches_implementation": false,
    "violating_role": "editor",
    "violating_status": "submitted",
    "violating_action": "edit",
    "risk": "unauthorized-edit-of-submitted-order"
  }
  ```
  `violating_role` ∈ {editor, reviewer, admin}；`violating_status` ∈
  {draft, submitted, archived}；`violating_action` ∈ {view, edit}；
  `risk` 为固定字符串标识。

### 3. `logic-cart-event-trace`（购物车事件乱序追踪）

- 目录：`cases/logic_analysis/cart_event_trace/`
- 文件：`cart-events.json`（无源码，只有事件日志：每条含 `seq`
  客户端发起顺序、`type`（add_item/remove_item）、`item_id`、`sent_at`、
  `received_at`）。数据构造为：`sku-1` 的 add（seq1）与 remove（seq2）两条
  事件，`received_at` 顺序与 `sent_at`/`seq` 顺序相反，导致服务端按到达顺序
  应用后 `sku-1` 残留在购物车中（应为空）。其余事件（`sku-2` 的
  add/remove）顺序正常，作为对照不产生偏差。
- 与 `result_process`（无源码，从结果数据反推缺陷）同构，换成购物车事件而非
  结账幂等性问题。
- `answer`：
  ```json
  {
    "process_issue": "out-of-order-event-application",
    "evidence": {"out_of_order_pairs": 1, "affected_items": 1},
    "control": "sequence-number-enforcement"
  }
  ```
  `process_issue` ∈ {out-of-order-event-application,
  duplicate-event-processing, missing-event-delivery}；`control` ∈
  {sequence-number-enforcement, idempotency-key-per-intent, increase-timeout}。

## 改动文件清单

- 新增：
  - `cases/logic_analysis/async_search_race/{case.json,TASK.md,search.js}`
  - `cases/logic_analysis/access_policy/{case.json,TASK.md,ACCESS_POLICY.md,permissions.js}`
  - `cases/logic_analysis/cart_event_trace/{case.json,TASK.md,cart-events.json}`
- 修改：
  - `benchmark/specs.json`：新增 3 个 case 的 `expected` 条目
  - `tests/test_benchmark.py`：`assertEqual(len(cases), 10)` → `13`
  - `README.md`：logic_analysis 数量 4 → 7，总 case 数 10 → 13
- Review（不一定改动）：
  - `tools.json`：确认 codex/claude-code/qwen/opencode 四个命令的非交互参数
    仍然正确、一致；不新增 Qoder 真实条目。

## 验证

- `python3 -m unittest discover -s tests -v`：参考解需对 13 个 case 都拿满分。
- `python3 -m compileall -q benchmark tests`
- `python3 benchmark.py list`：确认新 3 个 case 出现且 id/category 正确。

## 风险 / 边界

- 3 个新场景的“正确答案”均由本设计中固定构造的数据/代码决定，不存在
  多解歧义；已在设计阶段人工核对过唯一性（见上方逐条推导）。
- 不涉及现有 4 个 case、现有工具命令的行为变更（`tools.json` 只 review 不改，
  除非 review 中发现明确错误）。
