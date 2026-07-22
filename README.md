# 前端代码代理能力基准测试

比较 Codex、Claude Code、Qwen Code、OpenCode、Qoder 等代码代理工具在真实项目工作流中的能力，而非直接调用模型 API。

共 13 个前端 JavaScript case，分三类：

- `logic_analysis`（7 个）：从沟通记录、diff、注释、日志等零散材料反推业务规则或实现缺陷（含竞态、访问策略漂移、事件乱序等场景）。
- `code_correction`（3 个）：修复购物车金额、查询参数、分页边界缺陷。
- `code_generation`（3 个）：实现商品筛选、分页 reducer、安全商品卡片。

每个工具在独立副本中读取 `TASK.md`、修改文件、生成 `result.json`；评分器再运行不会复制到工作区的隐藏检查。功能检查占 90 分，结果文件协议占 10 分。

## 前置条件

- Python 3.10+、Node.js 18+
- 待测试代码代理 CLI 已安装并登录

`tools.json` 已配置 Codex、Claude Code、Qwen Code、OpenCode。新增工具只需按其非交互命令追加一条配置，命令数组支持 `{prompt}`、`{workspace}` 占位符（不经过 shell 展开）：

```json
{"qoder": {"command": ["实际可执行文件", "非交互参数", "{prompt}"]}}
```

## 使用

```bash
python3 benchmark.py list                                              # 查看 case

python3 benchmark.py prepare --run-id compare-001 \
  --tool codex --tool claude-code --tool opencode                      # 准备隔离副本

python3 benchmark.py execute --run-dir runs/compare-001 \
  --tool codex --tool claude-code --tool opencode                      # 依次执行代理工具

python3 benchmark.py grade --run-dir runs/compare-001 \
  --tool codex --tool claude-code --tool opencode                      # 评分并生成报告
```

报告写入 `runs/compare-001/report.json` 与 `report.html`（可直接用浏览器打开），对比工具总分、三类能力分数、每个 case 得分及协议/功能检查详情；每个 case 目录下还保留 `agent.log` 与 `execution.json`，记录执行过程、退出码和耗时。

三个命令都支持重复传入 `--case`/`--category` 做小规模试跑。`prepare` 后也可以不用 `execute`，改为手工进入 case 目录跑交互式代理——只要最终生成合法 `result.json`，就能统一执行 `grade`。

## 公平性与安全

- 各工具须使用相同 case、相同时间限制和等价的权限配置；建议固定实际使用的模型和推理等级，并在报告外另行记录版本。
- 工作区内 `AGENTS.md` 明确禁止读取父目录和评分器；同一仓库无法形成密码学意义上的隐藏测试，严格评测可将 `benchmark/specs.json` 和评分动作放到代理无法访问的外部环境。
- 代码代理会执行命令和修改文件，应在无敏感凭据、权限受限的临时环境中运行。

## 验证项目自身

参考解会完整跑过 13 个 case 的评分规则：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q benchmark tests
```
