import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark import cli
from benchmark.archive import (
    ARCHIVE_DIR_NAME,
    apply_archive,
    describe_plan,
    directory_size,
    plan_archive,
    restore_run,
    run_created_at,
)


def build_run(root: Path, run_id: str, created_at: str | None = None, payload: str = "artifact") -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"tools": ["codex"], "cases": ["draw-pelican-bicycle"]}
    if created_at:
        manifest["created_at"] = created_at
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (run_dir / "report.json").write_text(payload, encoding="utf-8")
    return run_dir


def iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class PlanTests(unittest.TestCase):
    def test_keeps_newest_runs(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "old-1", iso(30))
            build_run(root, "old-2", iso(20))
            build_run(root, "new-1", iso(1))
            items = plan_archive(root, keep=1)
            self.assertEqual({item.run_id for item in items}, {"old-1", "old-2"})
            self.assertTrue(all(item.destination.parent.name == ARCHIVE_DIR_NAME for item in items))

    def test_selects_runs_older_than_days(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "old", iso(40))
            build_run(root, "recent", iso(3))
            items = plan_archive(root, older_than_days=30)
            self.assertEqual([item.run_id for item in items], ["old"])

    def test_conditions_are_combined(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "old", iso(40))
            build_run(root, "recent", iso(3))
            # 两个条件同时生效：old 满足“30 天前”，且不在最新保留的 1 个 run 内
            self.assertEqual([item.run_id for item in plan_archive(root, older_than_days=30, keep=1)], ["old"])
            # 保留最新 2 个时，没有任何 run 同时满足两个条件
            self.assertEqual(plan_archive(root, older_than_days=30, keep=2), [])

    def test_explicit_run_ids(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            build_run(root, "b", iso(2))
            items = plan_archive(root, run_ids=["b"])
            self.assertEqual([item.run_id for item in items], ["b"])

    def test_unknown_run_id_is_rejected(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            with self.assertRaisesRegex(ValueError, "找不到 run: missing"):
                plan_archive(root, run_ids=["a", "missing"])

    def test_missing_runs_root_is_rejected(self):
        with TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ValueError, "运行目录不存在"):
                plan_archive(Path(raw) / "nope")

    def test_negative_thresholds_are_rejected(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "--older-than"):
                plan_archive(root, older_than_days=-1)
            with self.assertRaisesRegex(ValueError, "--keep"):
                plan_archive(root, keep=-1)

    def test_existing_archive_target_is_rejected(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            (root / ARCHIVE_DIR_NAME / "a").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "归档目标已存在"):
                plan_archive(root, run_ids=["a"])

    def test_archived_runs_are_not_listed_again(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            apply_archive(plan_archive(root))
            self.assertEqual(plan_archive(root), [])


class ApplyTests(unittest.TestCase):
    def test_dry_run_leaves_files_untouched(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            items = plan_archive(root)
            self.assertTrue(items)
            # 只做计划、不落盘：run 仍在原位，且没有创建归档目录
            self.assertTrue((root / "a" / "run.json").is_file())
            self.assertFalse((root / ARCHIVE_DIR_NAME).exists())
            self.assertIn("仅移动到归档目录，不删除任何文件", describe_plan(items))

    def test_apply_moves_and_restore_returns(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            moved = apply_archive(plan_archive(root))
            self.assertEqual(len(moved), 1)
            self.assertFalse((root / "a").exists())
            self.assertTrue((root / ARCHIVE_DIR_NAME / "a" / "run.json").is_file())
            restored = restore_run(root, "a")
            self.assertEqual(restored, root / "a")
            self.assertTrue((root / "a" / "run.json").is_file())

    def test_restore_rejects_missing_and_conflicting_targets(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "归档目录中不存在"):
                restore_run(root, "missing")
            build_run(root, "a", iso(1))
            apply_archive(plan_archive(root))
            build_run(root, "a", iso(1))
            with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
                restore_run(root, "a")

    def test_apply_rejects_stale_source(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "a", iso(1))
            items = plan_archive(root)
            (root / "a").rename(root / "moved-away")
            with self.assertRaisesRegex(ValueError, "已不存在"):
                apply_archive(items)


class HelperTests(unittest.TestCase):
    def test_created_at_falls_back_to_mtime(self):
        with TemporaryDirectory() as raw:
            run_dir = build_run(Path(raw), "a")
            self.assertIsNotNone(run_created_at(run_dir))

    def test_directory_size_counts_files(self):
        with TemporaryDirectory() as raw:
            run_dir = build_run(Path(raw), "a", payload="x" * 100)
            self.assertGreaterEqual(directory_size(run_dir), 100)

    def test_describe_plan_empty(self):
        self.assertEqual(describe_plan([]), "没有符合筛选条件的 run。")


class CommandTests(unittest.TestCase):
    def test_dry_run_then_apply(self):
        with TemporaryDirectory() as raw:
            root = Path(raw) / "runs"
            build_run(root, "a", iso(60))
            cli.main(["archive", "--runs-dir", str(root)])
            self.assertTrue((root / "a").is_dir())
            cli.main(["archive", "--runs-dir", str(root), "--apply"])
            self.assertTrue((root / ARCHIVE_DIR_NAME / "a").is_dir())

    def test_restore_requires_apply(self):
        with TemporaryDirectory() as raw:
            root = Path(raw) / "runs"
            build_run(root, "a", iso(60))
            cli.main(["archive", "--runs-dir", str(root), "--apply"])
            cli.main(["archive", "--runs-dir", str(root), "--restore", "a"])
            self.assertFalse((root / "a").exists())
            cli.main(["archive", "--runs-dir", str(root), "--restore", "a", "--apply"])
            self.assertTrue((root / "a" / "run.json").is_file())

    def test_restore_conflicts_with_selection_flags(self):
        with TemporaryDirectory() as raw:
            root = Path(raw) / "runs"
            build_run(root, "a", iso(60))
            with self.assertRaises(SystemExit) as context:
                cli.main(["archive", "--runs-dir", str(root), "--restore", "a", "--keep", "1"])
            self.assertIn("--restore 不能与", str(context.exception))


if __name__ == "__main__":
    unittest.main()
