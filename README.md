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

需要本地构建或运行鹈鹕案例的公开测试时，先安装锁定的前端依赖；构建产物、依赖目录和验证截图不会纳入版本管理：

```bash
cd cases/code_generation/pelican_bicycle
npm ci
npm test
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

`report` 子命令默认同时生成 Markdown 与**自包含静态页面**（单 run 为 `report.html`，历史为 `history-report.html`），静态页内联 CSS、无外部依赖，可直接用浏览器打开查看对比矩阵；可用 `--format md|html|both` 只输出指定格式：

```bash
python3 benchmark.py report --run-dir runs/compare-001                    # 同时生成 report.md 与 report.html
python3 benchmark.py report --run-dir runs/compare-001 --format html      # 只生成静态页面
python3 benchmark.py report --history --format html                      # 历史对比只生成静态页面
```

`run_benchmark.py` 批量流程会在 `evaluate` 之后自动执行 `report`，结束后同时打印 DeepEval 原始报告和对比报告路径。

需要把对比报告当作回归门禁时，用 `--fail-under` 指定通过率下限（0–1）。任一已评测工具的通过率低于该值时，报告照常生成，但命令以退出码 1 结束；整个 run 没有任何评测结果同样视为未达标，避免“没评分”被当成通过。该参数不支持 `--history` 模式。

```bash
python3 benchmark.py report --run-dir runs/compare-001 --fail-under 0.8
```

### 跨 run 稳定性分析

单次分数只能说明“跑过一次”，不足以支撑“该配置适合日常使用”。`stability` 按「工具 + Agent + 模型 + 智能度 + case」聚合同一配置的多次运行，输出样本数、三项指标的均值与极差、标准差、通过率和耗时，并按统一口径给出结论：

| 结论 | 含义 |
| --- | --- |
| 未评测 | 从未产出有效评分，先检查执行与评分链路 |
| 样本不足 | 有效样本少于 `--min-samples`（默认 3） |
| 波动偏大 | 任一指标极差超过 `--max-range`（默认 0.2） |
| 稳定失败 | 样本充足、分数一致，但每次都未达到阈值 |
| 部分失败 | 样本充足、分数一致，但存在未通过的运行 |
| 稳定通过 | 样本充足、分数一致且全部通过 |

判定顺序从“证据不足”到“证据可信”：先排除没有评分或样本不足，再判断波动，最后才解释通过与失败，避免用不稳定的分数下稳定结论。

```bash
python3 benchmark.py stability                                    # 扫描 runs/ 下全部 run
python3 benchmark.py stability --tool codex --case draw-pelican-bicycle
python3 benchmark.py stability --min-samples 5 --max-range 0.15 --format html
```

报告写入 `runs/stability-report.json`、`stability-report.md` 和 `stability-report.html`（`--format md|html|both`）。JSON 同时保留每一组的逐次运行明细，便于人工核对；明细表下方只展开需要关注的分组。某个 run 的评测产物损坏时只记录告警，不中断整份报告。只有达到「稳定通过」才建议把该配置作为日常推荐；显示「样本不足」时应先补齐重复运行次数，而不是直接下结论。

### 归档历史 run

每个 run 都保留完整的隔离工作区、代理日志和评测产物，`runs/` 会持续增长。`archive` 把整个 run 目录移动到 `runs/_archive/<run-id>`：不删除任何文件，随时可用 `--restore` 移回；`_archive` 自身不含 `deepeval/`，因此历史报告与稳定性分析会自动跳过已归档的 run。

```bash
python3 benchmark.py archive --keep 5                 # 预演：保留最新 5 个，其余列出
python3 benchmark.py archive --keep 5 --apply         # 真正移动
python3 benchmark.py archive --older-than 30 --apply
python3 benchmark.py archive --run-id old-run-001 --apply
python3 benchmark.py archive --restore old-run-001 --apply
```

不加 `--apply` 时只打印将要移动的 run、占用空间和原因，不会改动任何目录。`--older-than`、`--keep` 和 `--run-id` 可同时使用（需同时满足）；`--restore` 不能与它们同时使用。归档目标已存在时会报错，不会覆盖已有数据。

### 新增 case

`new-case` 生成 case 目录骨架并登记评分规格，避免手工复制目录时漏改 `benchmark/specs.json`（漏登记会让评分阶段直接失败）：

```bash
python3 benchmark.py new-case \
  --id fix-pagination-window \
  --category code_correction \
  --title "修复分页窗口边界"
