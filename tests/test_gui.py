"""Pure formatting checks for the optional Tkinter front end."""

import unittest

from veriphys.check_answer import AnswerCheckResult
from veriphys.gui import result_as_json, result_summary


class GuiFormattingTests(unittest.TestCase):
    def test_summary_includes_status_and_diagnostics(self) -> None:
        result = AnswerCheckResult(
            status="error",
            problem="F = m*a",
            candidate_answer="a = F/m",
            error="API key is not configured",
        )
        summary = result_summary(result)
        self.assertIn("ERROR", summary)
        self.assertIn("API key is not configured", summary)

    def test_json_report_is_complete(self) -> None:
        result = AnswerCheckResult(
            status="verified",
            problem="F = m*a",
            candidate_answer="a = F/m",
            lean_verified=True,
        )
        encoded = result_as_json(result)
        self.assertIn('"status": "verified"', encoded)
        self.assertIn('"lean_verified": true', encoded)


if __name__ == "__main__":
    unittest.main()
