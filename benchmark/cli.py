from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = "阅读 TASK.md，独立完成任务并执行必要验证。最后必须按 TASK.md 要求生成 result.json。"


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    source: Path


def load_cases() -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for path in sorted((ROOT / "cases").glob("*/*/case.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        case = Case(data["id"], data["category"], data["title"], path.parent)
        if case.id in seen:
            raise ValueError(f"重复的 case id: {case.id}")
        cases.append(case)
        seen.add(case.id)
    if not cases:
        raise ValueError("没有找到 case")
    return cases


def select_cases(cases: list[Case], ids: list[str], categories: list[str]) -> list[Case]:
    selected = [case for case in cases if not categories or case.category in categories]
    if ids:
        requested = set(ids)
        selected = [case for case in selected if case.id in requested]
        missing = requested - {case.id for case in selected}
        if missing:
            raise ValueError(f"找不到 case: {', '.join(sorted(missing))}")
    if not selected:
        raise ValueError("筛选条件没有匹配任何 case")
    return selected


def load_tool_config(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for name, config in data.items():
        command = config.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError(f"工具 {name} 的 command 必须是非空数组")
    return data


def preflight_tools(
    configs: dict[str, dict[str, Any]],
    tools: Sequence[str],
    workspace: str = "{workspace}",
) -> None:
    for tool in tools:
        if tool not in configs:
            raise ValueError(f"工具配置不存在: {tool}")
        command = configs[tool]["command"]
        if any(not isinstance(token, str) for token in command):
            raise ValueError(f"工具 {tool} 的 command 必须是字符串数组")
        executable = command[0]
        if shutil.which(executable) is None:
            raise ValueError(f"找不到工具命令: {executable}")
        try:
            [token.format(workspace=workspace, prompt=DEFAULT_PROMPT) for token in command]
        except (KeyError, ValueError) as error:
            raise ValueError(f"工具 {tool} 的命令占位符无效: {error}") from error


def prepare(run_dir: Path, tools: list[str], cases: list[Case]) -> None:
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"运行目录已存在且非空: {run_dir}")
    for tool in tools:
        for case in cases:
            target = run_dir / tool / case.id
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                case.source,
                target,
                ignore=shutil.ignore_patterns("result.json", "agent.log", "execution.json"),
            )
            (target / "AGENTS.md").write_text(
                "# 评测工作区规则\n\n"
                "只读取和修改当前目录，不得查看父目录、其他 case、评分器或其他工具结果。\n"
                "严格完成 TASK.md；不得修改 case.json；必须生成 result.json。\n",
                encoding="utf-8",
            )
            (target / "RESULT_PROTOCOL.md").write_text(
                "# 结果文件协议\n\n完成任务后，在当前目录生成 `result.json`：\n\n"
                "```json\n{\n"
                f"  \"case_id\": \"{case.id}\",\n"
                "  \"status\": \"completed\",\n"
                "  \"summary\": \"实际完成内容\",\n"
                "  \"changed_files\": [\"实际修改或新增的相对路径\"],\n"
                "  \"verification\": [\"实际执行的验证命令或检查\"]\n"
                "}\n```\n\n不得伪造未执行的验证。逻辑题和手动测试题还必须保留 TASK.md 要求的 `answer` 字段。\n",
                encoding="utf-8",
            )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tools": tools,
        "cases": [case.id for case in cases],
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def execute(run_dir: Path, tools: list[str], cases: list[Case], config_path: Path, timeout: int) -> None:
    configs = load_tool_config(config_path)
    preflight_tools(configs, tools)
    workspaces: dict[tuple[str, str], Path] = {}
    for tool in tools:
        for case in cases:
            workspace = (run_dir / tool / case.id).resolve()
            if not workspace.is_dir():
                raise ValueError(f"case 工作区不存在: {workspace}")
            workspaces[(tool, case.id)] = workspace

    for tool in tools:
        for case in cases:
            workspace = workspaces[(tool, case.id)]
            command = [
                token.format(workspace=str(workspace), prompt=DEFAULT_PROMPT)
                for token in configs[tool]["command"]
            ]
            print(f"[RUN] {tool} / {case.id}", flush=True)
            started = time.monotonic()
            try:
                result = subprocess.run(
                    command,
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                status = "completed" if result.returncode == 0 else "failed"
                returncode = result.returncode
                stdout, stderr = result.stdout, result.stderr
            except subprocess.TimeoutExpired as error:
                status, returncode = "timeout", None
                stdout = error.stdout or ""
                stderr = error.stderr or ""
            elapsed = round(time.monotonic() - started, 3)
            (workspace / "agent.log").write_text(
                f"command={json.dumps(command, ensure_ascii=False)}\n"
                f"status={status}\nreturncode={returncode}\nelapsed_seconds={elapsed}\n\n"
                f"[stdout]\n{stdout}\n\n[stderr]\n{stderr}",
                encoding="utf-8",
            )
            (workspace / "execution.json").write_text(
                json.dumps({"status": status, "returncode": returncode, "elapsed_seconds": elapsed}, indent=2),
                encoding="utf-8",
            )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="前端代码代理工具能力测试")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("prepare", "execute", "evaluate"):
        command = sub.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=name != "prepare")
        command.add_argument("--tool", action="append", dest="tools", required=True)
        command.add_argument("--case", action="append", dest="case_ids", default=[])
        command.add_argument("--category", action="append", default=[])
        if name == "prepare":
            command.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
        if name == "execute":
            command.add_argument("--config", type=Path, default=ROOT / "tools.json")
            command.add_argument("--timeout", type=int, default=900)
    sub.add_parser("list")
    return root


def main(argv: Sequence[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        cases = load_cases()
        if args.command == "list":
            for case in cases:
                print(f"{case.id:<28} {case.category:<16} {case.title}")
            return
        cases = select_cases(cases, args.case_ids, args.category)
        if args.command == "prepare":
            run_dir = ROOT / "runs" / args.run_id
            prepare(run_dir, args.tools, cases)
            print(f"运行目录: {run_dir}")
        elif args.command == "execute":
            execute(args.run_dir, args.tools, cases, args.config, args.timeout)
        else:
            for tool in args.tools:
                env = {key: value for key, value in os.environ.items() if key != "CONFIDENT_API_KEY"}
                env.update({"DEEPEVAL_DISABLE_DOTENV": "1", "DEEPEVAL_DISABLE_LEGACY_KEYFILE": "1", "DEEPEVAL_NO_INSPECT_PROMPT": "1"})
                subprocess.run([sys.executable, "-m", "benchmark.evaluation_worker", "--run-dir", str(args.run_dir), "--tool", tool, *sum((["--case", value] for value in args.case_ids), []), *sum((["--category", value] for value in args.category), [])], cwd=ROOT, env=env, check=True)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"错误: {error}") from error


if __name__ == "__main__":
    main()