```

会创建 `cases/code_correction/fix_pagination_window/`（`case.json` + `TASK.md` 模板），并在 `benchmark/specs.json` 登记 `{"id","category","type","actual_files"}`。`--type`（`html`/`code`/`analysis`）和 `--actual-file` 未指定时按分类推断：代码生成默认 `index.html`，代码修正默认 `solution.js`，Magento 业务题默认 `answer.md` 与 `evidence.json`。业务分析题用 `--project-dir <绝对路径>` 指定只读项目根目录。

全部校验在任何写入之前完成；写入失败会回滚已创建的目录，不留下无法评分的半截 case。加 `--no-spec` 只生成目录、不登记规格，此时需手工补登记，否则评分会失败。生成后请补全 `TASK.md` 的需求、约束和验收点，必要时在 `specs.json` 中补充 `expected_answer`。

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

- “同步 Arena 全榜”分页读取 [Arena WebDev 榜单](https://arena.ai/leaderboard/code/webdev) 的官方 `webdev/latest` Overall 快照，保存名次、Score、输入/输出 Price $/M 和官方来源。价格优先读取 Arena 页面及 LMArena 官方价格目录；Cloudflare 阻止页面读取或目录未覆盖当前模型时，横向总表会明确使用已匹配 AA 服务商配置的价格作为参考，不伪装成 Arena 原始字段。
- “同步 AA Model 全榜”读取 [Artificial Analysis Models](https://artificialanalysis.ai/models) 的公开加密 manifest，保存完整模型榜、Intelligence、Speed、Cost per Intelligence Index Task、Terminal-Bench 4.0 和服务商配置。解码使用 Node.js 内置加密与 gzip 能力，不需要 AA API key。
- “同步 AA Agent 全榜”读取 [Artificial Analysis Coding Agents](https://artificialanalysis.ai/agents/coding-agents) 的完整榜单，保存 Coding Agent Index、DeepSWE v1.1、Terminal-Bench 4.0、SWE-Atlas-QnA、Time per Task、Cost per Task 及底层模型标识；旧版字段继续兼容读取。
- “同步 LLM Stats 全榜”读取 [LLM Stats](https://llm-stats.com/) 官网使用的公开 `general` 指数榜单及 Coding 分项，保存完整排名、官方模型 ID、组织、14 天排名变化和参与评测数。

每个来源的成功同步都会保存不可变 SQLite 快照，默认对比最近两次，也可选择任意历史批次。页面分别标记名次和指标变化、新上榜、退出榜单及版本不可比；同步失败不会推进该来源的历史基线。

Model 三方聚合分先在各来源当前完整快照内按原始得分做 0–100 min-max 归一化，再按默认的 Artificial Analysis 50%、Arena 35%、LLM Stats 15% 加权。顶部「配置」页面可以修改这三个来源的权重，单项允许为 0%，但合计必须为 100%；保存后持久化到本地 SQLite 并立即重新计算聚合分、排名和来源列顺序。每行按“模型版本 + 智能度（推理强度）”独立匹配与算分，中英文强度别名会统一，但 High、XHigh、Max、Ultra 等配置不会混合。没有披露智能度的成绩单列为“未注明”，不会填入已知智能度的配置。只有同模型、同智能度在同一来源存在多条记录时，才选择官方名次最高的一条参与聚合，其他记录仍可展开检查。权重大于 0 的来源缺失时不计算聚合分，缺失值不会按 0 分或重新分配权重；设为 0% 的来源不再作为完整性门槛。本地实测分按任务正确性 70%、稳健与安全 20%、交付证据 10% 计算；同任务重复运行先平均，再跨任务平均。实战综合分采用同模型、同智能度的三方聚合分 70% + 本地实测分 30%，只有共同测试集齐全且每题至少完成 3 次时进入正式排名，覆盖不足时仅展示试算值。

Model 榜单支持“纯 Artificial Analysis”模式。开启后只展示 AA 已发布的模型与智能度配置，按 AA 官方名次排序，并直接展示 Intelligence、Speed、Terminal-Bench 4.0、服务商配置和成本；Arena、LLM Stats 与三方聚合分不参与该视图。该模式可继续叠加搜索和“仅看 Legion”筛选，切回后恢复原三方综合榜单。

直接启动（无需安装额外依赖）：

```bash
python3 -m model_dashboard.server
```

开发时可用 `--reload` 监听 `model_dashboard/**/*.py` 变更并自动重启（不监听 `data.local.json`，避免写入数据时误重启）：

```bash
python3 -m model_dashboard.server --reload
```

浏览器打开 <http://127.0.0.1:8765>。新增或导入的数据默认写入被 Git 忽略的 `var/sqlite/fox-airank-deepeval.db`；首次启动会从已有的 `model_dashboard/data.local.json` 自动导入，原 JSON 文件保留。可通过 `--data` 指定 SQLite 文件路径；静态页面每次请求都会重新读取，改 `static/index.html` 后刷新浏览器即可，无需重启。

数据缓存：本地实测结果（`/api/local-benchmarks`、模型榜单与 AI 分析读取的同一份数据）缓存在 SQLite 中，页面不再每次请求都重扫 `runs/`；当 `runs/` 或 `cases/*/*/case.json`、`TASK.md` 的文件指纹与缓存不一致时视为过期。三方榜单沿用已有 SQLite 快照，最近一次同步超过 `--cache-max-age-hours`（默认 24，必须大于 0）即视为过期。页面始终展示缓存数据（prompt-only）：有过期来源时顶部显示提示条，点击「立即更新」或「更多 → 缓存状态」中的「更新」手动刷新，不会自动同步；「刷新本地结果」按钮也会先重建本地缓存再重新读取。

Vibe Coding Legion 首页的「AI 参谋：总结与推荐」面板可输入使用需求，点击生成模型数据总结、场景推荐、推荐依据和限制。它调用 [SenseNova Token Plan](https://www.sensenova.cn/token-plan) 的 OpenAI 兼容接口（`POST https://token.sensenova.cn/v1/chat/completions`），与 DeepEval 评测和本机 Codex 登录状态无关。请求体只带当前指标快照、需求文本与输出 JSON Schema；仅手动点击生成时调用模型，普通刷新只读取最近一次成功结果。旧链接 `/#ai-insights` 仍然有效：会打开 Legion 首页并展开、定位到该面板。

