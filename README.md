# 前端代码代理能力基准测试

该项目比较 Codex、Claude Code、Qwen Code、OpenCode、Qoder 等代码代理工具在真实项目工作流中的能力，而不是直接调用模型 API。

评测覆盖三类能力，共 13 个前端 JavaScript case：

- `logic_analysis`（7 个）：从零散业务沟通还原规则、检查 commit 声明与 diff 是否一致、对照注释发现实现偏差、从结果数据反推过程缺陷、从异步竞态合约发现实现偏差、检查访问策略声明与实现是否一致、从购物车事件日志反推乱序缺陷。
- `code_correction`：修复购物车金额、查询参数、分页边界缺陷。
- `code_generation`：实现商品筛选、分页 reducer、安全商品卡片。

每个工具得到完全独立的 case 副本。工具读取 `TASK.md`、修改文件、执行公开测试并生成 `result.json`；评分器再运行不会复制到工作区的检查。功能检查占 90 分，结果文件协议占 10 分。

## 前置条件

- Python 3.10+
- Node.js 18+
- 待测试代码代理 CLI 已安装并已登录

当前 `tools.json` 已配置 Codex、Claude Code、Qwen Code、OpenCode。Qoder 安装后，按其当前非交互命令追加配置即可：

```json
{
  "qoder": {
    "command": ["实际可执行文件", "非交互参数", "{prompt}"]
  }
}
```

命令数组支持 `{prompt}` 和 `{workspace}` 占位符，不经过 shell 展开。

## 标准流程

查看 case：

```bash
python3 benchmark.py list
```

为多个工具准备隔离副本：

```bash
python3 benchmark.py prepare \
  --run-id compare-001 \
  --tool codex \
  --tool claude-code \
  --tool opencode
```

依次执行代理工具：

```bash
python3 benchmark.py execute \
  --run-dir runs/compare-001 \
  --tool codex \
  --tool claude-code \
  --tool opencode
```

评分并生成报告：

```bash
python3 benchmark.py grade \
  --run-dir runs/compare-001 \
  --tool codex \
  --tool claude-code \
  --tool opencode
```

报告同时写入 `runs/compare-001/report.json` 和 `runs/compare-001/report.html`。HTML 报告可直接用浏览器打开，对比工具总分、三类能力分数、每个 case 得分及协议/功能检查详情。每个 case 下还会保留 `agent.log` 与 `execution.json`，用于检查代理执行过程、退出码和耗时。

三个命令都支持重复传入 `--case` 或 `--category`，便于小规模试跑：

```bash
python3 benchmark.py prepare --run-id smoke --tool codex --case fix-cart-total
python3 benchmark.py execute --run-dir runs/smoke --tool codex --case fix-cart-total
python3 benchmark.py grade --run-dir runs/smoke --tool codex --case fix-cart-total
```

`prepare` 后也可以不使用 `execute`，而是手工进入各 case 目录启动交互式代码代理。只要代理最终生成合法 `result.json`，就可以统一执行 `grade`。

## 公平性与安全

- 各工具必须使用相同 case、相同时间限制和等价的权限配置。
- 建议固定各工具实际使用的模型和推理等级，并在报告外另行记录版本。
- 工作区内的 `AGENTS.md` 明确禁止读取父目录和评分器；同一仓库无法形成密码学意义上的隐藏测试，严格评测可将 `benchmark/specs.json` 和评分动作放到代理无法访问的外部环境。
- 代码代理会执行命令和修改文件。应在无敏感凭据、权限受限的临时环境中运行。

## 验证项目自身

参考解会完整跑过 13 个 case 的评分规则：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q benchmark tests
```
