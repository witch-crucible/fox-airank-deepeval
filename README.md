# 前端代码代理能力基准测试

比较 Codex、Claude Code、Qwen Code、OpenCode、Qoder 等代码代理工具在真实项目工作流中的能力，而非直接调用模型 API。

共 14 个前端 JavaScript case，分三类：

- `logic_analysis`（7 个）：从沟通记录、diff、注释、日志等零散材料反推业务规则或实现缺陷（含竞态、访问策略漂移、事件乱序等场景）。
- `code_correction`（3 个）：修复购物车金额、查询参数、分页边界缺陷。
- `code_generation`（4 个）：实现商品筛选、分页 reducer、安全商品卡片、像素风打飞机小游戏。

每个工具在独立副本中读取 `TASK.md`、修改文件、生成 `result.json`。随后由 DeepEval 的三个 GEval 指标评审：`Task Correctness`、`Robustness, Safety and Regression`、`Delivery Evidence`。参考实现和逻辑题标准答案只进入裁判输入，不会复制到代理工作区；不再生成旧版 100 分或根级报告。

## 前置条件

- Python 3.10+、Node.js 18+
- `deepeval==4.2.0`（`python3 -m pip install -e .`）
- 待测试代码代理 CLI 已安装并登录
- 统一裁判要求本机已登录 Codex CLI，固定使用 `gpt-5.6-sol` 和 `high` 推理强度

`tools.json` 已配置 Codex、Claude Code、Qwen Code、OpenCode。新增工具只需按其非交互命令追加一条配置，命令数组支持 `{prompt}`、`{workspace}` 占位符（不经过 shell 展开）：

```json
{"qoder": {"command": ["实际可执行文件", "非交互参数", "{prompt}"]}}
```

## 使用

### 批量运行

`run_benchmark.py` 会按顺序执行 `prepare`、`execute`、`evaluate`。默认读取 `tools.json`，测试其中配置的全部工具和全部 case。未传 `--run-id` 时，脚本会先询问所选 CLI 的 Agent 与实际模型，并按 `<agent>-<model>-<时间戳>` 生成 run ID；探测失败时使用配置值或 `unknown`：

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

`--tool`、`--case` 和 `--category` 均可重复传入。使用 `--run-id smoke-001` 可固定输出目录；使用 `--config custom-tools.json` 可加载其他工具配置。完成后脚本会打印 `runs/<run-id>/deepeval/`，其中每个工具有独立的 TestRun JSON 和 HTML。

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

python3 benchmark.py evaluate --run-dir runs/compare-001 \
  --tool codex --tool claude --tool opencode                           # 执行 DeepEval 评测
```

结果写入 `runs/compare-001/deepeval/<tool>/`，包括 DeepEval TestRun JSON、HTML，以及三项指标的分数、理由、阈值和通过状态；每个 case 目录下继续保留 `agent.log`、`execution.json` 和 `result.json`。

三个命令都支持重复传入 `--case`/`--category` 做小规模试跑。`prepare` 后也可以不用 `execute`，改为手工进入 case 目录跑交互式代理，再执行 `evaluate`；缺失或无效的执行/结果文件会以显式证据进入裁判输入。

### 对比报告

评测完成后，`report` 子命令把分散在各工具目录下的 DeepEval TestRun 汇总成一张跨工具 × case 对比矩阵，便于直接比较不同 Agent/模型的表现：

```bash
python3 benchmark.py report --run-dir runs/compare-001                    # 单 run 对比矩阵
python3 benchmark.py report --run-dir runs/compare-001 --tool codex       # 只汇总部分工具
python3 benchmark.py report --history                                     # 汇总 runs/ 下全部 run 的历史对比
```

单 run 报告写入 `runs/<run-id>/report.json` 和 `report.md`：汇总表给出每个工具的 Agent/模型/智能度、通过数、通过率和三项指标均分；明细表按 case 列出各指标分数（✓/✗ 表示是否达到阈值）、执行状态和通过结论。历史报告写入 `runs/history-report.json` 和 `history-report.md`，每行是一个 run 中一个工具的汇总，用于跨模型、跨时间的纵向比较。报告只读取 TestRun JSON，不依赖 deepeval，可随时离线重新生成。

`run_benchmark.py` 批量流程会在 `evaluate` 之后自动执行 `report`，结束后同时打印 DeepEval 原始报告和对比报告路径。

### 逻辑 case 与 DeepEval 评分

逻辑 case 的标准答案放在不会复制进运行工作区的 `benchmark/specs.json`。代码 case 登记实际输出文件和 `tests/reference/` 参考实现；打飞机 case 会完整评审 `game-logic.js`、`game.js` 和 `index.html`：

`benchmark/specs.json` 的代码 case 使用 `actual_files` 和 `reference_files` 登记文件；逻辑 case 使用 `expected_answer` 登记隐藏标准答案。该清单不会复制到代理工作区。

`execute` 使用 `tools.json` 中配置的 Codex、Claude、Qwen 或 OpenCode 无头命令执行，并在 `runs/<run-id>/<tool>/<case>/` 保存 `agent.log`、`execution.json` 和 `result.json`。三个 GEval 指标使用固定评审步骤，阈值分别为 `0.8`、`0.7`、`0.7`；一个 case 必须三项全部通过。默认不启用 DeepEval 缓存，评测子进程会清除 `CONFIDENT_API_KEY`、禁用 dotenv/历史 keyfile 和交互 inspect 提示，因此结果只写本地。

```bash
python3 run_benchmark.py --category logic_analysis --tool codex
```

## 公平性与安全

- 各工具须使用相同 case、相同时间限制和等价的权限配置；建议固定实际使用的模型和推理等级，并在 DeepEval TestRun 的 hyperparameters 中记录版本。
- 每次更换 Agent 或模型都应使用新的 run ID，不得在已执行的 case 工作区上继续测试另一模型。
- 工作区内 `AGENTS.md` 明确禁止读取父目录和评分器；同一仓库无法形成密码学意义上的隐藏测试，严格评测可将 `benchmark/specs.json` 和评分动作放到代理无法访问的外部环境。
- 代码代理会执行命令和修改文件，应在无敏感凭据、权限受限的临时环境中运行。

## 验证项目自身

验证项目自身的 Python 代码和测试：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q benchmark model_dashboard tests run_benchmark.py
```