密钥只从环境变量读取，不写入数据文件，也不在页面或接口中返回。启动看板前设置：

```bash
SENSENOVA_API_KEY=... \
MODEL_DASHBOARD_AI_BASE_URL=https://token.sensenova.cn/v1 \
MODEL_DASHBOARD_AI_MODEL=sensenova-6.8-flash-lite \
MODEL_DASHBOARD_AI_TIMEOUT=180 \
python3 -m model_dashboard.server
```

- `SENSENOVA_API_KEY`：必填，缺失时面板显示「未配置 Key」且生成按钮不可用。
- `MODEL_DASHBOARD_AI_BASE_URL`：默认 `https://token.sensenova.cn/v1`，必须为 HTTPS（本机调试可用 `localhost` 的 HTTP）。
- `MODEL_DASHBOARD_AI_MODEL`：默认 `sensenova-6.8-flash-lite`。
- `MODEL_DASHBOARD_AI_TIMEOUT`：默认 180 秒，取值 10 至 1800。

未配置密钥时页面仍可查看已保存的分析。接口错误只回传分类提示（密钥无效、配额超限、HTTP 状态码、网络超时），不会把响应体或密钥透传到页面。

AI 接收当前未归档模型的指标、来源时间、按配置汇总的本地实测及覆盖信息，不发送原始日志、工作区代码或备注。缺失指标不补零，不混用不同推理强度或 Agent 的成绩；每条推荐的配置身份和引用指标由服务端从输入快照回填。文字结论仍是 AI 推断，页面提供原始证据供核对。超过单次输入上限时明确报错，不静默裁剪榜单。

最近一次成功分析单独保存在当前 SQLite 的 `ai_insights` 表中，记录需求、分析模型、生成时间和数据摘要；不会修改 Legion 手工推荐、发布版本或评分。数据变化后页面提示结果过期，生成失败保留上一次结果；同一服务进程同时只接受一次生成。接口为 `GET /api/ai-insights`（状态和结果）与 `POST /api/ai-insights`（JSON 请求体 `{"goal":"优先比较代码审查质量与成本"}`，空需求使用默认场景）。

