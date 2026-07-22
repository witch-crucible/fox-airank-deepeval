import json
import tempfile
import unittest
from pathlib import Path

from benchmark.cli import ROOT, grade, load_cases, prepare
from benchmark.report import render_report_html


class BenchmarkTests(unittest.TestCase):
    def test_reference_solutions_score_full_marks(self):
        cases = load_cases()
        self.assertEqual(len(cases), 10)
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            prepare(run_dir, ["reference"], cases)
            specs = json.loads((ROOT / "benchmark" / "specs.json").read_text(encoding="utf-8"))
            reference_files = {
                "fix-cart-total": ("cart.js", "cart.js"),
                "fix-query-string": ("query.js", "query.js"),
                "fix-pagination-window": ("pagination.js", "pagination.js"),
                "write-product-filter": ("product-filter.js", "product-filter.js"),
                "write-pagination-reducer": ("pagination-reducer.js", "pagination-reducer.js"),
                "write-product-card": ("product-card.js", "product-card.js"),
            }
            for case in cases:
                workspace = run_dir / "reference" / case.id
                result = {
                    "case_id": case.id,
                    "status": "completed",
                    "summary": "reference solution",
                    "changed_files": ["result.json"],
                    "verification": ["reference check"],
                }
                if specs[case.id]["type"] == "logic":
                    result["answer"] = specs[case.id]["expected"]
                else:
                    source_name, target_name = reference_files[case.id]
                    source = ROOT / "tests" / "reference" / source_name
                    (workspace / target_name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                    result["changed_files"].append(target_name)
                (workspace / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            report = grade(run_dir, ["reference"], cases)
            self.assertEqual(report["summary"]["reference"]["overall"], 100.0)
            html = (run_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("AI 代码代理评测对比", html)
            self.assertIn('"overall": 100.0', html)

    def test_report_html_escapes_embedded_data(self):
        html = render_report_html(
            {
                "graded_at": "2026-07-14T00:00:00+00:00",
                "summary": {"</script><script>alert(1)</script>": {"overall": 0, "by_category": {}}},
                "results": [],
            }
        )
        self.assertNotIn("</script><script>alert(1)</script>", html)
        self.assertIn("\\u003c/script\\u003e", html)


if __name__ == "__main__":
    unittest.main()
