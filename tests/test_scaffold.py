import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from benchmark import cli
from benchmark.scaffold import (
    case_directory_name,
    render_task_template,
    resolve_actual_files,
    resolve_case_type,
    scaffold_case,
)


def empty_specs(root: Path) -> Path:
    specs = root / "specs.json"
    specs.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8")
    return specs


class ValidationTests(unittest.TestCase):
    def test_case_directory_name_uses_snake_case(self):
        self.assertEqual(case_directory_name("fix-cart-total"), "fix_cart_total")

    def test_rejects_invalid_case_id(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "kebab-case"):
                scaffold_case(root / "cases", empty_specs(root), case_id="Fix_Cart",
                              category="code_generation", title="修复购物车")

    def test_rejects_invalid_category(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "分类必须是"):
                scaffold_case(root / "cases", empty_specs(root), case_id="fix-cart-total",
                              category="Code Generation", title="修复购物车")

    def test_rejects_empty_title(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "标题不能为空"):
                scaffold_case(root / "cases", empty_specs(root), case_id="fix-cart-total",
                              category="code_generation", title="   ")

    def test_rejects_relative_or_missing_project_dir(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for project_dir in (Path("relative/path"), root / "missing"):
                with self.assertRaisesRegex(ValueError, "project_dir"):
                    scaffold_case(root / "cases", empty_specs(root), case_id="analyse-orders",
                                  category="magento_business", title="分析订单",
                                  project_dir=project_dir)

    def test_rejects_existing_directory(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            cases_root = root / "cases"
            (cases_root / "code_generation" / "fix_cart_total").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "已存在"):
                scaffold_case(cases_root, empty_specs(root), case_id="fix-cart-total",
                              category="code_generation", title="修复购物车")

    def test_rejects_duplicate_spec_entry(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            specs = empty_specs(root)
            specs.write_text(json.dumps({"fix-cart-total": {"id": "fix-cart-total"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "已登记该 case"):
                scaffold_case(root / "cases", specs, case_id="fix-cart-total",
                              category="code_generation", title="修复购物车")

    def test_unknown_category_requires_type(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "没有默认产物类型"):
                scaffold_case(root / "cases", empty_specs(root), case_id="new-task",
                              category="custom_category", title="新题")

    def test_unknown_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知的产物类型"):
            resolve_case_type("code_generation", "video")
        self.assertEqual(resolve_case_type("code_generation", None), "html")
        self.assertEqual(resolve_actual_files("code_generation", "html", ["main.html"]), ["main.html"])


class ScaffoldTests(unittest.TestCase):
    def test_creates_case_files_and_registers_spec(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            cases_root = root / "cases"
            specs = empty_specs(root)
            result = scaffold_case(cases_root, specs, case_id="fix-cart-total",
                                   category="code_generation", title="修复购物车总价")
            directory = cases_root / "code_generation" / "fix_cart_total"
            self.assertEqual(result["directory"], directory)
            self.assertTrue((directory / "TASK.md").is_file())
            document = json.loads((directory / "case.json").read_text(encoding="utf-8"))
            self.assertEqual(document["id"], "fix-cart-total")
            self.assertEqual(document["category"], "code_generation")
            self.assertEqual(document["title"], "修复购物车总价")
            self.assertNotIn("project_dir", document)
            registered = json.loads(specs.read_text(encoding="utf-8"))
            self.assertEqual(registered["fix-cart-total"]["actual_files"], ["index.html"])
            self.assertEqual(registered["fix-cart-total"]["type"], "html")
            self.assertTrue(result["spec_registered"])

    def test_project_dir_is_recorded_and_rendered(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_dir = root / "project"
            project_dir.mkdir()
            specs = empty_specs(root)
            result = scaffold_case(root / "cases", specs, case_id="analyse-orders",
                                   category="magento_business", title="分析订单流程",
                                   project_dir=project_dir)
            document = json.loads((result["directory"] / "case.json").read_text(encoding="utf-8"))
            self.assertEqual(document["project_dir"], str(project_dir))
            self.assertEqual(result["actual_files"], ["answer.md", "evidence.json"])
            task = (result["directory"] / "TASK.md").read_text(encoding="utf-8")
            self.assertIn("业务源码只读", task)
            self.assertIn(str(project_dir), task)

    def test_no_spec_skips_registration(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            specs = empty_specs(root)
            result = scaffold_case(root / "cases", specs, case_id="fix-cart-total",
                                   category="code_generation", title="修复购物车",
                                   register_spec=False)
            self.assertFalse(result["spec_registered"])
            self.assertEqual(json.loads(specs.read_text(encoding="utf-8")), {})

    def test_explicit_actual_files_win(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            result = scaffold_case(root / "cases", empty_specs(root), case_id="fix-cart-total",
                                   category="code_generation", title="修复购物车",
                                   case_type="code", actual_files=["solution.js", "notes.md"])
            self.assertEqual(result["actual_files"], ["solution.js", "notes.md"])

    def test_missing_specs_file_is_rejected_before_writing(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            cases_root = root / "cases"
            with self.assertRaisesRegex(ValueError, "评分规格文件不存在"):
                scaffold_case(cases_root, root / "nope.json", case_id="fix-cart-total",
                              category="code_generation", title="修复购物车")
            self.assertFalse(cases_root.exists())

    def test_rolls_back_when_spec_write_fails(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            cases_root = root / "cases"
            specs = empty_specs(root)
            with patch.object(Path, "write_text", side_effect=OSError("磁盘已满")):
                with self.assertRaises(OSError):
                    scaffold_case(cases_root, specs, case_id="fix-cart-total",
                                  category="code_generation", title="修复购物车")
            self.assertFalse((cases_root / "code_generation" / "fix_cart_total").exists())


class TemplateTests(unittest.TestCase):
    def test_template_mentions_result_protocol_and_case_id(self):
        text = render_task_template("标题", "fix-cart-total", ["index.html"])
        self.assertIn("`RESULT_PROTOCOL.md`", text)
        self.assertIn("`fix-cart-total`", text)
        self.assertIn("`index.html`", text)


class CommandTests(unittest.TestCase):
    def test_new_case_command_creates_scaffold(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            specs = empty_specs(root)
            cli.main([
                "new-case", "--id", "fix-cart-total", "--category", "code_generation",
                "--title", "修复购物车总价", "--cases-dir", str(root / "cases"),
                "--specs", str(specs),
            ])
            directory = root / "cases" / "code_generation" / "fix_cart_total"
            self.assertTrue((directory / "case.json").is_file())
            self.assertTrue((directory / "TASK.md").is_file())
            self.assertIn("fix-cart-total", json.loads(specs.read_text(encoding="utf-8")))

    def test_new_case_command_rejects_bad_id(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(SystemExit) as context:
                cli.main([
                    "new-case", "--id", "Bad_ID", "--category", "code_generation",
                    "--title", "修复购物车", "--cases-dir", str(root / "cases"),
                    "--specs", str(empty_specs(root)),
                ])
            self.assertIn("kebab-case", str(context.exception))


if __name__ == "__main__":
    unittest.main()
