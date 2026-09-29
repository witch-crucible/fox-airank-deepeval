# 代码代理与项目业务分析基准测试

在真实项目工作流中比较 Codex、Claude Code、Command Code、Qwen Code、OpenCode 等**代码代理工具**（而非直接调用模型 API）的实际能力，用统一 case、统一裁判和独立 run 记录回答一个具体问题：**在当前项目与真实工作流下，哪套「Agent + 模型 + 智能度」配置值得日常使用**。

## 项目简介与业务价值

### 解决什么问题

工具选型常被模型宣传、主观印象或单次演示左右。本项目把「哪个工具更强」变成可复现的评测：相同 case、相同时间上限、等价的权限配置，由固定裁判用三个固定的 GEval 指标评分，并记录每次执行使用的工具、Agent、实际模型与智能度。结论只对本次 case 集合、测试配置和对应版本负责，不构成普适的能力排名。

### 适合谁

- 需要在**日常常用配置**（而非极限配置）下选择 Agent / 模型 / 推理强度的个人与团队；
- 希望把代码代理表现接入回归门禁（用退出码判定通过率）的工程团队；
- 需要评估「只读业务分析」质量（读源码得出结论并附可复核证据链）的团队。

### 得到什么

- **可复核的评分**：三项 GEval 指标分数、理由、阈值与通过状态，全部落盘为 DeepEval TestRun；
- **可比矩阵**：跨工具 × case 的 Markdown / 自包含 HTML 报告，含通过率、三项均分、执行耗时、耗时分、token 用量与估费；
- **稳定性判断**：同一配置多次运行聚合后的结论（稳定通过 / 波动偏大 / 样本不足等），避免用单次分数下结论；
- **可回退的历史**：每次 run 保留完整隔离工作区与日志，可归档而不删除。

### 评测范围与口径

当前登记 3 个 case：

| Case ID | 分类 | 任务 |
| --- | --- | --- |
| `draw-pelican-bicycle` | `code_generation` | 从零实现「鹈鹕骑自行车处理障碍」的 TypeScript + SVG 动画 |
| `magento-lady-dior-features` | `magento_business` | 基于当前源码梳理 Lady Dior 涉及的功能清单并给出调用链证据 |
| `magento-post-shipment-exchange-intent` | `magento_business` | 追踪「发货后换货意向单」的完整逻辑链路 |

测试基调是「日常最常见配置下的实际效果」：默认应使用平时真实使用的 Agent、模型、推理强度、权限模式和超时，不临时切换到只在测试中启用的高阶模型或超高推理档位。

## 快速开始

### 前置条件

- Python 3.10+、Git；
- Node.js 18+（仅鹈鹕 case 的本地构建与公开测试需要；基准测试本体不依赖 Node）；
- 至少安装并登录一个被测代码代理 CLI（`tools.json` 默认登记 `codex`、`claude`、`commandcode`、`qwen`、`opencode`）。执行前会校验可执行文件是否在 `PATH` 上，缺失即报错；
- **统一裁判依赖本机 Codex CLI**：裁判固定使用 `gpt-5.6-sol` 与 `high` 推理强度，因此评分环节要求本机已安装并登录 `codex`。

### 1. 安装

推荐使用虚拟环境，避免与系统 Python 依赖互相影响：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

安装 `deepeval==4.2.0` 并注册 `agent-bench`、`model-dashboard`、`score-pelican` 三个命令。只有评分（`evaluate`）需要 `deepeval`；`list`、`prepare`、`report`、`stability`、`archive`、`new-case` 与本地看板不依赖它。

### 2. 确认 case 列表

```bash
python3 benchmark.py list
```

预期输出（每行：case ID、分类、标题）：

```
draw-pelican-bicycle         code_generation  绘制鹈鹕骑自行车的 SVG 动画
magento-lady-dior-features   magento_business 梳理 Lady Dior 涉及的功能清单
magento-post-shipment-exchange-intent magento_business 分析发货后换货意向单逻辑
```

### 3. 最短可运行路径：只准备隔离工作区

不启动 Agent、不评分，用于确认命令、case 配置与目录结构：

```bash
python3 benchmark.py prepare \
  --run-id smoke-prepare \
  --tool codex \
  --case draw-pelican-bicycle
```

预期：打印 `运行目录: <仓库>/runs/smoke-prepare`，并生成 `runs/smoke-prepare/codex/draw-pelican-bicycle/`，其中包含 `TASK.md`、`AGENTS.md`、`RESULT_PROTOCOL.md`、`case.json`。

### 4. 跑一次完整评测

