#!/usr/bin/env python3
"""Text checks: rules that later doc edits must not silently remove."""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def read(name):
    return (REPO / name).read_text(encoding="utf-8")


class ValidateTextTest(unittest.TestCase):
    def test_template_has_no_editorial_column_or_old_rating(self):
        template = read("templates/output_formats.md")
        self.assertNotIn("Recommendation", template)
        self.assertNotIn("SOLID", template)
        self.assertIn("What to check", template)

    def test_guide_rates_a_clean_null(self):
        guide = read("references/statistical_interpretation_guide.md")
        self.assertNotIn("SOLID", guide)
        self.assertIn("A non-significant result also has a precise estimate", guide)
        self.assertIn('Do not say "no effect"', guide)
        self.assertIn("whole CI lies between -B and +B", guide)
        self.assertIn("it does not make an estimate precise", guide)
        self.assertIn("highest level among the findings", guide)
        self.assertIn("a fallacy rated RED_FLAG", guide)


class RunModeTextTest(unittest.TestCase):
    def test_runner_asks_about_participant_data(self):
        runner = read("agents/code_runner_agent.md")
        self.assertIn("`participant_data` | Yes", runner)
        self.assertIn('Any "no" or "not sure" on the first two stops the run', runner)
        self.assertIn("Ask before you open any data file", runner)
        self.assertIn('Treat "not sure" as yes', runner)
        self.assertIn("do not open input data files at all", runner)

    def test_participant_runs_report_metadata_only(self):
        runner = read("agents/code_runner_agent.md")
        self.assertIn("report the exit code, file names and sizes only", runner)
        self.assertIn("Do not read logs or output to monitor them", runner)
        self.assertIn("send stdout and stderr to a log file", runner)
        self.assertNotIn("paste what they choose", runner)

    def test_reruns_compare_participant_files_by_hash(self):
        protocol = read("references/reproducibility_protocol.md")
        self.assertIn("compare hash and size only", protocol)

    def test_validate_asks_before_opening_a_result_file(self):
        self.assertIn("ask whether it holds only aggregate numbers", read("SKILL.md"))

    def test_safety_rule_matches_run_mode(self):
        skill = read("SKILL.md")
        self.assertIn("Never read raw participant data into the conversation", skill)
        self.assertNotIn("Never touch raw participant data", skill)
        self.assertNotIn("SOLID", skill)


class HandoffTextTest(unittest.TestCase):
    def test_ars_guide_does_not_suggest_skipping_the_question(self):
        guide = read("references/ars_integration_guide.md")
        self.assertNotIn('skip "do you have experiment data?"', guide)
        self.assertNotIn("asks every run", guide)
        self.assertIn("Do not copy these values into an ARS passport", guide)
        for field in ("repro_lock", "planned_vs_executed", "negative_results", "known_limitations"):
            self.assertIn(field, guide)

    def test_readmes_agree_on_secondary_data(self):
        self.assertIn("For secondary data analysis, use `run` and `validate`", read("README.md"))
        self.assertIn("二次資料分析請用 `run` 和 `validate`", read("README.zh-TW.md"))


if __name__ == "__main__":
    unittest.main()
