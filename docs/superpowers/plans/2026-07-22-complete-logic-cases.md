# 补全 logic_analysis 空 case Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 `cases/logic_analysis/` 下 3 个空 case 目录（`async_search_race`、
`access_policy`、`cart_event_trace`），使 logic_analysis 类别从 4 个扩展到 7 个，
总 case 数从 10 变为 13，并同步更新测试与文档；同时 review（不改动，除非发现
明确错误）`tools.json` 现有 4 个工具命令。

**Architecture:** 每个 case 是一个独立目录：`case.json`（id/category/title）+
`TASK.md`（任务说明，固定词表答案格式）+ 场景数据文件（源码或日志/文档）。
判分逻辑已存在于 `benchmark/cli.py` 的 `grade_case`：`type: "logic"` 的 case
直接比较 `result.json` 的 `answer` 字段与 `benchmark/specs.json` 里的
`expected` 是否严格相等，因此新 case 只需要往 `specs.json` 加条目，无需改
`benchmark/` 下任何代码。

**Tech Stack:** Python 3.10+（`benchmark/cli.py` 的 `load_cases`/`grade` 逻辑
不变），纯 JSON/Markdown/JS 场景文件，`unittest` 测试。

## Global Constraints

- 不修改 `benchmark/cli.py`、`benchmark/report.py` 的判分/报告逻辑。
- 新 case 的 `answer` 字段必须使用设计文档
  `docs/superpowers/specs/2026-07-22-complete-logic-cases-design.md` 中
  逐条推导过的固定词表，保证唯一正确答案。
- 每个 case 目录结构必须与现有 4 个 logic_analysis case 一致：
  `case.json` 含 `id`/`category`/`title` 三个字段；`TASK.md` 用中文，结尾
  给出 `answer` 的 JSON 结构与字段取值范围。
- `tools.json` 本次只 review，不新增 Qoder 真实条目，不改动现有 4 个工具的
  command 数组，除非 review 发现明确 bug（若发现，作为独立 Task 6 处理）。

---

### Task 1: `logic-async-search-race` case

**Files:**
- Create: `cases/logic_analysis/async_search_race/case.json`
- Create: `cases/logic_analysis/async_search_race/search.js`
- Create: `cases/logic_analysis/async_search_race/TASK.md`
- Modify: `benchmark/specs.json`

**Interfaces:**
- Consumes: `benchmark/cli.py` 的 `load_cases()`（按 `cases/*/*/case.json` glob
  扫描，读取 `id`/`category`/`title`）与 `grade_case()`（`type: "logic"` 时比较
  `result.json` 里 `answer` 与 `specs.json[case_id]["expected"]` 是否相等）。
- Produces: `case.json` 里的 `id` 字段 `"logic-async-search-race"` 供 Task 4
  的测试断言使用；`specs.json` 新增的顶层 key 必须与此 `id` 完全一致。

- [ ] **Step 1: 创建 `case.json`**

```json
{"id":"logic-async-search-race","category":"logic_analysis","title":"从异步竞态合约发现代码实现偏差"}
```

- [ ] **Step 2: 创建 `search.js`**

```js
/**
 * 搜索建议函数。
 * 每次输入变化都会调用一次 search，发起新的建议请求。
 * 只有最新一次发起的请求，其结果才允许调用 render；更早发起、
 * 但更晚返回的请求结果必须丢弃，不能调用 render。
 */
let latestToken = 0;

export async function search(query, fetchSuggestions, render) {
  const token = ++latestToken;
  const suggestions = await fetchSuggestions(query);
  render(suggestions);
}
```

- [ ] **Step 3: 创建 `TASK.md`**

```markdown
# 从异步竞态合约发现代码实现偏差

阅读 `search.js`。注释是已确认的业务契约，分析代码是否符合注释，并指出最小
修正条件。不要修改代码。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "contract_violated": true,
  "unguarded_call": "代码中未加保护的调用语句",
  "missing_condition": "缺失的保护条件表达式"
}
```

两个字段直接抄写 `search.js` 中的 JavaScript 语句/表达式，不附加解释。
```

- [ ] **Step 4: 在 `benchmark/specs.json` 中新增条目**

打开 `benchmark/specs.json`，在顶层对象中新增一个 key（与其他 9 个条目同级，
注意补逗号）：

```json
"logic-async-search-race": {
  "type": "logic",
  "expected": {
    "contract_violated": true,
    "unguarded_call": "render(suggestions)",
    "missing_condition": "token === latestToken"
  }
}
```

- [ ] **Step 5: 校验 JSON 合法性**

Run: `python3 -c "import json; json.load(open('benchmark/specs.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 6: 校验 case 能被扫描到**