会实际调用被测 Agent 与 Codex 裁判，耗时取决于任务（默认每个 Agent 每个 case 上限 30 分钟）：

```bash
python3 run_benchmark.py \
  --tool codex \
  --case draw-pelican-bicycle \
  --run-id smoke-codex-pelican
```

脚本按 `prepare → execute → evaluate → report` 顺序执行，结尾打印：

```
DeepEval reports: .../runs/smoke-codex-pelican/deepeval
对比报告(Markdown): .../runs/smoke-codex-pelican/report.md
对比报告(静态页): .../runs/smoke-codex-pelican/report.html
```

case 工作区位置取决于调用方式：

- 经 `run_benchmark.py` 启动（会写入身份信息）：鹈鹕 case 按身份分目录，为 `runs/<run-id>/pelican/<agent>/<model>/<intelligence>/<tool>/draw-pelican-bicycle/`；
- 直接用 `benchmark.py prepare/execute` 且未传身份：为 `runs/<run-id>/<tool>/<case-id>/`。

工作区内含被测产物、`result.json`、`agent.log`、`execution.json`、`tokens.json`。用浏览器打开 `report.html` 可查看对比矩阵。

### 5. 本地模型能力看板（可选）

```bash
python3 -m model_dashboard.server     # http://127.0.0.1:8765
```

看板是单文件 UI，依赖服务端接口取数，**必须通过该服务访问**；直接用浏览器打开 `model_dashboard/static/index.html` 会因相对路径请求失败而没有数据。

## 典型用法

### 批量对比多个工具 / 全部 case

```bash
python3 run_benchmark.py                                  # tools.json 的全部工具 × 全部 case
python3 run_benchmark.py --category code_generation        # 只跑前端 case，不触碰 Magento 项目
python3 run_benchmark.py --tool qwen --case draw-pelican-bicycle
```

`--tool`、`--case`、`--category` 均可重复传入；`--config custom-tools.json` 可加载其他工具配置。未传 `--run-id` 时脚本会先探测各 CLI 的 Agent 与实际模型，再按 `<agent>-<model>-<时间戳>` 生成 run ID，探测失败时回退配置值或 `unknown`。

注意：不带筛选条件时包含 Magento 业务题，需要 `case.json` 中登记的 `project_dir` 可访问（默认 `/Users/ben/Code/Work/cdc-dior/middleground`）。

### 固定 Codex 模型与推理强度对比

`tools-codex-models.json` 集中维护可复现的 Codex 组合：

| Tool ID | 模型 | 推理强度 |
| --- | --- | --- |
| `codex-luna-medium` | `gpt-5.6-luna` | `medium` |
| `codex-sol-high` | `gpt-5.6-sol` | `high` |
| `codex-astra-high` | `gpt-6-astra` | `high` |

```bash
# 单一配置
python3 run_benchmark.py --config tools-codex-models.json \
  --tool codex-sol-high --case draw-pelican-bicycle --run-id codex-sol-high-pelican-001

# 同一次对比两个配置（各自使用隔离的 case 工作区）
python3 run_benchmark.py --config tools-codex-models.json \
  --tool codex-luna-medium --tool codex-sol-high \
  --case draw-pelican-bicycle --run-id codex-56-pelican-compare-001
```

不传 `--tool` 会运行该文件中的全部 Codex 组合。默认 `tools.json` 不包含这些组合，原有批量运行行为不变。

### Magento 只读业务分析

两题的 `project_dir` 均为 `/Users/ben/Code/Work/cdc-dior/middleground`，执行时以该目录为 cwd，分析的是当前工作区（含未提交修改）。`prepare` 只记录项目路径、HEAD 与工作区状态，不启动 Agent、不修改项目：

```bash
python3 benchmark.py prepare --run-id magento-check \
  --category magento_business --tool codex --tool claude
```

确需执行并评分时换新 run ID：

```bash
python3 run_benchmark.py --run-id magento-business-001 \
  --category magento_business --tool codex --tool claude
```

- 每题交付 `answer.md`、`evidence.json`、`result.json`，仅写入输出目录；
- 只允许源码分析：不得修改业务源码、调用业务接口、操作数据库/缓存/队列。该约束通过任务提示与工作区 `AGENTS.md` 传递，**执行器不提供操作系统层面的只读隔离**，实际能力边界仍受各 CLI 自身权限配置控制；
- 评分时按 `evidence.json` 的相对路径与行号读取**当前项目源码**比对，因此执行到评分期间应保持项目工作区不变，避免行号漂移；
- `specs.json` 中的 `expected_answer` 是**分析质量要求，不是人工确认的完整业务标准答案**，引用片段也不能证明功能清单无遗漏；
- 报告单独展示 Magento 分类通过率，不计入 ModelTest 权重。

