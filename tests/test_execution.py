import io
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from benchmark.cli import Case, _stream_command, execute, prepare


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "source"
        source.mkdir()
        (source / "TASK.md").write_text("test task", encoding="utf-8")
        self.case = Case("stream-test", "test", "Streaming test", source)
        self.run_dir = self.root / "run"
        prepare(self.run_dir, ["test-agent"], [self.case])
        self.workspace = self.run_dir / "test-agent" / self.case.id
        self.script = self.root / "agent.py"
        self.config = self.root / "tools.json"
        self.config.write_text(json.dumps({"test-agent": {
            "command": [sys.executable, "-u", str(self.script)],
        }}), encoding="utf-8")
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def run_agent(self, script, timeout=5):
        self.script.write_text(textwrap.dedent(script), encoding="utf-8")
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            execute(self.run_dir, ["test-agent"], [self.case], self.config, timeout)
        return json.loads((self.workspace / "execution.json").read_text(encoding="utf-8"))

    def assert_final_output(self, stdout, stderr):
        log = (self.workspace / "agent.log").read_text(encoding="utf-8")
        self.assertTrue(log.endswith(f"[stdout]\n{stdout}\n\n[stderr]\n{stderr}"))

    def test_both_streams_are_visible_and_flushed_before_exit_without_newlines(self):
        self.script.write_text(textwrap.dedent("""
            import sys
            import time
            from pathlib import Path

            sys.stdout.write('stdout-ready')
            sys.stdout.flush()
            sys.stderr.write('stderr-ready')
            sys.stderr.flush()
            deadline = time.monotonic() + 8
            while not Path('release').exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('parent did not observe live output')
                time.sleep(0.01)
            print('-finished')
        """), encoding="utf-8")
        errors = []

        def run():
            try:
                execute(self.run_dir, ["test-agent"], [self.case], self.config, 10)
            except BaseException as error:
                errors.append(error)

        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                deadline = time.monotonic() + 5
                live = ""
                while time.monotonic() < deadline:
                    path = self.workspace / "agent.live.log"
                    if path.exists():
                        live = path.read_text(encoding="utf-8")
                    if (
                        "stdout-ready" in live and "stderr-ready" in live
                        and "stdout-ready" in self.stdout.getvalue()
                        and "stderr-ready" in self.stderr.getvalue()
                    ):
                        break
                    time.sleep(0.01)
                self.assertIn("stdout-ready", live)
                self.assertIn("stderr-ready", live)
                self.assertIn("[stdout]", live)
                self.assertIn("[stderr]", live)
                self.assertIn("stdout-ready", self.stdout.getvalue())
                self.assertEqual(self.stderr.getvalue(), "stderr-ready")
                self.assertTrue(worker.is_alive())
                self.assertFalse((self.workspace / "execution.json").exists())
                self.assertFalse((self.workspace / "agent.log").exists())
            finally:
                (self.workspace / "release").touch()
                worker.join(timeout=12)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assert_final_output("stdout-ready-finished\n", "stderr-ready")
        execution = json.loads((self.workspace / "execution.json").read_text())
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(execution["returncode"], 0)
        self.assertIn("started_at", execution)
        self.assertIn("finished_at", execution)
        self.assertIn("[DONE] test-agent / stream-test: completed", self.stdout.getvalue())

    def test_large_stderr_does_not_block_stdout_and_nonzero_exit_is_preserved(self):
        execution = self.run_agent("""
            import sys
            sys.stderr.write('E' * 262144)
            sys.stderr.flush()
            sys.stdout.write('O' * 262144)
            sys.stdout.flush()
            sys.exit(7)
        """)
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(execution["returncode"], 7)
        self.assertEqual(self.stderr.getvalue(), "E" * 262144)
        self.assertIn("O" * 262144, self.stdout.getvalue())
        self.assert_final_output("O" * 262144, "E" * 262144)

    def test_timeout_preserves_partial_output_with_open_or_closed_pipes(self):
        for close_pipes in (False, True):
            with self.subTest(close_pipes=close_pipes):
                started = time.monotonic()
                execution = self.run_agent(f"""
                    import os
                    import sys
                    import time
                    sys.stdout.write('partial stdout')
                    sys.stdout.flush()
                    sys.stderr.write('partial stderr')
                    sys.stderr.flush()
                    if {close_pipes!r}:
                        os.close(1)
                        os.close(2)
                    time.sleep(30)
                """, timeout=1)
                self.assertLess(time.monotonic() - started, 5)
                self.assertEqual(execution["status"], "timeout")
                self.assertIsNone(execution["returncode"])
                self.assertEqual(execution["timeout_seconds"], 1)
                self.assert_final_output("partial stdout", "partial stderr")
                live = (self.workspace / "agent.live.log").read_text()
                self.assertIn("partial stdout", live)
                self.assertIn("partial stderr", live)
                self.assertIn("status=timeout", live)

    def test_unicode_and_final_partial_character_do_not_discard_output(self):
        execution = self.run_agent("""
            import os
            import time
            text = '正在执行'.encode('utf-8')
            for value in text:
                os.write(1, bytes([value]))
                time.sleep(0.01)
            os.write(2, b'incomplete: \\xe4\\xb8')
        """)
        self.assertEqual(execution["status"], "completed")
        self.assertIn("正在执行", self.stdout.getvalue())
        self.assertEqual(self.stderr.getvalue(), "incomplete: \ufffd")
        self.assert_final_output("正在执行", "incomplete: \ufffd")

    @unittest.skipUnless(os.name == "posix", "进程组清理仅适用于 POSIX")
    def test_output_interruption_stops_the_agent(self):
        self.script.write_text(textwrap.dedent("""
            import os
            import time
            from pathlib import Path
            Path('agent.pid').write_text(str(os.getpid()))
            print('started', flush=True)
            time.sleep(30)
        """), encoding="utf-8")

        class InterruptedLog(io.StringIO):
            def write(self, text):
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            _stream_command(
                [sys.executable, "-u", str(self.script)], self.workspace, 5, InterruptedLog()
            )
        pid = int((self.workspace / "agent.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    @unittest.skipUnless(os.name == "posix", "进程组清理仅适用于 POSIX")
    def test_timeout_kills_child_holding_pipes_after_agent_exits(self):
        execution = self.run_agent("""
            import subprocess
            import sys
            subprocess.Popen([sys.executable, '-u', '-c',
                "import time; from pathlib import Path; "
                "print('child-started', flush=True); time.sleep(2); "
                "Path('survived-timeout').write_text('still running')"])
            print('parent-finished', flush=True)
        """, timeout=1)
        self.assertEqual(execution["status"], "timeout")
        self.assertIn("parent-finished", self.stdout.getvalue())
        self.assertIn("child-started", self.stdout.getvalue())
        time.sleep(1.3)
        self.assertFalse((self.workspace / "survived-timeout").exists())


if __name__ == "__main__":
    unittest.main()
