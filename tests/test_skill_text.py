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
        self.assertIn("Observed power computed from the same data does not count", guide)
        self.assertIn("a fallacy rated RED_FLAG", guide)


class RunModeTextTest(unittest.TestCase):
    def test_runner_asks_about_participant_data(self):
        runner = read("agents/code_runner_agent.md")
        self.assertIn("`participant_data` | Yes", runner)
        self.assertIn('Any "no" or "not sure" on the first two stops the run', runner)

    def test_participant_runs_report_metadata_only(self):
        runner = read("agents/code_runner_agent.md")
        self.assertIn("report the exit code, file names and sizes only", runner)
        self.assertIn("Do not read logs or output to monitor them", runner)

    def test_safety_rule_matches_run_mode(self):
        skill = read("SKILL.md")
        self.assertIn("Never read raw participant data into the conversation", skill)
        self.assertNotIn("Never touch raw participant data", skill)


class HandoffTextTest(unittest.TestCase):
    def test_ars_guide_does_not_suggest_skipping_the_question(self):
        guide = read("references/ars_integration_guide.md")
        self.assertNotIn('skip "do you have experiment data?"', guide)
        for field in ("repro_lock", "planned_vs_executed", "negative_results", "known_limitations"):
            self.assertIn(field, guide)

    def test_readmes_agree_on_secondary_data(self):
        self.assertIn("For secondary data analysis, use `run` and `validate`", read("README.md"))
        self.assertIn("二次資料分析請用 `run` 和 `validate`", read("README.zh-TW.md"))


if __name__ == "__main__":
    unittest.main()