## AI 模型能力看板

`model_dashboard/` 提供一个基于 `模型能力测试-20260623-展示优化版.xlsx` 数据整理的本地 HTML 看板。它展示人工测试、ModelTest、Arena WebDev、费用快照和原表综合分，支持看板/表格模式切换、搜索/筛选、全量排序后分页、归档/恢复、增加模型、Agent 使用人数手工录入与 CSV 导入，以及从第三方 JSON API 拉取数据。

页面右上角以“同步三方数据”为主按钮，会依次同步 Arena、Artificial Analysis、LLM Stats；某一源失败不影响其余来源，结束后给出汇总提示。旁边的“单项”菜单仍可单独同步某一个榜单。

- “同步 Arena 前 30”读取 [Arena WebDev 榜单](https://arena.ai/leaderboard/code/webdev) 的官方 `webdev/latest` 数据集快照，并同步当前 Overall 前 30 名。重复同步只替换上一次 Arena 同步记录，不会覆盖 Excel、手工或其他第三方记录；若官方数据不足 30 条则拒绝写入，保留上一次完整结果。
- “同步 AA 完整榜”读取 [Artificial Analysis Coding Agents](https://artificialanalysis.ai/agents/coding-agents) 官方页面嵌入的完整榜单（select all，不截断为前 30），保存 Coding Agent Index 排名、总分，以及 DeepSWE、Terminal-Bench v2.1、SWE-Atlas-QnA 三项分数。同步记录还保留官方记录 ID、Agent、模型、指数版本、每任务成本和运行时间；重复同步只替换上一次 Artificial Analysis 记录，不会覆盖 Excel、手工或其他来源。该指数使用独立字段，不参与原表综合分。看板能力排名区按 Agent（编程工具聚合）与 Model（模型配置逐条）两路展示当前指标得分及配对信息。
- “同步 LLM Stats 前 30”读取 [LLM Stats](https://llm-stats.com/) 官网使用的公开 `general` 指数榜单，只同步当前前 30 名，并保存官网排名、LLM Stats Score，以及 Reasoning、Code、Agents 三个主要分项。同步记录还保留官方模型 ID、组织、14 天排名变化和参与评测数；重复同步只替换上一次 LLM Stats 记录，不会覆盖 Excel、手工或其他来源；接口数据无效时保留已有结果。LLM Stats 分数使用独立字段，不参与原表综合分。

直接启动（无需安装额外依赖）：

```bash
python3 -m model_dashboard.server
```

开发时可用 `--reload` 监听 `model_dashboard/**/*.py` 变更并自动重启（不监听 `data.local.json`，避免写入数据时误重启）：

```bash
python3 -m model_dashboard.server --reload
```

浏览器打开 <http://127.0.0.1:8765>。新增或导入的数据写入被 Git 忽略的 `model_dashboard/data.local.json`；删除该文件即可恢复 Excel 种子数据。静态页面每次请求都会重新读取，改 `static/index.html` 后刷新浏览器即可，无需重启。

Agent 使用人数支持 CSV 文件导入（顶部「导入使用人数」、面板「导入 CSV」，或录入对话框内的「导入 CSV」）。表头需包含工具列和使用人数列，备注列可选，例如：

```csv
tool,user_count,notes
Claude Code,1200,Q2 内部统计
Codex,800,
```

也可用中文表头 `工具,使用人数,备注`。同名工具（大小写不敏感）会覆盖已有记录；文件内重复工具以最后一行为准。

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