Run: `python3 benchmark.py list | grep logic-async-search-race`
Expected: 输出一行 `logic-async-search-race    logic_analysis   从异步竞态合约发现代码实现偏差`

- [ ] **Step 7: Commit**

```bash
git add cases/logic_analysis/async_search_race benchmark/specs.json
git commit -m "feat: add logic-async-search-race case"
```

---

### Task 2: `logic-access-policy` case

**Files:**
- Create: `cases/logic_analysis/access_policy/case.json`
- Create: `cases/logic_analysis/access_policy/ACCESS_POLICY.md`
- Create: `cases/logic_analysis/access_policy/permissions.js`
- Create: `cases/logic_analysis/access_policy/TASK.md`
- Modify: `benchmark/specs.json`

**Interfaces:**
- Consumes: 同 Task 1（`load_cases()` / `grade_case()`）。
- Produces: `case.json` 的 `id` 字段 `"logic-access-policy"`，`specs.json`
  对应 key 需与此一致，供 Task 4 测试使用。

- [ ] **Step 1: 创建 `case.json`**

```json
{"id":"logic-access-policy","category":"logic_analysis","title":"检查访问策略声明与实现是否一致"}
```

- [ ] **Step 2: 创建 `ACCESS_POLICY.md`**

```markdown
# 订单访问策略

- `draft` 状态：`editor` 可查看和编辑；`reviewer` 只能查看；`admin` 可查看、
  编辑、删除。
- `submitted` 状态：`editor` 仅可查看，不可编辑；`reviewer` 可查看和编辑
  （用于审核修改）；`admin` 可查看、编辑、删除。
- `archived` 状态：仅 `admin` 可查看；其他角色不可查看、不可编辑、不可删除。
```

- [ ] **Step 3: 创建 `permissions.js`**

```js
export function canView(role, orderStatus) {
  if (role === "admin") return true;
  if (orderStatus === "archived") return false;
  return role === "editor" || role === "reviewer";
}

export function canEdit(role, orderStatus) {
  if (role === "admin") return true;
  if (orderStatus === "draft") return role === "editor";
  if (orderStatus === "submitted") return role === "editor" || role === "reviewer";
  return false;
}
```

- [ ] **Step 4: 创建 `TASK.md`**

```markdown
# 检查访问策略声明与实现是否一致

阅读 `ACCESS_POLICY.md` 和 `permissions.js`，判断实现是否完全符合策略声明。
只指出策略明确覆盖的行为，不提出无关重构。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "policy_matches_implementation": false,
  "violating_role": "角色标识",
  "violating_status": "订单状态标识",
  "violating_action": "操作标识",
  "risk": "固定风险标识"
}
```

`violating_role` 只能是 `editor`、`reviewer`、`admin`；`violating_status`
只能是 `draft`、`submitted`、`archived`；`violating_action` 只能是 `view`、
`edit`；`risk` 只能是 `unauthorized-edit-of-submitted-order`。
```

- [ ] **Step 5: 在 `benchmark/specs.json` 中新增条目**

```json
"logic-access-policy": {
  "type": "logic",
  "expected": {
    "policy_matches_implementation": false,
    "violating_role": "editor",
    "violating_status": "submitted",
    "violating_action": "edit",
    "risk": "unauthorized-edit-of-submitted-order"
  }
}
```

- [ ] **Step 6: 校验 JSON 合法性**

Run: `python3 -c "import json; json.load(open('benchmark/specs.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 7: 校验 case 能被扫描到**

Run: `python3 benchmark.py list | grep logic-access-policy`
Expected: 输出一行 `logic-access-policy` 对应 title

- [ ] **Step 8: Commit**

```bash
git add cases/logic_analysis/access_policy benchmark/specs.json
git commit -m "feat: add logic-access-policy case"
```

---

### Task 3: `logic-cart-event-trace` case

**Files:**
- Create: `cases/logic_analysis/cart_event_trace/case.json`
- Create: `cases/logic_analysis/cart_event_trace/cart-events.json`
- Create: `cases/logic_analysis/cart_event_trace/TASK.md`
- Modify: `benchmark/specs.json`

**Interfaces:**
- Consumes: 同 Task 1。
- Produces: `case.json` 的 `id` 字段 `"logic-cart-event-trace"`，供 Task 4
  测试使用。

- [ ] **Step 1: 创建 `case.json`**

