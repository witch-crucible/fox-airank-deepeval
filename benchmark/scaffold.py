"""新增 case 脚手架：生成 case 目录骨架并登记评分规格。

case 集是基准覆盖面的核心资产，此前新增 case 需要手工复制目录并手工改
`benchmark/specs.json`，漏登记会让评分阶段直接 `KeyError`。本模块把这两步合成一条命令，
并在写入任何文件之前完成全部校验；写入失败时回滚已创建的目录，不留下半截 case。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Sequence

CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# 与 benchmark/report.py 的 CATEGORY_LABELS 保持一致，用于给出默认产物类型。
DEFAULT_TYPE_BY_CATEGORY = {
    "code_generation": "html",
    "code_correction": "code",
    "logic_analysis": "analysis",
    "magento_business": "analysis",
}

DEFAULT_ACTUAL_FILES_BY_TYPE = {
    "html": ["index.html"],
    "code": ["solution.js"],
    "analysis": ["answer.md"],
}

# 分类级默认产物优先于类型级默认：业务分析题必须同时交付结论与源码引用。
DEFAULT_ACTUAL_FILES_BY_CATEGORY = {
    "magento_business": ["answer.md", "evidence.json"],
}

KNOWN_TYPES = tuple(DEFAULT_ACTUAL_FILES_BY_TYPE)


def case_directory_name(case_id: str) -> str:
    """case id 使用 kebab-case，目录使用 snake_case（与现有 cases/ 一致）。"""
    return case_id.replace("-", "_")


def validate_case_id(case_id: str) -> str:
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.match(case_id or ""):
        raise ValueError("case id 必须是 kebab-case（小写字母、数字和连字符，例如 fix-cart-total）")
    return case_id


def validate_category(category: str) -> str:
    if not isinstance(category, str) or not CATEGORY_PATTERN.match(category or ""):
        raise ValueError("分类必须是小写字母开头、仅含小写字母数字和下划线（例如 code_generation）")
    return category


def resolve_actual_files(category: str, case_type: str, actual_files: Sequence[str] | None) -> list[str]:
    files = [name for name in (actual_files or ()) if isinstance(name, str) and name.strip()]
    if files:
        return list(dict.fromkeys(name.strip() for name in files))
    default = DEFAULT_ACTUAL_FILES_BY_CATEGORY.get(category) or DEFAULT_ACTUAL_FILES_BY_TYPE.get(case_type)
    if default is None:
        raise ValueError(f"分类 {category} 没有默认产物，请用 --actual-file 指定实际输出文件")
    return list(default)


def resolve_case_type(category: str, case_type: str | None) -> str:
    if case_type:
        if case_type not in KNOWN_TYPES:
            raise ValueError(f"未知的产物类型: {case_type}（可选：{', '.join(KNOWN_TYPES)}）")
        return case_type
    default = DEFAULT_TYPE_BY_CATEGORY.get(category)
    if default is None:
        raise ValueError(
            f"分类 {category} 没有默认产物类型，请用 --type 指定（可选：{', '.join(KNOWN_TYPES)}）"
        )
    return default


def build_case_document(
    case_id: str,
    category: str,
    title: str,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {"id": case_id, "category": category, "title": title}
    if project_dir is not None:
        document["project_dir"] = str(project_dir)
    return document


def build_spec_document(
    case_id: str,
    category: str,
    case_type: str,
    actual_files: Sequence[str],
) -> dict[str, Any]:
    return {
        "id": case_id,
        "category": category,
        "type": case_type,
        "actual_files": list(actual_files),
    }


def render_task_template(
    title: str,
    case_id: str,
    actual_files: Sequence[str],
    project_dir: Path | None = None,
) -> str:
    deliverables = "\n".join(f"- `{name}`" for name in actual_files)
    if project_dir is not None:
        deliverables += (
            "\n- `evidence.json`（按需）：源码引用数组，每项含 `path`、`start_line`、`end_line`"
        )
    lines = [
        f"# {title}",
        "",
        "> 脚手架生成的任务模板：请补充完整需求、约束和验收点后再运行评测，并删除本说明段落。",
        "",
    ]
    if project_dir is not None:
        lines += [
            "执行器会把业务项目根目录设为当前工作目录，并在输出目录提供 `PROJECT.json`、"
            "`RESULT_PROTOCOL.md` 及本题要求的产物。业务源码只读：只允许阅读和分析，"
            "不得修改源码、调用业务接口或变更数据库、缓存、队列等外部状态。",
            "",
            f"项目根目录：`{project_dir}`",
            "",
        ]
    lines += [
        "## 背景与约束",
        "",
        "- 只读取和修改当前输出目录，不得查看父目录、其他 case 或评分器。",
        "- 说明允许的依赖、权限和运行方式。",
        "",
        "## 需求与验收点",
        "",
        "1. 逐条列出可验证的行为要求与边界条件。",
        "2. 说明哪些行为属于必须、哪些属于可选。",
        "",
        "## 交付物",
        "",
        deliverables,
        f"- `result.json`：遵循 `RESULT_PROTOCOL.md`，`case_id` 为 `{case_id}`。",
        "",
        "## 验证要求",
        "",
        "- 列出必须实际执行的验证命令或检查；不得伪造未执行的验证。",
        "",
    ]
    return "\n".join(lines)


def scaffold_case(
    cases_root: Path,
    specs_path: Path,
    *,
    case_id: str,
    category: str,
    title: str,
    project_dir: Path | None = None,
    case_type: str | None = None,
    actual_files: Sequence[str] | None = None,
    register_spec: bool = True,
) -> dict[str, Any]:
    """创建 case 目录并（可选）登记 specs.json，返回创建结果。

    所有校验在任何写入之前完成；登记 specs.json 失败时会回滚已创建的目录。
    """
    case_id = validate_case_id(case_id)
    category = validate_category(category)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("标题不能为空")
    title = title.strip()
    if project_dir is not None and (not project_dir.is_absolute() or not project_dir.is_dir()):
        raise ValueError(f"project_dir 必须是存在且为绝对路径的目录: {project_dir}")

    resolved_type = resolve_case_type(category, case_type)
    resolved_files = resolve_actual_files(category, resolved_type, actual_files)
    directory = cases_root / category / case_directory_name(case_id)
    if directory.exists():
        raise ValueError(f"case 目录已存在: {directory}")

    specs: dict[str, Any] = {}
    if register_spec:
        if not specs_path.is_file():
            raise ValueError(f"评分规格文件不存在: {specs_path}")
        try:
            specs = json.loads(specs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"评分规格文件不是合法 JSON: {specs_path}（{error}）") from error
        if not isinstance(specs, dict):
            raise ValueError(f"评分规格文件必须是 JSON 对象: {specs_path}")
        if case_id in specs:
            raise ValueError(f"评分规格已登记该 case，请改用其他 id 或加 --no-spec: {case_id}")

    created: list[Path] = []
    try:
        directory.mkdir(parents=True)
        created.append(directory)
        case_path = directory / "case.json"
        case_path.write_text(
            json.dumps(build_case_document(case_id, category, title, project_dir),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append(case_path)
        task_path = directory / "TASK.md"
        task_path.write_text(
            render_task_template(title, case_id, resolved_files, project_dir), encoding="utf-8"
        )
        created.append(task_path)
    except OSError:
        # 回滚：只删除本次创建的目录，且必须是本次刚创建的空壳目录。
        if created and created[0].is_dir():
            shutil.rmtree(created[0], ignore_errors=True)
        raise

    spec_document: dict[str, Any] | None = None
    if register_spec:
        spec_document = build_spec_document(case_id, category, resolved_type, resolved_files)
        specs[case_id] = spec_document
        try:
            specs_path.write_text(
                json.dumps(specs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            # 规格没写成功时同步回滚 case 目录，避免留下无法评分的 case。
            shutil.rmtree(directory, ignore_errors=True)
            raise
        created.append(specs_path)

    return {
        "case_id": case_id,
        "category": category,
        "directory": directory,
        "files": created,
        "type": resolved_type,
        "actual_files": resolved_files,
        "spec_registered": spec_document is not None,
        "spec": spec_document,
    }
