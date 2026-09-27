"""Command-line entry point for the V0 verifier."""

from __future__ import annotations

import argparse
from pathlib import Path

from .lean_verifier import LeanUnavailableError
from .pipeline import verify_source


PASSING_EXAMPLE = """import Mathlib.Data.Real.Basic
import Mathlib.Tactic.Linarith

theorem free_fall (m a g F : ℝ) (hm : m ≠ 0)
    (h1 : F = m * a) (h2 : F = m * g) : a = g := by
  have h : m * a = m * g := by
    calc
      m * a = F := h1.symm
      _ = m * g := h2
  have h_sub : m * (a - g) = 0 := by
    nlinarith [h]
  rcases mul_eq_zero.mp h_sub with hm_zero | h_diff
  · exact (hm hm_zero).elim
  · exact sub_eq_zero.mp h_diff
"""

FAILING_EXAMPLE = """import Mathlib.Data.Real.Basic
import Mathlib.Tactic.NormNum

theorem broken_example : (2 : ℝ) + 2 = 5 := by
  norm_num
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Lean theorem with VeriPhys")
    parser.add_argument("--file", type=Path, help="path to a .lean file to verify")
    parser.add_argument(
        "--example", choices=("passing", "failure"), default="passing", help="built-in demo"
    )
    parser.add_argument("--project-dir", type=Path, default=Path("lean"))
    args = parser.parse_args()

    code = args.file.read_text() if args.file else (
        FAILING_EXAMPLE if args.example == "failure" else PASSING_EXAMPLE
    )
    try:
        result = verify_source(code, project_dir=args.project_dir)
    except LeanUnavailableError as exc:
        print(f"Lean unavailable: {exc}")
        return 2

    print(f"Lean Verification: {'PASS' if result.success else 'FAIL'}")
    if not result.success:
        print(result.error_text or "Lean returned a failure without diagnostics.")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
