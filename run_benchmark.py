#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from benchmark.cli import load_tool_config, preflight_tools


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "tools.json"
IDENTITY_PROMPT = (
    "只输出一行 JSON，不要使用工具："
    '{"agent":"你的 agent 名称","model":"当前实际模型 ID",'
    '"intelligence":"当前实际智能度（如 low/medium/high/xhigh，未知则 unknown）"}'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量执行配置文件中的代码代理基准测试")
    parser.add_argument(
        "--run-id",
        help="运行 ID（默认使用 agent、模型和当前时间）",
    )
    parser.add_argument("--case", dest="case_ids", action="append", default=[], help="指定 case，可重复")
    parser.add_argument("--category", action="append", default=[], help="指定分类，可重复")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="工具配置文件")
    parser.add_argument("--tool", dest="tools", action="append", default=[], help="指定工具，可重复")
    parser.add_argument("--timeout", type=positive_integer, help="每个代理执行的超时秒数")
    args = parser.parse_args()
    if args.run_id is not None and not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id):
        parser.error("--run-id 只能包含字母、数字、点、下划线和连字符")
    return args


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def select_tools(configured: tuple[str, ...], requested: list[str]) -> tuple[str, ...]:
    if not requested:
        return configured
    unknown = sorted(set(requested) - set(configured))
    if unknown:
        raise ValueError(f"工具配置不存在: {', '.join(unknown)}")
    return tuple(dict.fromkeys(requested))


def common_args(args: argparse.Namespace, tools: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for tool in tools:
        result.extend(("--tool", tool))
    for case_id in args.case_ids:
        result.extend(("--case", case_id))
    for category in args.category:
        result.extend(("--category", category))
    return result


def command_option(command: list[str], *names: str) -> str | None:
    for index, token in enumerate(command[:-1]):
        if token in names:
            return command[index + 1]
    return None


def execution_identity(config: dict[str, object]) -> tuple[str, str, str]:
    command = config["command"]
    if not isinstance(command, list):
        raise ValueError("工具 command 必须是数组")
    agent = config.get("agent") or command_option(command, "--agent")
    model = config.get("model") or command_option(command, "--model", "-m")
    intelligence = (
        config.get("intelligence")
        or config.get("reasoning_effort")
        or command_option(command, "--intelligence", "--reasoning-effort")
    )
    return (
        str(agent or "unknown"),
        str(model or "unknown"),
        str(intelligence or "unknown"),
    )


def parse_json_object(value: str) -> tuple[str, str, str] | None:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    agent = data.get("agent")
    model = data.get("model")
    if isinstance(agent, str) and agent.strip() and isinstance(model, str) and model.strip():
        intelligence = data.get("intelligence")
        if not isinstance(intelligence, str) or not intelligence.strip():
            intelligence = "unknown"
        return agent.strip(), model.strip(), intelligence.strip()
    return None


def parse_identity_output(tool: str, output: str) -> tuple[str, str, str] | None:
    for line in reversed(output.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidates: list[object] = []
        if tool == "codex" and event.get("type") == "item.completed":
            candidates.append(event.get("item", {}).get("text"))
        elif tool == "claude" and event.get("type") == "result":
            candidates.append(event.get("result"))
        elif tool == "opencode" and event.get("type") == "text":
            candidates.append(event.get("part", {}).get("text"))
        elif tool == "qwen":
            candidates.extend((event.get("result"), event.get("text")))
        for candidate in candidates:
            if isinstance(candidate, str):
                identity = parse_json_object(candidate)
                if identity is not None:
                    return identity
    return None


def identity_command(
    tool: str,
    config: dict[str, object],
    workspace: Path = ROOT,
) -> list[str] | None:
    command = config.get("command")
    if not isinstance(command, list) or not command:
        return None
    executable = str(command[0])
    if tool == "codex":
        return [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
            "--json",
            IDENTITY_PROMPT,
        ]
    if tool == "claude":
        return [
            executable,
            "-p",
            "--permission-mode",
            "auto",
            "--no-session-persistence",
            "--tools",
            "",
            "--output-format",
            "json",
            IDENTITY_PROMPT,
        ]
    if tool == "opencode":
        identity = [executable, "run"]
        for flag in ("--pure", "--auto"):
            if flag in command:
                identity.append(flag)
        identity.extend(("--format", "json", "--dir", str(workspace)))
        for option in ("--agent", "--model", "-m", "--variant"):
            value = command_option(command, option)
            if value and option not in identity:
                identity.extend((option, value))
        identity.append(IDENTITY_PROMPT)
        return identity
    return None


def query_identity(tool: str, config: dict[str, object]) -> tuple[str, str, str]:
    fallback = execution_identity(config)
    with tempfile.TemporaryDirectory(prefix="benchmark-identity-") as directory:
        workspace = Path(directory)
        command = identity_command(tool, config, workspace)
        if command is None:
            print(f"  {tool}: 不支持身份探测，使用配置值")
            return fallback
        print(f"  {tool}: 正在询问 Agent、模型和智能度...", flush=True)
        try:
            result = subprocess.run(
                command,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"  {tool}: 探测失败（{error}），使用配置值")
            return fallback
    identity = parse_identity_output(tool, result.stdout)
    if result.returncode != 0 or identity is None:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit {result.returncode}"
        print(f"  {tool}: 探测失败（{reason}），使用配置值")
        return fallback
    return identity


def query_identities(
    configs: dict[str, dict[str, object]], tools: tuple[str, ...]
) -> dict[str, tuple[str, str, str]]:
    print("Identity discovery:")
    return {tool: query_identity(tool, configs[tool]) for tool in tools}


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return normalized or "unknown"


def default_run_id(identities: dict[str, tuple[str, str, str]]) -> str:
    identity = "_".join(
        f"{slug(agent)}-{slug(model)}" for agent, model, _intelligence in identities.values()
    )
    return f"{identity}-{datetime.now():%Y%m%d-%H%M%S}"


def print_execution_plan(
    identities: dict[str, tuple[str, str, str]], tools: tuple[str, ...]
) -> None:
    print("\nExecution plan:")
    for tool in tools:
        agent, model, intelligence = identities[tool]
        print(f"  {tool}: agent={agent}, model={model}, intelligence={intelligence}")


def run(command: list[str]) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    try:
        configs = load_tool_config(config_path)
        configured_tools = tuple(configs)
        if not configured_tools:
            raise ValueError(f"工具配置为空: {config_path}")
        tools = select_tools(configured_tools, args.tools)
        preflight_tools(configs, tools)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"错误: {error}") from error
    identities = (
        {tool: execution_identity(configs[tool]) for tool in tools}
        if args.run_id
        else query_identities(configs, tools)
    )
    run_id = args.run_id or default_run_id(identities)
    run_dir = ROOT / "runs" / run_id
    benchmark = [sys.executable, str(ROOT / "benchmark.py")]
    shared = common_args(args, tools)

    print(f"Tools: {', '.join(tools)}")
    print(f"Run directory: {run_dir}")
    run([*benchmark, "prepare", "--run-id", run_id, *shared])

    print_execution_plan(identities, tools)
    execute = [*benchmark, "execute", "--run-dir", str(run_dir), *shared]
    execute.extend(("--config", str(config_path)))
    if args.timeout is not None:
        execute.extend(("--timeout", str(args.timeout)))
    run(execute)

    run([*benchmark, "grade", "--run-dir", str(run_dir), *shared])
    print(f"\nHTML report: {run_dir / 'report.html'}")
    print(f"JSON report: {run_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