顶部导航按用途拆分：「本地实测」展示本地运行评分、作品与人工能力剖面；「Agent 三方榜单」按 Agent 聚合 AA 配置，展开后展示各模型与智能度的 Coding Agent Index、成本、耗时及底层模型对照，Coding Agent Index 可直达官方指标区块，模型基线仅展示可比的 Terminal-Bench 4.0 分数并可跳转到对应模型页；「Model 三方榜单」横向合并 Arena、AA Models、LLM Stats 和本地实测；「Agent 使用人数」「订阅费用快照」和「配置」各自独立成页。Agent 榜单默认按组内最佳 Coding Agent Index 排序，也可切换为按组内最佳同配置 Terminal-Bench 4.0 提升效果排序；两种排序下分组摘要行都同时给出组内最佳 Coding Agent Index 原始分与组内最佳同配置 Terminal-Bench 4.0 提升（提升前 → 提升后，两个分数与提升幅度同源可核对），两项可能取自不同模型与智能度配置，因此各自标注所属配置；分数均可点击跳转 Artificial Analysis（基线缺失时只省略「提升前 / 提升后」而不改写提升幅度）；无有效值的 Agent 排在末尾且空白不按 0 分处理。费用快照拆成「Agent Plan」「Code Plan」「Token Plan」三个区块：前两者对应 IDE / Agent 与 CLI / Coding 形态的订阅档位，Token Plan 对应按 token / Credits 额度计费的档位；页内顶部提供章节导航，锚点为 `/#pricing-agent`、`/#pricing-code` 与 `/#pricing-token`；每个区块只展示已录入该形态价格的工具，全部为空时提示待补录。规范字段为 `agent_plans`、`coding_plans` 与 `token_plans`；旧 `ide_plans`、`code_plans` 和 `plans` 数据继续兼容读取。档位可带 `detail` 小字（如额度说明），与月费同行展示。

费用快照页最前面新增「统一坐标系 · 性价比」区块（章节 key 为 `value`，锚点 `/#pricing-value`）。它把各档位月费折算到可比口径，用于跨工具横向比较：

- 主坐标 `¥ / 百万 token`。档位需提供 `included_tokens`（月度额度，token）与 `token_basis`（折算依据原文，展示在该行下方）。
- 副坐标 `¥ / 美元额度`（`¥/USD`）。档位只提供 `included_usd_credit`（月度额度，美元）而没有 `included_tokens` 时使用，按 `price_cny_month / included_usd_credit` 计算。
- 两个坐标系**不做跨口径换算**：只有美元额度、未公布 token 数的档位记为 `—`，并在区块底部汇总「不做估算」的档位数量与原因，避免把「只公布美元额度」误算成「便宜」。
- 主表按 `¥/Mtok` 升序并给出「相对最优」倍数，最低值一行高亮；档位标注 `calibration_note`（如 Credits 折算口径与社区实测差异）会显示在工具卡片上，提醒不要只取表中最优值。
- 汇率沿用快照原值 1 USD = 6.75 CNY（`USD_TO_CNY`），前端 `planCnyPerMtok()` 与后端 `pricing.value_overview()` 口径一致。

每条条目都记录原始地址。条目可带 `sources` 数组（旧的 `official_url` 继续作为第一个来源回退读取），元素形如 `{"label": "GLM Coding Plan 订阅页", "url": "https://z.ai/subscribe", "snapshot_at": "2026-09-27", "status": "ok"}`；缺失 `label` 时用 URL 兜底。工具卡片底部渲染「采集日期 · 各来源链接 + 状态徽章 · ↻ 刷新」，点击刷新会重新抓取这些地址。来源状态：`ok`（正文 ≥ 200 字符）、`partial`（疑似纯 JS 渲染，正文过短）、`blocked`（命中反爬特征串）、`error`（抓取异常，附 `http_error`）。刷新采用内容指纹（归一化空白后取 sha256 前 16 位）比对：指纹变化才推进条目的 `snapshot_at` 与该来源的 `snapshot_at`，正文无变化时不推进，避免把「抓到了页面」误当成「价格已更新」。抓取默认沿用环境变量中的代理，代理 tunnelling 失败（如 `Tunnel connection failed`）时自动回退直连，而 403 / 404 等 4xx 属于对方明确应答，不再回退。相关接口为 `GET /api/pricing/sources`（汇总全部条目的来源记录）与 `POST /api/pricing/refresh`（请求体 `{"tool": "Z AI"}` 可只刷指定工具，返回 `{checked, updated, blocked, error, sources}`）。

页面可通过 `/#dashboard`、`/#agent-reference`、`/#reference`、`/#agent-usage`、`/#pricing`、`/#pricing-value`、`/#pricing-agent`、`/#pricing-code`、`/#pricing-token`、`/#settings` 直接打开，支持刷新和浏览器前进/后退；旧章节链接（含 `/#section-pricing-value`）继续进入迁移后的所属页面。

