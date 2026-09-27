from __future__ import annotations

import argparse
import codecs
import io
import json
import locale
import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Sequence, TextIO

from benchmark.paths import PELICAN_CASE, load_identities, workspace_path
from benchmark.token_usage import collect_token_usage

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = "阅读 TASK.md，独立完成任务并执行必要验证。最后必须按 TASK.md 要求生成 result.json。"
DEFAULT_EXECUTION_TIMEOUT_SECONDS = 30 * 60


def pass_rate_value(value: str) -> float:
    """解析 0–1 的通过率下限，供 report --fail-under 作为门禁阈值。"""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须是 0 到 1 之间的数字") from error
    if not 0.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError("必须是 0 到 1 之间的数字")
    return number


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    source: Path
    project_dir: Path | None = None


def load_cases() -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for path in sorted((ROOT / "cases").glob("*/*/case.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        project_dir = data.get("project_dir")
        if project_dir is not None and (not isinstance(project_dir, str) or not Path(project_dir).is_absolute()):
            raise ValueError(f"case 的 project_dir 必须是绝对路径: {path}")
        case = Case(data["id"], data["category"], data["title"], path.parent,
                    Path(project_dir) if project_dir is not None else None)
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
            [token.format(workspace=workspace, output_dir=workspace, prompt=DEFAULT_PROMPT) for token in command]
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


def prepare(
    run_dir: Path,
    tools: list[str],
    cases: list[Case],
    identities: dict[str, Any] | None = None,
) -> None:
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"运行目录已存在且非空: {run_dir}")
    projects = {case.id: project_context(case.project_dir) for case in cases if case.project_dir is not None}
    for tool in tools:
        for case in cases:
            target = workspace_path(run_dir, tool, case.id, identities)
            target.parent.mkdir(parents=True, exist_ok=True)
            if case.id == PELICAN_CASE:
                # This task must start from scratch; local solutions are not fixtures.
                target.mkdir()
                for name in ("TASK.md", "case.json"):
                    source = case.source / name
                    if source.is_file():
                        shutil.copy2(source, target / name)
            else:
                shutil.copytree(
                    case.source,
                    target,
                    ignore=shutil.ignore_patterns(
                        "_git_fixture", "result.json", "agent.log", "agent.live.log", "execution.json"
                    ),
                )
            _materialize_git_fixture(case.source, target)
            project_rules = "只读取和修改当前目录，不得查看父目录、其他 case、评分器或其他工具结果。\n"
            if case.project_dir is not None:
                (target / "PROJECT.json").write_text(
                    json.dumps(projects[case.id], ensure_ascii=False, indent=2), encoding="utf-8"
                )
                project_rules = (
                    f"只读分析项目 {case.project_dir}；仅可在本输出目录写入答案和结果文件。\n"
                    "不得修改项目源码、调用业务接口、连接数据库或执行业务任务；不得查看其他 case、评分器或其他工具结果。\n"
                )
            model_rules = ""
            result_attestation = ""
            if case.id == PELICAN_CASE:
                model_rules = (
                    "仅允许当前被测 Agent 使用当前主模型独立完成；不得调用、启动或委派给任何子 Agent、"
                    "子模型、后台/并行 Agent 或外部 LLM/API。\n"
                )
                result_attestation = '  "submodels_used": false,\n'
            (target / "AGENTS.md").write_text(
                "# 评测工作区规则\n\n"
                + project_rules +
                model_rules +
                "严格完成 TASK.md；不得修改 case.json；必须生成 result.json。\n",
                encoding="utf-8",
            )
            (target / "RESULT_PROTOCOL.md").write_text(
                "# 结果文件协议\n\n完成任务后，在本协议文件所在的输出目录生成 `result.json`：\n\n"
                "```json\n{\n"
                f"  \"case_id\": \"{case.id}\",\n"
                "  \"status\": \"completed\",\n"
                + result_attestation +
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
    if identities:
        manifest["identities"] = identities
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def project_context(project_dir: Path) -> dict[str, str]:
    if not project_dir.is_dir():
        raise ValueError(f"项目目录不存在: {project_dir}")
    context = {"path": str(project_dir.resolve())}
    for key, arguments in (("commit", ["rev-parse", "HEAD"]), ("working_tree", ["status", "--short"])):
        result = subprocess.run(
            ["git", "-C", str(project_dir), *arguments], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise ValueError(f"无法读取项目 Git 状态: {project_dir}")
        context[key] = result.stdout.strip()
    return context


def _stream_command(
    command: list[str], cwd: Path, timeout: int, live_log: TextIO
) -> subprocess.CompletedProcess[str]:
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    events: queue.Queue[tuple[str, str | Exception | None]] = queue.Queue()
    stopping = threading.Event()
    output: dict[str, list[str]] = {"stdout": [], "stderr": []}
    pending = set(output)
    last_stream = None
    stopped = False
    completed = False

    def read_output(name: str, stream: BinaryIO) -> None:
        decoder = io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace"),
            translate=True,
        )
        try:
            with stream:
                while not stopping.is_set():
                    chunk = stream.read1(65536)
                    text = decoder.decode(chunk, final=not chunk)
                    if text:
                        events.put((name, text))
                    if not chunk:
                        break
        except Exception as error:
            events.put((name, error))
        finally:
            events.put((name, None))

    def receive_output(wait: float) -> None:
        nonlocal last_stream
        name, text = events.get(timeout=max(0, wait))
        if text is None:
            pending.remove(name)
        elif isinstance(text, Exception):
            raise text
        else:
            output[name].append(text)
            if last_stream != name:
                live_log.write(f"\n[{name}]\n")
                last_stream = name
            live_log.write(text)
            live_log.flush()
            terminal = sys.stdout if name == "stdout" else sys.stderr
            terminal.write(text)
            terminal.flush()

    def stop_process() -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        if os.name == "posix":
            # Kill this execution's group, including children holding output pipes open.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait()

    readers = [
        threading.Thread(target=read_output, args=(name, stream), daemon=True)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    try:
        for reader in readers:
            reader.start()
        try:
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                receive_output(remaining)
            returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
        except (queue.Empty, subprocess.TimeoutExpired):
            stop_process()
            # Drain output already emitted, without waiting forever on a detached child.
            drain_deadline = time.monotonic() + 1
            while pending:
                remaining = drain_deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    receive_output(remaining)
                except queue.Empty:
                    break
            raise subprocess.TimeoutExpired(
                command, timeout, output="".join(output["stdout"]), stderr="".join(output["stderr"])
            ) from None
        completed = True
        return subprocess.CompletedProcess(
            command, returncode, "".join(output["stdout"]), "".join(output["stderr"])
        )
    finally:
        stopping.set()
        if not completed:
            stop_process()
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=0.2)


def execute(run_dir: Path, tools: list[str], cases: list[Case], config_path: Path, timeout: int) -> None:
    configs = load_tool_config(config_path)
    preflight_tools(configs, tools)
    identities = load_identities(run_dir)
    workspaces: dict[tuple[str, str], Path] = {}
    for tool in tools:
        for case in cases:
            workspace = workspace_path(run_dir, tool, case.id, identities).resolve()
            if not workspace.is_dir():
                raise ValueError(f"case 工作区不存在: {workspace}")
            if case.project_dir is not None and not case.project_dir.is_dir():
                raise ValueError(f"项目目录不存在: {case.project_dir}")
            workspaces[(tool, case.id)] = workspace

    for tool in tools:
        for case in cases:
            workspace = workspaces[(tool, case.id)]
            cwd = case.project_dir or workspace
            prompt = DEFAULT_PROMPT
            if case.project_dir is not None:
                prompt = (
                    f"这是只读项目业务分析测试。当前项目目录：{cwd}。输出目录：{workspace}。"
                    f"阅读输出目录中的 TASK.md、AGENTS.md、RESULT_PROTOCOL.md 和 PROJECT.json，完成题目。"
                    "只读分析项目源码，不得修改项目文件、调用业务接口、连接数据库、启动服务或执行业务任务。"
                    "所有 answer.md、evidence.json、result.json 仅写入上述输出目录，不得写到项目目录。"
                    "不得读取输出目录的父目录、其他 case、评分器或其他工具结果；不得伪造执行或验证记录。"
                )
            command = [
                token.format(workspace=str(cwd), output_dir=str(workspace), prompt=prompt)
                for token in configs[tool]["command"]
            ]
            print(f"[RUN] {tool} / {case.id}", flush=True)
            execution_details = (
                f"工作目录: {cwd}\n"
                f"\n[PROMPT]\n{prompt}\n[/PROMPT]\n"
                f"\n手动执行命令（zsh/bash）:\n"
                f"cd {shlex.quote(str(cwd))} && {shlex.join(command)}\n"
            )
            print(execution_details, flush=True)
            started_at = datetime.now(timezone.utc)
            started = time.monotonic()
            live_log_path = workspace / "agent.live.log"
            print(f"实时日志: {live_log_path}", flush=True)
            with live_log_path.open("w", encoding="utf-8") as live_log:
                live_log.write(
                    f"command={json.dumps(command, ensure_ascii=False)}\n"
                    f"started_at={started_at.isoformat()}\ntimeout_seconds={timeout}\n"
                    f"\n{execution_details}"
                )
                live_log.flush()
                try:
                    result = _stream_command(command, cwd=cwd, timeout=timeout, live_log=live_log)
                    status = "completed" if result.returncode == 0 else "failed"
                    returncode = result.returncode
                    stdout, stderr = result.stdout, result.stderr
                except subprocess.TimeoutExpired as error:
                    status, returncode = "timeout", None
                    stdout = error.stdout or ""
                    stderr = error.stderr or ""
                live_log.write(f"\nstatus={status}\nreturncode={returncode}\n")
            elapsed = round(time.monotonic() - started, 3)
            finished_at = datetime.now(timezone.utc)
            token_usage = collect_token_usage(
                tool,
                stdout=stdout,
                started_at=started_at,
                finished_at=finished_at,
                cwd=str(cwd),
            )
            (workspace / "agent.log").write_text(
                f"command={json.dumps(command, ensure_ascii=False)}\n"
                f"status={status}\nreturncode={returncode}\n"
                f"started_at={started_at.isoformat()}\nfinished_at={finished_at.isoformat()}\n"
                f"elapsed_seconds={elapsed}\ntimeout_seconds={timeout}\n\n"
                f"[stdout]\n{stdout}\n\n[stderr]\n{stderr}",
                encoding="utf-8",
            )
            (workspace / "execution.json").write_text(
                json.dumps(
                    {
                        "status": status,
                        "returncode": returncode,
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "elapsed_seconds": elapsed,
                        "timeout_seconds": timeout,
                        "tokens": token_usage.to_dict(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (workspace / "tokens.json").write_text(
                json.dumps(token_usage.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\n[DONE] {tool} / {case.id}: {status} ({elapsed}s)", flush=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="代码代理与项目业务分析能力测试")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("prepare", "execute", "evaluate"):
        command = sub.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=name != "prepare")
        command.add_argument("--tool", action="append", dest="tools", required=True)
        command.add_argument("--case", action="append", dest="case_ids", default=[])
        command.add_argument("--category", action="append", default=[])
        if name == "prepare":
            command.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
            command.add_argument("--identities-json", default="{}")
        if name == "execute":
            command.add_argument("--config", type=Path, default=ROOT / "tools.json")
            command.add_argument(
                "--timeout",
                type=int,
                default=DEFAULT_EXECUTION_TIMEOUT_SECONDS,
                help=f"每个代理执行的超时秒数（默认 {DEFAULT_EXECUTION_TIMEOUT_SECONDS}，即 30 分钟）",
            )
    sub.add_parser("list")
    report = sub.add_parser("report")
    report.add_argument("--run-dir", type=Path)
    report.add_argument("--tool", action="append", dest="tools", default=[])
    report.add_argument("--history", action="store_true", help="汇总 runs/ 下全部 run 的历史对比")
    report.add_argument(
        "--format", choices=("md", "html", "both"), default="both",
        help="输出格式：md=Markdown，html=自包含静态页面，both=两者（默认）",
    )
    report.add_argument(
        "--fail-under", type=pass_rate_value, default=None,
        help="通过率门禁：任一已评测工具的通过率低于该值（0–1）时以退出码 1 结束",
    )

    from benchmark.stability import DEFAULT_MAX_RANGE, DEFAULT_MIN_SAMPLES

    stability = sub.add_parser("stability", help="跨 run 稳定性分析")
    stability.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    stability.add_argument("--tool", action="append", dest="tools", default=[])
    stability.add_argument("--case", action="append", dest="case_ids", default=[])
    stability.add_argument("--category", action="append", default=[])
    stability.add_argument(
        "--min-samples", type=int, default=DEFAULT_MIN_SAMPLES,
        help=f"判定稳定性所需的最少有效样本数（默认 {DEFAULT_MIN_SAMPLES}）",
    )
    stability.add_argument(
        "--max-range", type=float, default=DEFAULT_MAX_RANGE,
        help=f"允许的单项指标最大极差（默认 {DEFAULT_MAX_RANGE}）",
    )
    stability.add_argument(
        "--format", choices=("md", "html", "both"), default="both",
        help="输出格式：md=Markdown，html=自包含静态页面，both=两者（默认）",
    )

    archive = sub.add_parser("archive", help="归档历史 run（默认仅预演）")
    archive.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    archive.add_argument("--run-id", action="append", dest="run_ids", default=[],
                         help="指定要归档的 run，可重复")
    archive.add_argument("--older-than", type=int, default=None,
                         help="只归档创建时间早于该天数的 run")
    archive.add_argument("--keep", type=int, default=None, help="保留最新的 N 个 run，其余归档")
    archive.add_argument("--restore", default=None, help="把已归档的 run 移回 runs/ 根目录")
    archive.add_argument("--apply", action="store_true", help="实际执行移动；不加则只预演")

    new_case = sub.add_parser("new-case", help="新增 case 脚手架")
    new_case.add_argument("--id", dest="case_id", required=True, help="case id（kebab-case）")
    new_case.add_argument("--category", required=True, help="分类目录名（snake_case）")
    new_case.add_argument("--title", required=True, help="case 标题")
    new_case.add_argument("--project-dir", type=Path, default=None,
                          help="只读业务项目根目录（绝对路径，仅业务分析题需要）")
    new_case.add_argument("--type", dest="case_type", default=None,
                          help="产物类型：html / code / analysis（默认按分类推断）")
    new_case.add_argument("--actual-file", action="append", dest="actual_files", default=[],
                          help="实际输出文件名，可重复（默认按类型推断）")
    new_case.add_argument("--no-spec", action="store_false", dest="register_spec",
                          help="不在 benchmark/specs.json 中登记该 case")
    new_case.add_argument("--cases-dir", type=Path, default=ROOT / "cases")
    new_case.add_argument("--specs", type=Path, default=ROOT / "benchmark" / "specs.json")
    return root


def _check_pass_rate_gate(report: dict[str, Any], threshold: float) -> None:
    """按 --fail-under 判定本次对比是否达标；未达标时以退出码 1 结束。

    没有任何已评测结果的 run 同样视为未达标——门禁不能因为“没评分”而静默通过。
    """
    evaluated = [item for item in report.get("tools", []) if item.get("summary", {}).get("evaluated")]
    if not evaluated:
        raise SystemExit("错误: 本次对比没有任何已评测结果，无法通过 --fail-under 判定")
    failures = [
        f"{item['tool']}（{item['summary']['pass_rate'] * 100:.0f}%）"
        for item in evaluated
        if item["summary"]["pass_rate"] < threshold
    ]
    if failures:
        raise SystemExit(f"错误: 以下工具通过率低于 {threshold * 100:.0f}%：{', '.join(failures)}")
    print(f"通过率门禁：全部已评测工具均不低于 {threshold * 100:.0f}%")


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

            formats = ("md", "html") if args.format == "both" else (args.format,)
            if args.fail_under is not None and args.history:
                raise ValueError("--fail-under 不支持 --history 模式")
            if args.history:
                if args.run_dir is not None:
                    raise ValueError("--history 与 --run-dir 不能同时使用")
                history = write_history_report(ROOT / "runs", cases, formats=formats)
                md = ROOT / "runs" / "history-report.md"
                html = ROOT / "runs" / "history-report.html"
                tail = f"（{len(history)} 个 run）"
                if "md" in formats:
                    print(f"历史报告(Markdown): {md}{tail}")
                if "html" in formats:
                    print(f"历史报告(静态页): {html}{tail}")
            else:
                if args.run_dir is None:
                    raise ValueError("report 需要 --run-dir（或使用 --history）")
                report = write_run_report(args.run_dir, args.tools, cases, formats=formats)
                missing = [item["tool"] for item in report["tools"] if not item["cases"]]
                warning = f"（未找到评测产物: {', '.join(missing)}）" if missing else ""
                if "md" in formats:
                    print(f"报告(Markdown): {args.run_dir / 'report.md'}{warning}")
                if "html" in formats:
                    print(f"报告(静态页): {args.run_dir / 'report.html'}{warning}")
                if args.fail_under is not None:
                    _check_pass_rate_gate(report, args.fail_under)
            return
        if args.command == "stability":
            from benchmark.stability import write_stability_report

            formats = ("md", "html") if args.format == "both" else (args.format,)
            report = write_stability_report(
                args.runs_dir,
                cases,
                tools=args.tools,
                case_ids=args.case_ids,
                categories=args.category,
                min_samples=args.min_samples,
                max_range=args.max_range,
                formats=formats,
            )
            if "md" in formats:
                print(f"稳定性报告(Markdown): {args.runs_dir / 'stability-report.md'}")
            if "html" in formats:
                print(f"稳定性报告(静态页): {args.runs_dir / 'stability-report.html'}")
            distribution = "，".join(
                f"{key} {value}" for key, value in report["summary"].items() if key != "groups"
            )
            print(f"稳定性分组 {report['summary'].get('groups', 0)} 个：{distribution}")
            for warning in report["warnings"]:
                print(f"告警: {warning}")
            return
        if args.command == "archive":
            from benchmark.archive import (
                ARCHIVE_DIR_NAME,
                apply_archive,
                describe_plan,
                plan_archive,
                restore_run,
            )

            if args.restore is not None:
                if args.run_ids or args.older_than is not None or args.keep is not None:
                    raise ValueError("--restore 不能与 --run-id/--older-than/--keep 同时使用")
                destination = args.runs_dir / args.restore
                if not args.apply:
                    print(f"预演：将把 {args.runs_dir / ARCHIVE_DIR_NAME / args.restore} "
                          f"移回 {destination}（加 --apply 执行）")
                    return
                print(f"已恢复: {restore_run(args.runs_dir, args.restore)}")
                return
            items = plan_archive(args.runs_dir, args.run_ids, args.older_than, args.keep)
            if not args.apply or not items:
                print(describe_plan(items))
                if items:
                    print("以上仅为预演；加 --apply 才会移动目录。")
                return
            moved = apply_archive(items)
            print(f"已归档 {len(moved)} 个 run 到 {args.runs_dir / ARCHIVE_DIR_NAME}")
            for path in moved:
                print(f"  - {path}")
            return
        if args.command == "new-case":
            from benchmark.scaffold import scaffold_case

            result = scaffold_case(
                args.cases_dir,
                args.specs,
                case_id=args.case_id,
                category=args.category,
                title=args.title,
                project_dir=args.project_dir,
                case_type=args.case_type,
                actual_files=args.actual_files,
                register_spec=args.register_spec,
            )
            print(f"已创建 case: {result['directory']}")
            for path in result["files"]:
                print(f"  - {path}")
            if result["spec_registered"]:
                print("下一步：补全 TASK.md 的需求与验收点；需要隐藏标准答案时，"
                      f"在 {args.specs} 中为 {result['case_id']} 补充 expected_answer。")
            else:
                print("下一步：补全 TASK.md，并手动在 "
                      f"{args.specs} 中登记该 case，否则评分阶段会失败。")
            return
        cases = select_cases(cases, args.case_ids, args.category)
        if args.command == "prepare":
            run_dir = ROOT / "runs" / args.run_id
            identities = json.loads(args.identities_json)
            if not isinstance(identities, dict):
                raise ValueError("--identities-json 必须是 JSON 对象")
            prepare(run_dir, args.tools, cases, identities)
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
