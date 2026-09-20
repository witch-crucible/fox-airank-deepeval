"""Import and score an already-generated Pelican HTML artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from benchmark.cli import (
    DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    Case,
    load_cases,
    prepare,
    select_cases,
)
from benchmark.paths import PELICAN_CASE, path_component, workspace_path

ROOT = Path(__file__).resolve().parent.parent
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def parse_elapsed_seconds(value: str) -> float:
    """Parse seconds, clock notation, or compact Chinese/English duration units."""
    raw = value.strip()
    if not raw:
        raise argparse.ArgumentTypeError("耗时不能为空")

    try:
        seconds = float(raw)
    except ValueError:
        seconds = -1
    else:
        if math.isfinite(seconds) and seconds >= 0:
            return round(seconds, 3)
        raise argparse.ArgumentTypeError("耗时必须是非负有限数")

    if ":" in raw:
        parts = raw.split(":")
        if len(parts) not in (2, 3):
            raise argparse.ArgumentTypeError("冒号格式应为 MM:SS 或 HH:MM:SS")
        try:
            numbers = [float(part) for part in parts]
        except ValueError as error:
            raise argparse.ArgumentTypeError("耗时包含无效数字") from error
        if any(not math.isfinite(number) or number < 0 for number in numbers):
            raise argparse.ArgumentTypeError("耗时必须是非负有限数")
        hours, minutes, seconds = (0.0, *numbers) if len(numbers) == 2 else numbers
        if minutes >= 60 or seconds >= 60:
            raise argparse.ArgumentTypeError("MM 和 SS 必须小于 60")
        return round(hours * 3600 + minutes * 60 + seconds, 3)

    normalized = re.sub(r"\s+", "", raw.lower())
    for source, target in (
        ("小时", "h"),
        ("分钟", "m"),
        ("秒", "s"),
        ("时", "h"),
        ("分", "m"),
    ):
        normalized = normalized.replace(source, target)
    match = re.fullmatch(
        r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
        r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
        r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?",
        normalized,
    )
    if match is None or not any(match.groupdict().values()):
        raise argparse.ArgumentTypeError("耗时格式无效，可使用 2065、34:25 或 34m25s")
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return round(hours * 3600 + minutes * 60 + seconds, 3)


def artifact_path(value: str) -> Path:
    """Resolve a local path or file URL without accepting remote URLs."""
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        raise argparse.ArgumentTypeError("--result 只接受本地路径或 file:// URL")
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise argparse.ArgumentTypeError("file:// URL 不能指向远程主机")
        value = url2pathname(unquote(parsed.path))
    return Path(value).expanduser().resolve()


def default_run_id(agent: str, model: str) -> str:
    return (
        f"pelican-manual-{path_component(agent).lower()}-"
        f"{path_component(model).lower()}-{datetime.now():%Y%m%d-%H%M%S}"
    )


def _required_text(value: str, option: str) -> str:
    result = value.strip()
    if not result:
        raise ValueError(f"{option} 不能为空")
    return result


def create_scoring_run(
    *,
    artifact: Path,
    run_dir: Path,
    tool: str,
    agent: str,
    model: str,
    intelligence: str,
    elapsed_seconds: float,
    timeout_seconds: int,
    submodels_used: bool,
    case: Case | None = None,
) -> Path:
    """Create an isolated, auditable run for a manually generated result."""
    tool = _required_text(tool, "--tool")
    agent = _required_text(agent, "--agent")
    model = _required_text(model, "--model")
    intelligence = _required_text(intelligence, "--intelligence")
    if not artifact.is_file():
        raise ValueError(f"生成结果不存在: {artifact}")
    if artifact.suffix.lower() != ".html":
        raise ValueError(f"生成结果必须是 HTML 文件: {artifact}")
    content = artifact.read_bytes()
    if not content.strip():
        raise ValueError(f"生成结果为空: {artifact}")
    if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise ValueError("耗时必须是非负有限数")
    if timeout_seconds <= 0:
        raise ValueError("超时上限必须是正整数")

    if case is None:
        case = select_cases(load_cases(), [PELICAN_CASE], [])[0]
    elif case.id != PELICAN_CASE:
        raise ValueError(f"只支持 {PELICAN_CASE}，实际为 {case.id}")

    identity = {
        "agent": agent,
        "model": model,
        "intelligence": intelligence,
    }
    identities = {tool: identity}
    prepare(run_dir, [tool], [case], identities)
    workspace = workspace_path(run_dir, tool, case.id, identities)
    target = workspace / "index.html"
    shutil.copy2(artifact, target)
    digest = hashlib.sha256(content).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    execution = {
        "status": "completed",
        "returncode": None,
        "started_at": None,
        "finished_at": None,
        "recorded_at": now,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "timeout_seconds": timeout_seconds,
        "execution_mode": "manual_result_import",
        "agent_identity": identity,
        "artifact": "index.html",
        "artifact_sha256": digest,
    }
    (workspace / "execution.json").write_text(
        json.dumps(execution, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = {
        "case_id": case.id,
        "status": "completed",
        "submodels_used": submodels_used,
        "summary": "导入已生成的 index.html 进行评分；评分脚本未重新调用被测 Agent。",
        "changed_files": ["index.html"],
        "verification": [
            f"评分脚本确认 index.html 可读取、非空，SHA-256={digest}"
        ],
        "evidence_origin": "manual_result_import",
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace / "agent.log").write_text(
        "execution_mode=manual_result_import\n"
        f"recorded_at={now}\n"
        f"elapsed_seconds={elapsed_seconds}\n"
        f"timeout_seconds={timeout_seconds}\n"
        f"agent={agent}\nmodel={model}\nintelligence={intelligence}\n"
        f"artifact=index.html\nartifact_sha256={digest}\n",
        encoding="utf-8",
    )
    return workspace


def evaluate_and_report(run_dir: Path, tool: str) -> None:
    """Run the existing fixed judge, then materialize the comparison report."""
    env = {key: value for key, value in os.environ.items() if key != "CONFIDENT_API_KEY"}
    env.update(
        {
            "DEEPEVAL_DISABLE_DOTENV": "1",
            "DEEPEVAL_DISABLE_LEGACY_KEYFILE": "1",
            "DEEPEVAL_NO_INSPECT_PROMPT": "1",
        }
    )
    evaluate_command = [
        sys.executable,
        "-m",
        "benchmark.evaluation_worker",
        "--run-dir",
        str(run_dir),
        "--tool",
        tool,
        "--case",
        PELICAN_CASE,
    ]
    print(f"\n$ {' '.join(evaluate_command)}", flush=True)
    subprocess.run(evaluate_command, cwd=ROOT, env=env, check=True)

    from benchmark.report import write_run_report

    write_run_report(run_dir, [tool], load_cases())
    print(f"报告: {run_dir / 'report.md'}")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="对已生成的鹈鹕 index.html 直接评分")
    command.add_argument(
        "--result",
        type=artifact_path,
        required=True,
        help="已生成的 index.html 路径或 file:// URL",
    )
    command.add_argument("--model", required=True, help="被测模型，例如 qwen/qwen3.8-max-0902")
    command.add_argument("--intelligence", required=True, help="智能度/推理强度，未知可填 unknown")
    command.add_argument(
        "--elapsed",
        type=parse_elapsed_seconds,
        required=True,
        help="生成耗时：秒数、MM:SS、HH:MM:SS、34m25s 或 34分25秒",
    )
    command.add_argument("--tool", default="manual", help="报告中的工具 ID（默认 manual）")
    command.add_argument("--agent", default="manual", help="报告中的 Agent 名称（默认 manual）")
    command.add_argument(
        "--timeout",
        type=positive_integer,
        default=DEFAULT_EXECUTION_TIMEOUT_SECONDS,
        help=f"耗时评分上限秒数（默认 {DEFAULT_EXECUTION_TIMEOUT_SECONDS}）",
    )
    command.add_argument("--run-id", help="运行 ID；默认由 Agent、模型和当前时间生成")
    command.add_argument(
        "--submodels-used",
        action="store_true",
        help="声明生成期间使用了子模型；默认记录为 false",
    )
    return command


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    run_id = args.run_id or default_run_id(args.agent, args.model)
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise SystemExit("错误: --run-id 只能包含字母、数字、点、下划线和连字符")
    run_dir = ROOT / "runs" / run_id
    try:
        workspace = create_scoring_run(
            artifact=args.result,
            run_dir=run_dir,
            tool=args.tool,
            agent=args.agent,
            model=args.model,
            intelligence=args.intelligence,
            elapsed_seconds=args.elapsed,
            timeout_seconds=args.timeout,
            submodels_used=args.submodels_used,
        )
        print(f"运行目录: {run_dir}")
        print(f"评分工作区: {workspace}")
        print(
            f"身份: agent={args.agent}, model={args.model}, "
            f"intelligence={args.intelligence}"
        )
        print(f"生成耗时: {args.elapsed}s / 上限 {args.timeout}s")
        evaluate_and_report(run_dir, args.tool)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"错误: {error}") from error
    return 0
