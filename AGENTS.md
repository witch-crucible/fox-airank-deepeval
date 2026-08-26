# Repository Guidelines

## Project Structure & Module Organization

`benchmark/` contains the Python CLI, report renderer, and hidden grading specifications. `benchmark.py` is the repository-level entry point. Benchmark fixtures live under `cases/<category>/<case_name>/`; each case includes `case.json`, `TASK.md`, and any JavaScript inputs or public tests. Python regression tests are in `tests/`, with known-good JavaScript implementations in `tests/reference/`. Treat `runs/` as generated execution output: inspect reports and logs there, but make reusable changes in `benchmark/`, `cases/`, or `tests/`. Design notes are stored under `docs/`.

## Build, Test, and Development Commands

- `python3 benchmark.py list` lists all registered cases and verifies that case metadata loads.
- `python3 benchmark.py prepare --run-id smoke --tool codex --case fix-cart-total` creates an isolated smoke-test workspace.
- `python3 benchmark.py execute --run-dir runs/smoke --tool codex --case fix-cart-total` invokes the configured agent from `tools.json`.
- `python3 benchmark.py evaluate --run-dir runs/smoke --tool codex --case fix-cart-total` runs the three DeepEval GEval metrics and writes tool-scoped local JSON/HTML.
- `python3 -m unittest discover -s tests -v` runs the repository regression suite.
- `python3 -m compileall -q benchmark tests` checks Python syntax and imports.

Python 3.10+, Node.js 18+, and `deepeval==4.2.0` are required for evaluation. There is no separate build step or formatter configuration.

## Coding Style & Naming Conventions

Follow the existing Python style: four-space indentation, type hints on public helpers, `snake_case` functions and variables, and `PascalCase` classes. Keep CLI errors concise and preserve the repository's Chinese user-facing messages. Case directories use `snake_case`, while case IDs use kebab-case (for example, `pagination_window` and `fix-pagination-window`). Keep JSON human-readable with two-space indentation where generated.

## Testing Guidelines

Tests use `unittest`; name files `test_*.py` and methods `test_<behavior>`. Add or update a case's `public-test.mjs` for visible behavior and update `benchmark/specs.json` only when grading requirements intentionally change. Run the full unit suite and compile check before submitting. Changes to JavaScript cases should also run the relevant public test with `node`.

## Commit & Pull Request Guidelines

Prefer the established Conventional Commit-style subjects: `feat:`, `fix:`, `test:`, or `docs:` followed by a short imperative summary. Avoid vague subjects such as `todo` or `hi`. Pull requests should explain the affected cases or scoring behavior, list verification commands, link the issue when applicable, and include a report excerpt or screenshot when report rendering changes. Do not commit credentials, agent login state, or sensitive data in `tools.json`, logs, or generated runs.