### 对已生成的产物单独评分

已手工用 Agent 生成 `index.html` 时，不必重跑 Agent。`score_pelican.py` 会把结果复制到新的隔离 run，记录身份与耗时证据，再调用固定裁判并生成报告：

```bash
python3 score_pelican.py \
  --result file:///Users/ben/Code/Personal/witch-crucible/fox-airank-deepeval/cases/code_generation/pelican_bicycle/index.html \
  --tool commandcode --agent "Command Code" \
  --model qwen/qwen3.8-max-0902 --intelligence unknown --elapsed 34m25s
```

`--result` 接受本地路径或 `file://` URL；`--elapsed` 支持秒数、`MM:SS`、`HH:MM:SS`、`34m25s`、`34分25秒`。`--model`、`--intelligence`、`--elapsed` 必填，`--tool`、`--agent` 默认 `manual`。默认记录 `submodels_used=false`；生成期间若实际使用了子模型，必须加 `--submodels-used`，不得伪造交付证据。原始 `index.html` 不会被修改。

### 分步运行

```bash
python3 benchmark.py prepare --run-id compare-001 --tool codex --tool claude

# 可以跳过 execute，改为手工进入 case 目录跑交互式 Agent，再执行评分
python3 benchmark.py execute --run-dir runs/compare-001 --tool codex --tool claude
python3 benchmark.py evaluate --run-dir runs/compare-001 --tool codex --tool claude
```

三个子命令都支持重复传入 `--case`/`--category` 做小规模试跑。缺失或无效的执行/结果文件会以显式证据进入裁判输入，而不是静默忽略。

### 对比报告与回归门禁

```bash
python3 benchmark.py report --run-dir runs/compare-001                    # 单 run 对比矩阵
python3 benchmark.py report --run-dir runs/compare-001 --format html      # 只出静态页
python3 benchmark.py report --history                                     # 汇总 runs/ 下全部 run

# 门禁：任一已评测工具通过率低于阈值即以退出码 1 结束
python3 benchmark.py report --run-dir runs/compare-001 --fail-under 0.8
```

- 单 run 报告写入 `runs/<run-id>/report.json`、`report.md`、`report.html`；历史报告写入 `runs/history-report.{json,md,html}`；
- `report` 只读取 TestRun JSON，不依赖 `deepeval`，可离线重新生成；`run_benchmark.py` 会在 `evaluate` 之后自动执行一次；
- `--fail-under` 不支持 `--history`；整个 run 没有任何评测结果同样视为未达标，避免「没评分」被当成通过。

### 跨 run 稳定性分析

单次分数只能说明「跑过一次」。`stability` 按「工具 + Agent + 模型 + 智能度 + case」聚合多次运行：

| 结论 | 含义 |
| --- | --- |
| 未评测 | 从未产出有效评分，先检查执行与评分链路 |
| 样本不足 | 有效样本少于 `--min-samples`（默认 3） |
| 波动偏大 | 任一指标极差超过 `--max-range`（默认 0.2） |
| 稳定失败 | 样本充足、分数一致，但每次都未达到阈值 |
| 部分失败 | 样本充足、分数一致，但存在未通过的运行 |
| 稳定通过 | 样本充足、分数一致且全部通过 |

```bash
python3 benchmark.py stability
python3 benchmark.py stability --tool codex --case draw-pelican-bicycle
python3 benchmark.py stability --min-samples 5 --max-range 0.15 --format html
```

报告写入 `runs/stability-report.{json,md,html}`，JSON 保留逐次运行明细。只有「稳定通过」才建议将配置作为日常推荐；显示「样本不足」时应先补齐重复运行次数。单个 run 的评测产物损坏时只记录告警，不中断整份报告。

### 归档历史 run

`runs/` 会持续增长。`archive` 把整个 run 目录移动到 `runs/_archive/<run-id>`，不删除任何文件，`--restore` 可移回；`_archive` 内不含 `deepeval/`，因此历史报告与稳定性分析会自动跳过已归档 run。

```bash
python3 benchmark.py archive --keep 5                 # 预演：保留最新 5 个，其余列出
python3 benchmark.py archive --keep 5 --apply         # 实际移动
python3 benchmark.py archive --older-than 30 --apply
python3 benchmark.py archive --restore old-run-001 --apply
```

