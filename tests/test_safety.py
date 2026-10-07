"""Regression tests for the generated Lean source boundary."""

import unittest
from unittest.mock import patch

from veriphys.pipeline import verify_source
from veriphys.safety import UnsafeLeanError, normalize_lean_source


class SafetyTests(unittest.TestCase):
    def test_accepts_one_theorem_with_allowed_imports(self) -> None:
        source = """import Mathlib.Data.Real.Basic
import Mathlib.Tactic.NormNum

theorem identity (x : ℝ) : x = x := by
  rfl
"""
        self.assertIn("theorem identity", normalize_lean_source(source))

    def test_normalizes_umbrella_import(self) -> None:
        source = """import Mathlib

theorem identity (x : ℝ) : x = x := by
  rfl
"""
        normalized = normalize_lean_source(source)
        self.assertNotIn("import Mathlib\n", normalized)
        self.assertIn("import Mathlib.Data.Real.Basic", normalized)

    def test_rejects_eval_and_filesystem_side_effects(self) -> None:
        for source in (
            "#eval IO.println \"unsafe\"\n",
            '#eval IO.FS.writeFile "../work/unsafe_probe" "generated"\n',
            "import Mathlib.Data.Real.Basic\n\nrun_tac Lean.Elab.Tactic.closeUsingOrAdmit\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(UnsafeLeanError):
                    normalize_lean_source(source)

    def test_rejects_extra_declarations_and_commands(self) -> None:
        for line in ("def helper := 1", "namespace Hidden", "set_option pp.all true"):
            source = f"import Mathlib.Data.Real.Basic\n\n{line}\n"
            with self.subTest(line=line):
                with self.assertRaises(UnsafeLeanError):
                    normalize_lean_source(source)

    def test_rejects_multiple_theorems(self) -> None:
        source = """import Mathlib.Data.Real.Basic
theorem first (x : ℝ) : x = x := by rfl
theorem second (x : ℝ) : x = x := by rfl
"""
        with self.assertRaises(UnsafeLeanError):
            normalize_lean_source(source)

    def test_comments_and_strings_are_not_scanned_as_code(self) -> None:
        source = """-- sorry #eval IO.println unsafe
/- outer comment /- nested sorry -/ still a comment -/
import Mathlib.Data.Real.Basic

theorem identity : \"sorry #eval\" = \"sorry #eval\" := by
  rfl
"""
        normalize_lean_source(source)

    def test_rejects_import_shape_and_position_bypasses(self) -> None:
        sources = (
            "import Mathlib.Data.Real.Basic Mathlib\ntheorem identity : True := by trivial",
            "  import Mathlib.Data.Real.Basic\ntheorem identity : True := by trivial",
            "import Mathlib.Data.Real.Basic\ntheorem identity : True := by trivial\nimport Mathlib.Tactic.NormNum",
        )
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(UnsafeLeanError):
                    normalize_lean_source(source)

    def test_rejects_theorem_count_and_position_bypasses(self) -> None:
        sources = (
            "import Mathlib.Data.Real.Basic\n  theorem hidden : True := by trivial",
            "import Mathlib.Data.Real.Basic\ntheorem first : True := by trivial\n theorem second : True := by trivial",
            "import Mathlib.Data.Real.Basic\ntheorem first : True := by trivial theorem second : True := by trivial",
            "import Mathlib.Data.Real.Basic\nprivate theorem hidden : True := by trivial",
        )
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(UnsafeLeanError):
                    normalize_lean_source(source)

    def test_rejects_elaboration_and_axiom_escape_tokens(self) -> None:
        for token in (
            "by_elab",
            "run_cmd",
            "run_elab",
            "run_meta",
            "run_tac",
            "sorryAx",
            "native_decide",
            "unsafeCast",
        ):
            source = f"import Mathlib.Data.Real.Basic\ntheorem identity : True := by {token}"
            with self.subTest(token=token):
                with self.assertRaises(UnsafeLeanError):
                    normalize_lean_source(source)

    def test_rejects_unterminated_literals_and_comments(self) -> None:
        for source in (
            "import Mathlib.Data.Real.Basic\n/- unfinished\ntheorem identity : True := by trivial",
            'import Mathlib.Data.Real.Basic\ntheorem identity : "unfinished = "unfinished" := by rfl',
        ):
            with self.subTest(source=source):
                with self.assertRaises(UnsafeLeanError):
                    normalize_lean_source(source)

    def test_pipeline_does_not_send_unsafe_source_to_lean(self) -> None:
        with patch("veriphys.pipeline.verify_lean") as verify_lean:
            result = verify_source("#eval IO.println 'unsafe'")
        self.assertFalse(result.success)
        self.assertIn("safety checks", result.error_text)
        verify_lean.assert_not_called()


if __name__ == "__main__":
    unittest.main()
