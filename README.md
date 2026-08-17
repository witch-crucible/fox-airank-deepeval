# 前端代码代理能力基准测试

比较 Codex、Claude Code、Qwen Code、OpenCode、Qoder 等代码代理工具在真实项目工作流中的能力，而非直接调用模型 API。

共 14 个前端 JavaScript case，分三类：

- `logic_analysis`（7 个）：从沟通记录、diff、注释、日志等零散材料反推业务规则或实现缺陷（含竞态、访问策略漂移、事件乱序等场景）。
- `code_correction`（3 个）：修复购物车金额、查询参数、分页边界缺陷。
- `code_generation`（4 个）：实现商品筛选、分页 reducer、安全商品卡片、像素风打飞机小游戏。

每个工具在独立副本中读取 `TASK.md`、修改文件、生成 `result.json`；评分器再运行不会复制到工作区的隐藏检查。功能检查占 90 分，结果文件协议占 10 分。

## 前置条件

- Python 3.10+、Node.js 18+
- 待测试代码代理 CLI 已安装并登录

`tools.json` 已配置 Codex、Claude Code、Qwen Code、OpenCode。新增工具只需按其非交互命令追加一条配置，命令数组支持 `{prompt}`、`{workspace}` 占位符（不经过 shell 展开）：

```json
{"qoder": {"command": ["实际可执行文件", "非交互参数", "{prompt}"]}}
```

## 使用

### 批量运行

`run_benchmark.py` 会按顺序执行 `prepare`、`execute`、`grade`。默认读取 `tools.json`，测试其中配置的全部工具和全部 case。未传 `--run-id` 时，脚本会先询问所选 CLI 的 Agent 与实际模型，并按 `<agent>-<model>-<时间戳>` 生成 run ID；探测失败时使用配置值或 `unknown`：

```bash
python3 run_benchmark.py
```

只运行 Qwen Code，或进一步限制 case：

```bash
python3 run_benchmark.py --tool qwen

python3 run_benchmark.py \
  --tool qwen \
  --case fix-cart-total \
  --timeout 600
```

`--tool`、`--case` 和 `--category` 均可重复传入。使用 `--run-id smoke-001` 可固定输出目录；使用 `--config custom-tools.json` 可加载其他工具配置。完成后脚本会打印 `runs/<run-id>/report.html` 和 `report.json` 的路径。

### OpenCode 隔离

OpenCode 固定使用 `build` Agent，模型使用当前 OpenCode 有效配置。`tools.json` 中的 `--dir {workspace}` 设置当前 case 为工作目录，`--pure` 禁止加载 OMO 等外部插件，降低误读其他 case、历史 run 或调用额外模型的风险。如需严格比较固定模型，应在 `tools.json` 的 OpenCode 命令中显式增加 `--model <模型 ID>`：

```bash
python3 run_benchmark.py \
  --tool opencode \
  --case fix-pagination-window \
  --timeout 180
```

不要从 OpenCode 命令中移除 `--dir {workspace}` 或 `--pure`，否则 OpenCode 可能将仓库根目录识别为工作区，破坏 case 隔离。`prepare` 还会忽略源 case 中残留的 `result.json`、`agent.log` 和 `execution.json`，防止旧执行产物进入新 run；源 case 目录仍应保持无生成文件。

### 分步运行

```bash
python3 benchmark.py list                                              # 查看 case

python3 benchmark.py prepare --run-id compare-001 \
  --tool codex --tool claude --tool opencode                           # 准备隔离副本

python3 benchmark.py execute --run-dir runs/compare-001 \
  --tool codex --tool claude --tool opencode                           # 依次执行代理工具

python3 benchmark.py grade --run-dir runs/compare-001 \
  --tool codex --tool claude --tool opencode                           # 评分并生成报告
```

报告写入 `runs/compare-001/report.json` 与 `report.html`（可直接用浏览器打开），对比工具总分、三类能力分数、每个 case 得分及协议/功能检查详情；每个 case 目录下还保留 `agent.log` 与 `execution.json`，记录执行过程、退出码和耗时。

三个命令都支持重复传入 `--case`/`--category` 做小规模试跑。`prepare` 后也可以不用 `execute`，改为手工进入 case 目录跑交互式代理——只要最终生成合法 `result.json`，就能统一执行 `grade`。

### 手动测试 case 的无头执行与评分

原来依靠人工提问和记分的测试可以作为 `manual` case 纳入同一流程。case 目录仍只放 `case.json`、`TASK.md` 和 Agent 可见的输入材料；标准答案放在不会复制进运行工作区的 `benchmark/specs.json`：

```json
{
  "manual-example": {
    "type": "manual",
    "expected": {
      "decision": "reject",
      "evidence": {"count": 2, "risk": "high"}
    }
  }
}
```

