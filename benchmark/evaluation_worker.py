from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.cli import load_cases, select_cases
from benchmark.evaluation import evaluate_tool


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    args = parser.parse_args()
    cases = select_cases(load_cases(), args.case, args.category)
    identities = {}
    manifest = args.run_dir / "run.json"
    if manifest.is_file():
        try:
            identities = json.loads(manifest.read_text(encoding="utf-8")).get("identities", {})
        except json.JSONDecodeError:
            identities = {}
    evaluate_tool(args.run_dir, args.tool, cases, identities)


if __name__ == "__main__":
    main()
