# 代码代理与项目业务分析基准测试

比较 Codex、Claude Code、Qwen Code、OpenCode、Qoder 等代码代理工具在真实项目工作流中的能力，而非直接调用模型 API。

当前包含 1 个前端 `code_generation` case（使用 HTML/SVG 绘制鹈鹕骑自行车的 2D 动画），以及 2 个 `magento_business` 项目业务分析 case。

前端用例在独立副本中读取 `TASK.md`、修改文件、生成 `result.json`；项目业务用例在指定项目目录执行只读分析，结果写入独立输出目录。随后由 DeepEval 的三个 GEval 指标评审：`Task Correctness`、`Robustness, Safety and Regression`、`Delivery Evidence`。参考实现和逻辑题标准答案只进入裁判输入，不会复制到代理工作区；不再生成旧版 100 分或根级报告。

## 思想声明

本项目不把模型宣传、主观印象或单项演示当作能力结论。模型本身的强弱，以及不同智能度（推理强度）带来的实际差异，必须依赖第三方测试和可复现的评测证据来判断；本项目使用统一 case、统一裁判指标和独立 run 记录这些比较结果。

项目的目的不是寻找抽象意义上“最强”的模型，而是通过测试，为当前项目和真实工作流选择最适合的模型与智能度组合。这里的“适合”同时包含任务效果、稳定性、安全边界、交付证据、耗时和失败成本；任何结论都只对本次 case 集合、测试配置和对应版本负责，不能直接外推为普遍能力排名。

本项目的测试基调是“日常最常见配置下的实际效果”，不是为每个工具寻找最高分的极限配置。默认应使用平时真实使用的 Agent、模型、推理强度、权限模式和超时；不临时增加只在测试中启用的高阶模型、超高推理档位或额外插件。这样得到的分数才可以回答：在相同任务和时间约束下，哪种工具配置更适合日常开发与业务分析。

## 快速启动

在仓库根目录执行。推荐使用 Python 虚拟环境，避免与系统 Python 的依赖互相影响：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

先确认当前登记的测试用例：

```bash
python3 benchmark.py list
```

### 启动一次最小基准测试

下面的命令只运行当前前端 case，并使用 `tools.json` 中的 Codex 配置。执行前请确认 Codex CLI 已安装、登录，且本机可调用统一裁判所需的模型：

```bash
python3 run_benchmark.py \
  --tool codex \
  --case draw-pelican-bicycle \
  --run-id smoke-codex-pelican
```

脚本会依次执行准备隔离工作区、调用 Agent、DeepEval 评分和生成对比报告；结果位于 `runs/smoke-codex-pelican/`。只想检查命令和 case 配置、不启动 Agent 时，使用：

```bash
python3 benchmark.py prepare \
  --run-id smoke-prepare \
  --tool codex \
  --case draw-pelican-bicycle
```

### 启动本地模型能力看板

另一个终端运行：

```bash
python3 -m model_dashboard.server
```

然后打开 <http://127.0.0.1:8765>。开发模式可自动监听 Python 文件变化并重启：

```bash
python3 -m model_dashboard.server --reload
```