「Vibe Coding Legion」是默认页面，顶部导航另有独立的「Legion 日志」页面；两页分别使用本地打包的军团出征图和技能冷却图，不依赖外部图片服务。Legion 页面先按主用途分组，再在用途内按建议中的 Agent/工具聚合；工具为空时回退使用 Agent Plan 或 Coding Plan 作为 Agent 名。存在同名费用快照的 Agent 分组会显示「订阅费用」链接，点击后进入费用页并定位、高亮对应工具；没有匹配费用记录时不显示空链接。默认用途类型为 `Ask`、`Plan`、`Build`、`Review` 和 `Ship`，每条建议的主用途与副用途都支持多选，副用途仅作为浅色标签展示，不建立页面分组。每张配置卡片按模型名称和工具匹配本地打包的简化家族标记，覆盖 GPT/OpenAI、Claude/Opus、Grok、DeepSeek、Cursor/Composer、Qwen、Kimi 与 Gemini，未知模型回退到模型首字符。只有主用途分组中的卡片支持在右上角用空心/实心星星执行“设为核心 / 取消核心”；核心卡片同时使用金色边框和浅色背景高亮，编辑弹窗中的复选框仍可维护同一字段。点击「编辑建议」可按模型、工具或推理强度搜索配置，复制已有配置，并用固定底部操作区保存；关闭有未保存修改的编辑器时会二次确认。用途类型支持 1 至 20 个逗号分隔值，并提供即时数量、重复与长度校验；每条建议可以分别多选主用途、副用途及修改说明，选择同一类型时会自动从另一用途角色移除。默认不自动标记任何配置。每条建议仍按工具、模型和推理强度优先匹配本地实测结果，展示该配置任务正确性最佳一次运行的三项能力分；没有本地结果时再匹配模型数据，仍无记录或尚未评分时明确显示为空，不按 0 分处理。模型必填，其他字段可留空；主用途留空时，Agent Plan 优先归入 `Plan`、Coding Plan 优先归入 `Build`，对应类型不存在时归入配置列表第一项。用途说明留空时按 Plan 归属和推理强度显示中性默认说明。保存后写入同一本地数据文件，刷新页面或重启服务后保留；取消不会保存。点击「发布 Vibe Coding Legion」会把已保存草稿固化为不可变版本，发布历史在「Legion 日志」页保留完整快照、SHA-256、发布说明和新增/更新/移除差异；内容未变化时不会重复生成版本。旧数据会把原用途数组的第一项读取为主用途、其余项读取为副用途，并继续提供旧字段兼容视图，但不会因读取而写回。建议独立于评分、费用和榜单同步，不参与排名计算。

星标实际按“用途 + 建议条目”独立保存；同一建议属于多个主用途时，只高亮用户点选的那个用途条目。旧数据中的整条 `is_core=true` 会兼容映射为该建议的全部主用途，并继续输出布尔别名供旧客户端读取。

Agent 与 Model 三方榜单都会高亮匹配的 Legion 配置并显示空心 / 实心星标及具体用途，支持“仅看 Legion”筛选。Model 按模型与智能度匹配；Agent 还要求工具一致，不借用其他 Agent 的成绩。Agent 聚合行汇总组内收藏状态、主用途和弱化展示的副用途，展开后的配置仍保留各自的精确星标与用途；启用“仅看 Legion”时只展示匹配配置，并仅用这些配置计算组内最佳排序值。保存建议或切换核心星标后，榜单同步更新。缺失的 Legion 配置会作为补充行展示已有的同配置模型数据，不伪造 Agent 分数或官方排名。点击“补齐 Legion 数据”会仅对有缺失项的来源重新获取完整官方目录并融合，保持归一化使用完整来源快照；单一来源失败时保留该源原有数据并继续其他来源。补拉后仍未发布的配置分数保持为空，且不会使用其他智能度补位。

本地鹈鹕测试默认按「模型＋智力程度（推理强度）」合并多次运行，展示组内「任务正确性」得分最高的一次；同分取最新一次，有效的 0 分优先于未评分。同一模型不同智力程度分别展示；同一模型、同一智力程度使用不同工具时仍参与同组比较，评分表中的三项分数、耗时和明细来自选中的同一次运行。作品区只预览带有完整单文件 HTML 的运行；当评分表选中的运行没有可预览作品时，作品区会在当前筛选范围内回退到另一条可预览历史运行，并标明自己的 `run_id`、得分（未评分会明确显示）和耗时。仍可切换到「每个配置最新一次」或「全部运行（含失败）」查看历史；其他任务保持按配置展示最新结果，原始运行记录不变。

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

- 人工测试总分仍按兼容字段 Skill 调用、逻辑梳理分（原代码评审）、逻辑分析、功能修复四项之和计算；“本地实测”的人工能力剖面只展示逻辑梳理分，并把鹈鹕测试的任务正确性展示为功能实现分。
- ModelTest 总分按当前 case 数量加权：代码修正 3、代码生成 4、逻辑分析 8。
- 原表综合分沿用 Excel 公式：人工测试总分 + ModelTest 总分 + Arena WebDev。三者量纲不同，因此只用于还原原表排序，不代表归一化能力分。