`TASK.md` 应明确要求在 `result.json.answer` 中输出与标准答案同结构的 JSON，但不能包含答案值。`execute` 使用 `tools.json` 中配置的 Codex、Claude、Qwen 或 OpenCode 无头命令执行，并在 `runs/<run-id>/<tool>/<case>/` 保存 `agent.log`、`execution.json` 和 `result.json`。`grade` 按隐藏标准答案的叶子字段逐项比较：匹配比例记录为 `manual_score`（0–10），同时按既有规则生成 `score`（功能 90% + 结果协议 10%）。实际 `answer` 会进入 `report.json`，便于复核；标准答案不会复制给 Agent。

```bash
python3 run_benchmark.py --category manual_test --tool codex
```

## 公平性与安全

- 各工具须使用相同 case、相同时间限制和等价的权限配置；建议固定实际使用的模型和推理等级，并在报告外另行记录版本。
- 每次更换 Agent 或模型都应使用新的 run ID，不得在已执行的 case 工作区上继续测试另一模型。
- 工作区内 `AGENTS.md` 明确禁止读取父目录和评分器；同一仓库无法形成密码学意义上的隐藏测试，严格评测可将 `benchmark/specs.json` 和评分动作放到代理无法访问的外部环境。
- 代码代理会执行命令和修改文件，应在无敏感凭据、权限受限的临时环境中运行。

## 验证项目自身

参考解会完整跑过 14 个 case 的评分规则：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q benchmark model_dashboard tests run_benchmark.py
```

## AI 模型能力看板

`model_dashboard/` 提供一个基于 `模型能力测试-20260623-展示优化版.xlsx` 数据整理的本地 HTML 看板。它展示人工测试、ModelTest、Arena WebDev、费用快照和原表综合分，支持看板/表格模式切换、搜索/筛选、全量排序后分页、归档/恢复、增加模型，以及从第三方 JSON API 拉取数据。

页面右上角的“同步 Arena 前 30”会主动读取 [Arena WebDev 榜单](https://arena.ai/leaderboard/code/webdev) 的官方 `webdev/latest` 数据集快照，并同步当前 Overall 前 30 名。重复同步只替换上一次 Arena 同步记录，不会覆盖 Excel、手工或其他第三方记录；若官方数据不足 30 条则拒绝写入，保留上一次完整结果。

“同步 AA 编程榜”会主动读取 [Artificial Analysis Coding Agents](https://artificialanalysis.ai/agents/coding-agents) 官方页面嵌入的完整榜单，保存 Coding Agent Index 排名、总分，以及 DeepSWE、Terminal-Bench v2、SWE-Atlas-QnA 三项分数。同步记录还保留官方记录 ID、Agent、模型、指数版本、每任务成本和运行时间；重复同步只替换上一次 Artificial Analysis 记录。该指数使用独立字段，不参与原表综合分。

“同步 LLM Stats”会主动读取 [LLM Stats](https://llm-stats.com/) 官网使用的公开 `general` 指数榜单，保存官网排名、LLM Stats Score，以及 Reasoning、Code、Agents 三个主要分项。同步记录还保留官方模型 ID、组织、14 天排名变化和参与评测数；重复同步只替换上一次 LLM Stats 记录，接口数据无效时保留已有结果。LLM Stats 分数使用独立字段，不参与原表综合分。

直接启动（无需安装额外依赖）：

```bash
python3 -m model_dashboard.server
```

浏览器打开 <http://127.0.0.1:8765>。新增或导入的数据写入被 Git 忽略的 `model_dashboard/data.local.json`；删除该文件即可恢复 Excel 种子数据。

第三方接口必须返回 JSON。页面支持通过点号路径映射嵌套字段；例如接口返回：

```json
{
  "data": {
    "models": [
      {
        "agent": "Codex",
        "name": "GPT-X",
        "scores": {"model_test": 95, "arena": 1600}
      }
    ]
  }
}
```

可填写数组路径 `data.models`，并将 `tool` 映射到 `agent`、`model` 映射到 `name`、`scores.model_test_total` 映射到 `scores.model_test`。需要鉴权时，只在页面填写环境变量名，例如先运行 `export MODEL_API_TOKEN='...'`，再将该变量配置为 `Authorization` 请求头的 `Bearer ` 凭据；密钥本身不会写入页面或仓库。

看板计算口径：

- 人工测试总分是 Skill 调用、代码评审、逻辑分析、功能修复四项之和。
- ModelTest 总分按当前 case 数量加权：代码修正 3、代码生成 4、逻辑分析 7。
- 原表综合分沿用 Excel 公式：人工测试总分 + ModelTest 总分 + Arena WebDev。三者量纲不同，因此只用于还原原表排序，不代表归一化能力分。
