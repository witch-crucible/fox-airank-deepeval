import json
import subprocess
import unittest
from pathlib import Path

from model_dashboard.local_results import PELICAN_CASE


INDEX_PATH = Path(__file__).resolve().parent.parent / "model_dashboard" / "static" / "index.html"


class LocalDisplayTests(unittest.TestCase):
    def record(self, run_id, score, **overrides):
        return {
            "id": run_id,
            "run_id": run_id,
            "case_id": PELICAN_CASE,
            "tool": "codex",
            "agent": "Codex",
            "model": "sample-model",
            "reasoning_effort": "high",
            "metrics": {"Task Correctness": {"score": score}},
            "preview_url": f"/api/local-benchmarks/preview/{run_id}/codex",
            **overrides,
        }

    def displayed(self, records, mode="best", search="", case_id=PELICAN_CASE):
        script = r"""
            const fs = require("node:fs");
            const vm = require("node:vm");
            const state = JSON.parse(fs.readFileSync(0, "utf8"));
            const html = fs.readFileSync(process.argv[1], "utf8");
            const source = html.split("<script>")[1].split("</script>")[0];
            new vm.Script(source);
            const start = source.indexOf("    function localScore(");
            const end = source.indexOf("    function localButton(", start);
            if (start < 0 || end < 0) throw new Error("Local display functions missing");
            const context = vm.createContext({ state });
            vm.runInContext(source.slice(start, end), context);
            const records = vm.runInContext("visibleLocalRecords()", context);
            process.stdout.write(JSON.stringify(records));
        """
        result = subprocess.run(
            ["node", "-e", script, str(INDEX_PATH)],
            input=json.dumps({
                "local": {"records": records},
                "localHistory": mode,
                "localSearch": search,
                "localCase": case_id,
            }),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_best_run_keeps_scores_and_artifact_from_the_same_record(self):
        latest = self.record("latest", .6, metrics={
            "Task Correctness": {"score": .6}, "Delivery Evidence": {"score": 1},
        })
        best = self.record("older-best", .9, metrics={
            "Task Correctness": {"score": .9}, "Delivery Evidence": {"score": .3},
        })
        other = self.record("other-model", .8, model="other-model")
        self.assertEqual(self.displayed([latest, best, other]), [best, other])

    def test_same_model_and_reasoning_effort_are_merged_across_tools(self):
        latest = self.record("latest", .7, tool="claude", agent="Claude Code")
        best = self.record("best", .9)
        self.assertEqual(self.displayed([latest, best]), [best])

    def test_different_reasoning_efforts_keep_their_own_best_run(self):
        latest_high = self.record("latest-high", .7)
        latest_low = self.record("latest-low", .4, reasoning_effort="low")
        best_high = self.record("best-high", .9)
        best_low = self.record("best-low", .8, reasoning_effort="low")
        unknown = self.record("unknown-effort", 1, reasoning_effort="unknown")
        records = [latest_high, latest_low, best_high, best_low, unknown]
        self.assertEqual(self.displayed(records), [best_high, best_low, unknown])

    def test_ties_and_ungraded_runs_keep_latest_and_zero_is_a_score(self):
        for scores, expected in [((.9, .9), 0), ((None, None), 0), ((None, 0), 1), ((0, None), 0)]:
            with self.subTest(scores=scores):
                records = [self.record("latest", scores[0]), self.record("older", scores[1])]
                self.assertEqual(self.displayed(records), [records[expected]])

    def test_unknown_models_are_not_merged(self):
        records = [self.record("latest", .6, model="unknown"), self.record("older", .9, model="unknown")]
        self.assertEqual(self.displayed(records), records)

    def test_latest_and_all_modes_preserve_configuration_history(self):
        latest = self.record("latest", .6)
        older = self.record("older-best", .9)
        other_config = self.record("other-config", .8, reasoning_effort="low")
        records = [latest, older, other_config]
        self.assertEqual(self.displayed(records, mode="latest"), [latest, other_config])
        self.assertEqual(self.displayed(records, mode="all"), records)

    def test_search_filters_winners_without_substituting_a_lower_score(self):
        latest = self.record("latest-lower", .6)
        best = self.record("older-best", .9)
        other = self.record("other-model", 1, model="other-model")
        records = [latest, best, other]
        self.assertEqual(self.displayed(records, search="SAMPLE-MODEL"), [best])
        self.assertEqual(self.displayed(records, search="latest-lower"), [])
        self.assertEqual(self.displayed(records, mode="all", search="latest-lower"), [latest])

    def test_other_cases_keep_latest_per_configuration(self):
        pelican = self.record("pelican", 1)
        latest = self.record("latest", .6, case_id="other-case")
        older = self.record("older-best", .9, case_id="other-case")
        other_config = self.record("other-config", .8, case_id="other-case", reasoning_effort="low")
        records = [pelican, latest, older, other_config]
        self.assertEqual(self.displayed(records, case_id="other-case"), [latest, other_config])


if __name__ == "__main__":
    unittest.main()
