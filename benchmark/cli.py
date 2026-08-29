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


def _relative_fixture_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Git fixture 的 {field} 必须是非空相对路径")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Git fixture 的 {field} 必须位于 fixture 目录内")
    return path


def _run_git(arguments: list[str], repository: Path, env: dict[str, str] | None = None) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "未知错误").strip()
        raise ValueError(f"生成 Git fixture 失败: {detail}") from error


def _materialize_git_fixture(source: Path, workspace: Path) -> None:
    fixture = source / "_git_fixture"
    if not fixture.is_dir():
        return
    if shutil.which("git") is None:
        raise ValueError("当前环境缺少 git，无法生成 Git fixture")

    manifest_path = fixture / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Git fixture 缺少 manifest.json: {source}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Git fixture 的 manifest.json 必须是对象")

    target_path = _relative_fixture_path(manifest.get("target"), "target")
    repository = (workspace / target_path).resolve()
    try:
        repository.relative_to(workspace.resolve())
    except ValueError as error:
        raise ValueError("Git fixture 的 target 超出 case 工作区") from error
    if repository.exists():
        raise ValueError(f"Git fixture 的 target 已存在: {target_path}")

    commits = manifest.get("commits")
    if not isinstance(commits, list) or not commits:
        raise ValueError("Git fixture 的 commits 必须是非空数组")
    repository.mkdir(parents=True)
    _run_git(["init", "--quiet"], repository)
    _run_git(["config", "user.name", str(manifest.get("author_name", "Benchmark Fixture"))], repository)
    _run_git(
        ["config", "user.email", str(manifest.get("author_email", "benchmark@example.invalid"))],
        repository,
    )

    for index, commit in enumerate(commits, start=1):
        if not isinstance(commit, dict):
            raise ValueError(f"Git fixture 的第 {index} 个 commit 必须是对象")
        snapshot_path = _relative_fixture_path(commit.get("snapshot"), f"commits[{index}].snapshot")
        snapshot = (fixture / snapshot_path).resolve()
        try:
            snapshot.relative_to(fixture.resolve())
        except ValueError as error:
            raise ValueError(f"Git fixture 的第 {index} 个 snapshot 超出 fixture 目录") from error
        if not snapshot.is_dir():
            raise ValueError(f"Git fixture 的 snapshot 不存在: {snapshot_path}")
        message = commit.get("message")
        timestamp = commit.get("timestamp")
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"Git fixture 的第 {index} 个 message 必须是非空字符串")
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError(f"Git fixture 的第 {index} 个 timestamp 必须是非空字符串")

        for child in repository.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in snapshot.iterdir():
            destination = repository / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

        _run_git(["add", "--all"], repository)
        commit_env = os.environ.copy()
        commit_env.update({"GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp})
        _run_git(["commit", "--quiet", "--no-gpg-sign", "--message", message], repository, commit_env)


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
                ignore=shutil.ignore_patterns(
                    "_git_fixture", "result.json", "agent.log", "execution.json"
                ),
            )
            _materialize_git_fixture(case.source, target)
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
    report = sub.add_parser("report")
    report.add_argument("--run-dir", type=Path)
    report.add_argument("--tool", action="append", dest="tools", default=[])
    report.add_argument("--history", action="store_true", help="汇总 runs/ 下全部 run 的历史对比")
    return root


def main(argv: Sequence[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        cases = load_cases()
        if args.command == "list":
            for case in cases:
                print(f"{case.id:<28} {case.category:<16} {case.title}")
            return
        if args.command == "report":
            from benchmark.report import write_history_report, write_run_report

            if args.history:
                if args.run_dir is not None:
                    raise ValueError("--history 与 --run-dir 不能同时使用")
                history = write_history_report(ROOT / "runs", cases)
                print(f"历史报告: {ROOT / 'runs' / 'history-report.md'}（{len(history)} 个 run）")
            else:
                if args.run_dir is None:
                    raise ValueError("report 需要 --run-dir（或使用 --history）")
                report = write_run_report(args.run_dir, args.tools, cases)
                missing = [item["tool"] for item in report["tools"] if not item["cases"]]
                warning = f"（未找到评测产物: {', '.join(missing)}）" if missing else ""
                print(f"报告: {args.run_dir / 'report.md'}{warning}")
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