不加 `--apply` 只打印计划，不改动目录。`--older-than`、`--keep`、`--run-id` 可同时使用（需同时满足）；`--restore` 不能与它们同时使用，归档目标已存在时会报错而非覆盖。

### 新增 case

`new-case` 生成 case 骨架并登记评分规格，避免手工复制目录时漏改 `specs.json`（漏登记会让评分阶段直接失败）：

```bash
python3 benchmark.py new-case \
  --id fix-pagination-window \
  --category code_correction \
  --title "修复分页窗口边界"
```

创建 `cases/code_correction/fix_pagination_window/`（`case.json` + `TASK.md` 模板），并在 `benchmark/specs.json` 登记 `{"id","category","type","actual_files"}`。`--type`（`html`/`code`/`analysis`）与 `--actual-file` 未指定时按分类推断：代码生成默认 `index.html`，代码修正默认 `solution.js`，Magento 业务题默认 `answer.md` + `evidence.json`。业务分析题用 `--project-dir <绝对路径>` 指定只读项目根目录。

全部校验在任何写入之前完成，写入失败会回滚已创建的目录；`--no-spec` 只生成目录、不登记规格（此时必须手工补登记）。生成后请补全 `TASK.md` 的需求、约束与验收点。

### 模型能力看板

`model_dashboard/` 提供本地 HTML 看板，汇总人工测试、ModelTest、Arena WebDev、AA、LLM Stats、订阅费用与本地实测结果，并支持 Legion 推荐、AI 参谋与第三方 JSON 接入；同时按固定智力基线（AA Intelligence Index 低于 DeepSeek Flash 最新版的配置判为「差」）评价配置。

```bash
python3 -m model_dashboard.server          # http://127.0.0.1:8765
python3 -m model_dashboard.server --reload # 开发模式，监听 Python 文件变化
```

完整说明见 [docs/model-dashboard.md](docs/model-dashboard.md)。

## 必要配置与注意事项

### tools.json：工具命令与占位符

`execute` 使用 `tools.json` 中的非交互命令启动各工具。命令数组支持三个占位符（按字面替换，不经过 shell 展开）：

| 占位符 | 含义 |
| --- | --- |
| `{prompt}` | 完整任务提示词 |
| `{workspace}` | 本次实际执行目录（业务题指向项目目录，其余指向 case 工作区） |
| `{output_dir}` | 结果输出目录（业务题中与 `{workspace}` 不同） |

新增工具只需追加一条配置：

```json
{"new-tool": {"command": ["实际可执行文件", "非交互参数", "{prompt}"]}}
```

`tools.json` 是可复现执行用的命令配置，不等于任何人的日常配置；正式比较前应确认其中的模型、推理强度与权限模式与实际日常使用一致。

### 隔离与安全边界

`prepare` 会为每个「工具 × case」创建独立副本，并忽略源目录中的 `_git_fixture`、`result.json`、`agent.log`、`agent.live.log`、`execution.json`。鹈鹕 case **只复制 `TASK.md` 与 `case.json`**：该题要求从零实现，仓库内已有实现不作为 fixture 提供。工作区中的 `AGENTS.md` 明确禁止读取父目录、其他 case、评分器与其他工具结果；业务题额外禁止修改源码、调用业务接口、连接数据库；鹈鹕题额外禁止使用子 Agent / 子模型。

同一仓库无法形成密码学意义上的隐藏测试；需要严格评测时，应把 `benchmark/specs.json` 与评分动作放到被测 Agent 无法访问的外部环境。代码代理会执行命令和修改文件，应在无敏感凭据、权限受限的临时环境中运行。

### 评分口径

- **三项 GEval**（`benchmark/specs.json` 登记每个 case 的实际产物，该清单不会进入工作区），阈值分别为 `0.8`、`0.7`、`0.7`，一个 case 必须三项全部通过：

| 指标 | 阈值 | 关注点 |
| --- | --- | --- |
| Task Correctness | 0.8 | 是否满足 `TASK.md` 与参考结果的行为要求（允许结构、命名、风格不同） |
| Robustness, Safety and Regression | 0.7 | 边界条件、输入不变性、编码与注入安全、错误处理、既有行为回归风险 |
| Delivery Evidence | 0.7 | `execution.json`、`result.json`、变更声明与验证记录是否真实完整一致 |