按 `Ctrl-C` 停止服务。看板启动、数据文件和端口参数的完整说明见[“AI 模型能力看板”](#ai-模型能力看板)。

## 日常配置测试方法

每次比较分为两层：

1. **日常基线**：按用户平时的 CLI 配置运行全部目标 case。模型和推理强度沿用工具当前有效默认值，权限保持日常工作模式；不为了提高分数临时切换到最高档。需要比较多个工具时，尽量保持相同 case、超时、工作区隔离和裁判配置。
2. **候选配置对比**：只改变一个配置维度，例如模型、推理强度、Agent 或权限模式，再使用新的 `run-id` 重跑同一组 case。不要在同一个已执行工作区上继续测试另一配置。

每个 run 都会记录工具、Agent、实际模型和智能度（推理强度）。因此“适合日常”的结论应同时看以下结果，而不是只看单项最高分：

- 三项 GEval 指标是否全部达到阈值，尤其是 `Robustness, Safety and Regression` 与 `Delivery Evidence`；
- 多个 case 的通过率和失败是否集中在某一类任务，而不是单个题目的偶然高分；
- 执行耗时、超时和失败重试成本是否能接受；
- 权限、隔离和结果交付是否符合日常使用的安全边界。

推荐配置是“在日常基线下稳定通过、耗时可接受、失败模式可解释”的配置，而不是分数最高但依赖极限模型或极高推理档位的配置。报告只能说明本次 case 集合和当前配置下的效果，不能直接证明所有项目、所有模型版本或生产环境都同样适用。

## 前置条件

- Python 3.10+、Node.js 18+、Git
- `deepeval==4.2.0`（`python3 -m pip install -e .`）
- 待测试代码代理 CLI 已安装并登录
- 统一裁判要求本机已登录 Codex CLI，固定使用 `gpt-5.6-sol` 和 `high` 推理强度

`tools.json` 已配置 Codex、Claude Code、Command Code、Qwen Code、OpenCode。它是可复现执行用的命令配置，不等于所有用户的日常配置；正式比较前应确认其中的模型、推理强度和权限模式与实际日常使用一致。新增工具只需按其非交互命令追加一条配置，命令数组支持 `{prompt}`、`{workspace}`（实际执行目录）、`{output_dir}`（结果目录）占位符（不经过 shell 展开）：

```json
{"qoder": {"command": ["实际可执行文件", "非交互参数", "{prompt}"]}}
```

## 使用

### Magento 项目业务测试

| Case ID | 题目 |
| --- | --- |
| `magento-lady-dior-features` | 列出 Lady Dior 涉及功能 |
| `magento-post-shipment-exchange-intent` | 当前项目发货后换货意向单逻辑是什么？ |

两题的 `case.json` 通过 `project_dir` 指定 `/Users/ben/Code/Work/cdc-dior/middleground`。执行 Codex、Claude Code 等 CLI 时，以此目录作为 cwd；分析的是当前工作区，包含未提交修改。任务文件和答案保存在 `runs/<run-id>/<tool>/<case>/`。`prepare` 仅创建测试输入、记录项目路径、HEAD 和工作区状态，不启动 Agent 或裁判，也不修改 Magento 项目：

```bash
python3 benchmark.py prepare --run-id magento-check \
  --category magento_business --tool codex --tool claude
```

确需启动真实代理并评分时，使用新的 run ID 执行以下命令（会调用所选工具和 Codex 裁判）：

```bash
python3 run_benchmark.py --run-id magento-business-001 \
  --category magento_business --tool codex --tool claude
```

任务只允许源码分析，不允许修改业务源码、执行业务接口或操作数据库、缓存、队列。该约束通过任务提示传递，执行器不提供操作系统层面的只读隔离；CLI 本身仍受各自权限配置控制。默认 Codex/Claude 配置用 `--add-dir {output_dir}` 提供独立结果目录访问，自定义配置也需允许该目录。Command Code 的现有配置会持久化项目级 Taste Learning 设置，若要求完全不写项目配置，请使用 Codex/Claude 或另行调整工具配置。

每题交付 `answer.md`、`evidence.json`、`result.json`。评分时按 `evidence.json` 的相对路径和行号读取当前项目源码，并提供给裁判核对；只能引用业务源码或 Markdown 文档，最多 40 条、每条 80 行。评分规格是分析质量要求，不是经过人工确认的完整业务标准答案，引用片段也不能证明功能清单无遗漏。执行到评分期间请保持项目工作区不变，以免引用行号漂移。报告单独展示 Magento 分类通过率，不将其计入现有前端 ModelTest 权重。

### 批量运行

`run_benchmark.py` 会按顺序执行 `prepare`、`execute`、`evaluate`。默认读取 `tools.json`，测试其中配置的全部工具和全部 case（包括 Magento 业务题，需要上述项目目录可访问；仅测前端时加 `--category code_generation`）。未传 `--run-id` 时，脚本会先询问所选 CLI 的 Agent 与实际模型，并按 `<agent>-<model>-<时间戳>` 生成 run ID；探测失败时使用配置值或 `unknown`：

每个 Agent、每个 case 的默认执行上限为 30 分钟（1800 秒）；可用 `--timeout <秒数>` 覆盖。执行产物会记录开始时间、结束时间、实际耗时和超时上限。报告将耗时换算为独立的 0–100 分：正常完成时使用 `max(0, 100 × (1 - 实际耗时 / 超时上限))`，失败或超时记 0 分。耗时分不改变现有三项 GEval 的通过判定和 ModelTest 总分。

每个 case 执行前会打印工作目录、`[PROMPT]` 区块中的完整调用提示词，以及经过参数转义、包含 `cd` 的 zsh/bash 命令，方便复制后手动执行；这些信息也会写入 `agent.live.log`。提示词中引用的 `TASK.md` 等文件仍从对应工作区读取。

执行时会实时转发代理的 stdout/stderr，并打印当前 case 的 `agent.live.log` 绝对路径。该文件会持续写入输出，并用 `[stdout]`、`[stderr]` 标识来源；在另一个终端对打印的路径执行 `tail -f` 即可查看明细。代理尚未输出内容时，日志也不会产生新的内容。执行结束或超时后，仍按原格式写入 `agent.log` 和 `execution.json`，终端打印 `[DONE]`、状态和耗时。在 macOS/Linux 上，超时或中断会清理本次执行的进程组。已启动的旧进程不会应用这些改动。

```bash
python3 run_benchmark.py
```

只运行 Qwen Code，或进一步限制 case：

```bash
python3 run_benchmark.py --tool qwen

python3 run_benchmark.py \
  --tool qwen \
  --case draw-pelican-bicycle
```

`--tool`、`--case` 和 `--category` 均可重复传入。使用 `--run-id smoke-001` 可固定输出目录；使用 `--config custom-tools.json` 可加载其他工具配置。完成后脚本会打印 `runs/<run-id>/deepeval/`，其中每个工具有独立的 TestRun JSON 和 HTML。

### 固定 Codex 模型配置

`tools-codex-models.json` 集中维护可复现的 Codex 模型与推理强度组合：

| Tool ID | 模型 | 推理强度 |
| --- | --- | --- |
| `codex-luna-medium` | `gpt-5.6-luna` | `medium` |
| `codex-sol-high` | `gpt-5.6-sol` | `high` |
| `codex-astra-high` | `gpt-6-astra` | `high` |

只运行一个配置时，同时指定配置文件和 Tool ID，并为每次执行使用新的 run ID：

```bash
python3 run_benchmark.py \
  --config tools-codex-models.json \
  --tool codex-sol-high \
  --case draw-pelican-bicycle \
  --run-id codex-sol-high-pelican-001
```

同一次对比 Luna/medium 与 Sol/high 时重复传入 `--tool`，两套配置会使用各自隔离的 case 工作区：

```bash
python3 run_benchmark.py \
  --config tools-codex-models.json \
  --tool codex-luna-medium \
  --tool codex-sol-high \
  --case draw-pelican-bicycle \
  --run-id codex-56-pelican-compare-001
```

不传 `--tool` 会运行该配置文件中的全部 Codex 组合。默认 `tools.json` 不包含这些固定组合，因此原有批量运行行为不变；旧的 `tools-codex6-high.json` 也继续保留兼容。

### OpenCode 隔离

OpenCode 固定使用 `build` Agent，模型使用当前 OpenCode 有效配置。`tools.json` 中的 `--dir {workspace}` 设置当前 case 为工作目录，`--pure` 禁止加载 OMO 等外部插件，降低误读其他 case、历史 run 或调用额外模型的风险。如需严格比较固定模型，应在 `tools.json` 的 OpenCode 命令中显式增加 `--model <模型 ID>`：

```bash
python3 run_benchmark.py \
  --tool opencode \
  --case draw-pelican-bicycle
```

不要从 OpenCode 命令中移除 `--dir {workspace}` 或 `--pure`，否则 OpenCode 可能将仓库根目录识别为工作区，破坏 case 隔离。`prepare` 还会忽略源 case 中残留的 `result.json`、`agent.log` 和 `execution.json`，防止旧执行产物进入新 run；源 case 目录仍应保持无生成文件。

### Command Code 隔离与无头执行

Command Code 使用 `commandcode -p` 无头执行；`--output-format json` 使 CLI 以 NDJSON 输出，最终结果位于 `result.finalText`；`--verbose` 向 stderr 输出工具执行进度，二者都会实时显示并记录。基准任务需要在已准备好的隔离 case 工作区修改文件，因此执行命令保留 `--yolo`，并使用 `--no-session`、`--skip-onboarding`、`--no-auto-update`。`--config taste-learning-project=disabled` 会禁用该项目的 Taste Learning，避免基准 case 产生持久学习；该项目级设置本身会持久化。`--no-session` 不保存会话 transcript。身份探测调用 `commandcode status --json`，不发送模型请求。配置未固定模型或 effort，沿用 Command Code 当前有效配置：

```bash
python3 run_benchmark.py \
  --tool commandcode \
  --case draw-pelican-bicycle
```

### 对已生成的鹈鹕结果评分

如果已经手动使用 Agent 生成了 `index.html`，不需要再次调用被测 Agent。使用
`score_pelican.py` 录入模型、智能度和实际生成耗时，脚本会把结果复制到新的隔离
run，记录身份与耗时证据，然后调用现有固定裁判并生成 `report.md`：

```bash
python3 score_pelican.py \
  --result file:///Users/ben/Code/Personal/witch-crucible/fox-airank-deepeval/cases/code_generation/pelican_bicycle/index.html \
  --tool commandcode \
  --agent "Command Code" \
  --model qwen/qwen3.8-max-0902 \
  --intelligence unknown \
  --elapsed 34m25s
```

`--result` 同时接受普通本地路径和 `file://` URL。`--elapsed` 支持秒数、`MM:SS`、
`HH:MM:SS`、`34m25s` 或 `34分25秒`。`--model`、`--intelligence` 和
`--elapsed` 必须明确提供；`--tool`、`--agent` 默认均为 `manual`。未传
`--run-id` 时会按 Agent、模型和当前时间生成，已有非空 run 不会被覆盖。

耗时评分默认仍使用 1800 秒上限，可用 `--timeout` 调整。超过上限但已成功生成的
结果仍会进入三项 GEval 评分，只是独立耗时分为 0。脚本默认记录
`submodels_used=false`；如果生成期间实际使用了子模型，必须加
`--submodels-used`，避免伪造交付证据。原始 `index.html` 不会被修改。

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

### DeepEval 评分

`benchmark/specs.json` 登记当前 case 的实际输出文件；该清单不会复制到代理工作区。

`execute` 使用 `tools.json` 中配置的 Codex、Claude、Command Code、Qwen 或 OpenCode 无头命令执行，并在 `runs/<run-id>/<tool>/<case>/` 保存 `agent.log`、`execution.json` 和 `result.json`。三个 GEval 指标使用固定评审步骤，阈值分别为 `0.8`、`0.7`、`0.7`；一个 case 必须三项全部通过。默认不启用 DeepEval 缓存，评测子进程会清除 `CONFIDENT_API_KEY`、禁用 dotenv/历史 keyfile 和交互 inspect 提示，因此结果只写本地。

```bash
python3 run_benchmark.py --case draw-pelican-bicycle --tool codex
```

## 公平性与安全

- 各工具须使用相同 case、相同时间限制和等价的权限配置；建议固定实际使用的模型和推理等级，并在 DeepEval TestRun 的 hyperparameters 中记录版本。
- 首轮应先建立日常基线，再做候选配置对比；候选配置每次只改变一个主要变量，并使用新的 run ID。
- 日常推荐应基于重复或多 case 的稳定结果、耗时和安全边界；不得仅凭一次 run 的最高分或单个 case 的结果下结论。
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

本地鹈鹕测试默认按「模型＋智力程度（推理强度）」合并多次运行，展示组内「任务正确性」得分最高的一次；同分取最新一次，有效的 0 分优先于未评分。同一模型不同智力程度分别展示；同一模型、同一智力程度使用不同工具时仍参与同组比较，三项分数、耗时、明细及作品均来自选中的同一次运行。仍可切换到「每个配置最新一次」或「全部运行（含失败）」查看历史；其他任务保持按配置展示最新结果，原始运行记录不变。

在「配置与评分明细」中点击「展开明细分」，可在模型行下方查看三项分数、通过阈值、状态和评分理由，再次点击即可收起；「查看完整明细」仍可打开包含裁判配置与评分来源的弹窗。

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
- ModelTest 总分按当前 case 数量加权：代码修正 3、代码生成 4、逻辑分析 8。
- 原表综合分沿用 Excel 公式：人工测试总分 + ModelTest 总分 + Arena WebDev。三者量纲不同，因此只用于还原原表排序，不代表归一化能力分。