```json
{"id":"logic-cart-event-trace","category":"logic_analysis","title":"从购物车事件日志反推乱序缺陷"}
```

- [ ] **Step 2: 创建 `cart-events.json`**

```json
[
  {"seq": 1, "type": "add_item", "item_id": "sku-1", "sent_at": "2026-07-10T10:00:00.000Z", "received_at": "2026-07-10T10:00:00.100Z"},
  {"seq": 2, "type": "remove_item", "item_id": "sku-1", "sent_at": "2026-07-10T10:00:00.200Z", "received_at": "2026-07-10T10:00:00.050Z"},
  {"seq": 3, "type": "add_item", "item_id": "sku-2", "sent_at": "2026-07-10T10:00:00.300Z", "received_at": "2026-07-10T10:00:00.310Z"},
  {"seq": 4, "type": "remove_item", "item_id": "sku-2", "sent_at": "2026-07-10T10:00:00.400Z", "received_at": "2026-07-10T10:00:00.410Z"}
]
```

（`seq` 是客户端发起顺序；服务端按 `received_at` 到达顺序应用事件。`sku-1`
的两条事件里，`remove_item`（seq2）比 `add_item`（seq1）更晚发出，却更早
到达，导致服务端按到达顺序应用后 `sku-1` 残留在购物车——而按发起顺序
应有的最终状态是 `sku-1` 已被移除。`sku-2` 的两条事件到达顺序与发起顺序
一致，无缺陷，作为对照。）

- [ ] **Step 3: 创建 `TASK.md`**

```markdown
# 从购物车事件日志反推乱序缺陷

本 case 没有源码。阅读 `cart-events.json`：每条事件包含客户端发起顺序 `seq`、
事件类型 `type`（`add_item`/`remove_item`）、`item_id`，以及客户端发出时间
`sent_at` 与服务端收到时间 `received_at`。服务端按 `received_at` 到达顺序
应用事件来维护购物车状态。

请找出因为事件到达顺序与发起顺序不一致而导致的最终购物车状态错误，
统计受影响的“乱序事件对”数量与受影响的商品数量。

按 `RESULT_PROTOCOL.md` 生成 `result.json`，`answer` 必须严格为：

```json
{
  "process_issue": "固定问题标识",
  "evidence": {"out_of_order_pairs": 0, "affected_items": 0},
  "control": "固定措施标识"
}
```

问题标识只能是 `out-of-order-event-application`、
`duplicate-event-processing`、`missing-event-delivery`；措施标识只能是
`sequence-number-enforcement`、`idempotency-key-per-intent`、
`increase-timeout`。
```

- [ ] **Step 4: 在 `benchmark/specs.json` 中新增条目**

```json
"logic-cart-event-trace": {
  "type": "logic",
  "expected": {
    "process_issue": "out-of-order-event-application",
    "evidence": {
      "out_of_order_pairs": 1,
      "affected_items": 1
    },
    "control": "sequence-number-enforcement"
  }
}
```

- [ ] **Step 5: 校验 JSON 合法性**

Run: `python3 -c "import json; json.load(open('benchmark/specs.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 6: 校验 case 能被扫描到**

Run: `python3 benchmark.py list | grep logic-cart-event-trace`
Expected: 输出一行 `logic-cart-event-trace` 对应 title

- [ ] **Step 7: Commit**

```bash
git add cases/logic_analysis/cart_event_trace benchmark/specs.json
git commit -m "feat: add logic-cart-event-trace case"
```

---

### Task 4: 更新测试用例数量断言

**Files:**
- Modify: `tests/test_benchmark.py:13`

**Interfaces:**
- Consumes: `benchmark.cli.load_cases()`（此时应返回 13 个 `Case`，因为
  Task 1-3 已在 `cases/logic_analysis/` 下新增 3 个含 `case.json` 的目录）。
- Produces: 无（测试文件，不被其他任务消费）。

- [ ] **Step 1: 确认当前测试会失败（因为 case 数已变成 13）**

Run: `python3 -m unittest tests.test_benchmark -v 2>&1 | head -20`
Expected: `test_reference_solutions_score_full_marks` 失败，报错类似
`AssertionError: 13 != 10`

- [ ] **Step 2: 修改断言**

在 `tests/test_benchmark.py` 中定位：

```python
        cases = load_cases()
        self.assertEqual(len(cases), 10)
```

改为：

```python
        cases = load_cases()
        self.assertEqual(len(cases), 13)