- **耗时分**：`max(0, 100 × (1 - 实际耗时 / 超时上限))`，失败或超时记 0。默认上限 1800 秒（可用 `--timeout` 覆盖）。耗时分独立展示，**不改变** GEval 通过判定与 ModelTest 总分。
- **ModelTest 总分**：按任务正确性加权（代码修正 3、代码生成 4、逻辑分析 8），Magento 业务题不参与。
- **token 用量与费用**：`execute` 结束后采集 `tokens.json`（同一份数据嵌入 `execution.json` 的 `tokens` 字段）。优先解析代理自身的结构化输出（Codex `--json`、Claude/Qwen `--output-format json`、Command Code、OpenCode `run --format json`），取不到时按执行时间窗回退扫描本机会话日志（`~/.codex/sessions/**/rollout-*.jsonl`、`~/.claude/projects/<cwd>/*.jsonl`）。字段为 `input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_creation_tokens`、`reasoning_tokens`、`total_tokens`、`cost_usd` 与来源标记 `source`（`stdout` / `log`）。模型名子串未命中定价表时 `cost_usd` 留空，不按 0 计。token 与费用仅作成本参考，**不参与**通过判定、ModelTest 或耗时评分。
- **裁判固定**：`gpt-5.6-sol` + `high`，指标版本 `2026-08-26-v1`。默认不启用 DeepEval 缓存，评测子进程会清除 `CONFIDENT_API_KEY` 并禁用 dotenv、历史 keyfile 与交互 inspect 提示，结果只写本地。

### 执行日志与超时

每个 case 执行前会打印工作目录、`[PROMPT]` 区块中的完整提示词，以及经过参数转义、包含 `cd` 的 zsh/bash 命令（便于复制后手工执行），这些内容同时写入 `agent.live.log`。执行期间实时转发 Agent 的 stdout/stderr，并用 `[stdout]`、`[stderr]` 标识来源；在另一个终端 `tail -f` 打印出的日志路径即可查看明细。结束或超时后按原格式写入 `agent.log`、`execution.json`、`tokens.json`，终端打印 `[DONE]` 与状态、耗时。在 macOS/Linux 上，超时或中断会清理本次执行的进程组。

### 工具特有约束

- **OpenCode**：固定使用 `build` Agent，模型沿用当前 OpenCode 有效配置。`--dir {workspace}` 把当前 case 设为工作目录，`--pure` 禁止加载 OMO 等外部插件，降低误读其他 case、历史 run 或调用额外模型的风险。**不要移除这两个参数**，否则 OpenCode 可能把仓库根目录识别为工作区，破坏 case 隔离。需要严格比较固定模型时，在 `tools.json` 中显式追加 `--model <模型 ID>`。
- **Command Code**：使用 `commandcode -p` 无头执行，`--output-format json` 输出 NDJSON（最终结果在 `result.finalText`），`--verbose` 向 stderr 输出进度。基准任务需要在隔离工作区内改文件，故保留 `--yolo`，并使用 `--no-session`、`--skip-onboarding`、`--no-auto-update`。`--config taste-learning-project=disabled` 会禁用项目的 Taste Learning，但**该项目级设置本身会持久化**；若要求完全不写项目配置，请改用 Codex/Claude 或另行调整工具配置。身份探测调用 `commandcode status --json`，不发送模型请求。为了可复现，当前配置显式指定 `--model qwen/qwen3.8-max-0902`，未固定 effort，沿用当前有效值。
- **Codex / Claude**：默认配置使用 `--add-dir {output_dir}` 提供独立结果目录访问；自定义配置同样需要允许该目录。

### 公平性与安全

- 各工具须使用相同 case、相同时间限制和等价的权限配置；固定实际使用的模型与推理等级，并在 TestRun 的 hyperparameters 中记录版本。
- 先建立日常基线，再做候选配置对比；候选每次只改变一个主要变量，并使用新的 run ID。**不得**在已执行过的 case 工作区上继续测试另一模型。
- 日常推荐应基于重复运行或多 case 的稳定结果，不得仅凭单次最高分或单个 case 下结论。

### 验证项目自身

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q benchmark model_dashboard tests run_benchmark.py
```

鹈鹕 case 自带的公开测试（Playwright + Chromium；用于验证测试本身与本地实现，不参与 Agent 评分）。需要网络安装依赖，若本机没有可用的 Chromium，先执行 `npx playwright install chromium`：

```bash
cd cases/code_generation/pelican_bicycle
npm ci
npm test        # 等价于 npm run build && node public-test.mjs
```

实测输出为 `10/10 项通过，截图见 verification/`（截图目录在用后自行清理）。

`dist/`、`node_modules/`、`verification/` 均被 `.gitignore` 忽略；用例目录内随仓库提交的 `index.html` 是仓库内的实现样例，`prepare` 不会把它复制到被测工作区。