```

- [ ] **Step 3: 运行完整测试套件**

Run: `python3 -m unittest discover -s tests -v`
Expected: 全部测试 `ok`，包括
`test_reference_solutions_score_full_marks`（新 3 个 logic case 因为
`type == "logic"` 分支通用处理 `result["answer"] = specs[case.id]["expected"]`，
会自动拿满分，无需额外改动这个测试方法体）。

- [ ] **Step 4: 编译检查**

Run: `python3 -m compileall -q benchmark tests`
Expected: 无输出（无编译错误）

- [ ] **Step 5: Commit**

```bash
git add tests/test_benchmark.py
git commit -m "test: bump expected case count to 13"
```

---

### Task 5: 更新 README 文档

**Files:**
- Modify: `README.md:5-9`

**Interfaces:**
- Consumes: 无（纯文档）。
- Produces: 无。

- [ ] **Step 1: 修改 case 数量描述**

定位 `README.md` 中：

```markdown
评测覆盖三类能力，共 10 个前端 JavaScript case：

- `logic_analysis`（4 个）：从零散业务沟通还原规则、检查 commit 声明与 diff 是否一致、对照注释发现实现偏差、从结果数据反推过程缺陷。
```

改为：

```markdown
评测覆盖三类能力，共 13 个前端 JavaScript case：

- `logic_analysis`（7 个）：从零散业务沟通还原规则、检查 commit 声明与 diff 是否一致、对照注释发现实现偏差、从结果数据反推过程缺陷、从异步竞态合约发现实现偏差、检查访问策略声明与实现是否一致、从购物车事件日志反推乱序缺陷。
```

- [ ] **Step 2: 校验没有其他地方引用旧的 "10 个" / "4 个"**

Run: `grep -n "10 个\|4 个" README.md`
Expected: 无匹配（说明已全部更新一致）

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update case counts to 13 total / 7 logic_analysis"
```

---

### Task 6: Review `tools.json` 现有工具命令

**Files:**
- Read-only review: `tools.json`
- Modify (仅当发现明确错误时): `tools.json`

**Interfaces:**
- Consumes: `benchmark/cli.py` 的 `load_tool_config()`（校验每个工具的
  `command` 是非空数组）与 `execute()`（用 `shutil.which(executable)`
  检查可执行文件是否存在于 `PATH`，再用 `str.format` 替换 `{workspace}`/
  `{prompt}` 占位符，`subprocess.run` 时 `cwd=workspace`）。
- Produces: 无（本任务不引入新接口）。

- [ ] **Step 1: 逐个核对四个工具命令的非交互性与占位符用法**

Run:

```bash
python3 -c "
import json
d = json.load(open('tools.json'))
for name, cfg in d.items():
    print(name, cfg['command'])
"
```

Expected 输出（当前内容，逐条人工核对）：

```
codex ['codex', 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'workspace-write', '{prompt}']
claude-code ['claude', '-p', '--permission-mode', 'auto', '--no-session-persistence', '{prompt}']
qwen ['qwen', '-p', '{prompt}']
opencode ['opencode', 'run', '--auto', '{prompt}']
```

核对要点（对照各 CLI 官方非交互模式文档，逐条确认，不臆测）：
- 每条命令必须是非交互式（不会等待终端输入）。
- 每条命令必须能在 `cwd=workspace` 下正确执行且写文件到当前目录，而不是
  默认写到别处。
- `{prompt}` 占位符必须落在正确的参数位置（作为命令的最后一个自由文本参数，
  不被当作 flag 解析）。

- [ ] **Step 2: 如果发现明确错误，修正并说明原因**

如果 Step 1 核对后发现某个工具的参数确实有问题（例如版本升级后 flag 改名、
非交互 flag 缺失导致会 hang），在 `tools.json` 中修正对应 `command` 数组，
并在下面这条 commit message 里写清楚具体是哪个工具、什么问题。如果核对后
没有发现问题，跳过本步骤，不做任何修改。

- [ ] **Step 3: 校验 JSON 合法性（如有修改）**

Run: `python3 -c "import json; json.load(open('tools.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit（仅当 Step 2 有实际修改时）**

```bash
git add tools.json
git commit -m "fix: correct <tool> non-interactive flag in tools.json"
```

如果 Step 2 未做任何修改，本任务无需 commit，直接结束。

---

## 完成标准

- `python3 benchmark.py list` 输出 13 行，`logic_analysis` 类别有 7 行。
- `python3 -m unittest discover -s tests -v` 全部通过。
- `python3 -m compileall -q benchmark tests` 无报错。
- `README.md` 中的 case 数量描述与实际一致。
- `tools.json` 经过人工 review，若有明确错误已修正并说明。
