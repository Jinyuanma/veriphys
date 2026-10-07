"""Lean-backed checks that a generated proof establishes the IR target."""

import unittest
from unittest.mock import patch

import veriphys.check_answer as checker_module
from veriphys.ir_validator import validate_physics_ir
from veriphys.physics_ir import PhysicsIR
from veriphys.proof_contract import ProofContractError, build_proof_contract
from veriphys.schema import LeanFormalization


def newton_ir() -> PhysicsIR:
    return PhysicsIR(
        problem_type="newton_second_law",
        objects=[{"id": "body", "mass": "m"}],
        equations=["F = m*a"],
        target={"quantity": "acceleration", "symbol": "a", "expression": "F/m"},
    )


class ProofContractTests(unittest.TestCase):
    def test_ir_target_must_match_candidate(self) -> None:
        with self.assertRaisesRegex(ProofContractError, "does not match"):
            build_proof_contract(newton_ir(), "a = 2*F/m")

    def test_candidate_cannot_be_ir_premise_even_when_reversed(self) -> None:
        ir = newton_ir().model_copy(update={"equations": ["F = m*a", "F/m = a"]})
        with self.assertRaisesRegex(ProofContractError, "among IR premises"):
            build_proof_contract(ir, "a = F/m")

    def test_algebraically_equivalent_candidate_premise_is_rejected(self) -> None:
        ir = newton_ir().model_copy(
            update={"equations": ["F = m*a", "a = (F*1)/m"]}
        )
        with self.assertRaisesRegex(ProofContractError, "among IR premises"):
            build_proof_contract(ir, "a = F/m")

    def test_algebraically_equivalent_target_is_accepted(self) -> None:
        ir = newton_ir().model_copy(
            update={"target": newton_ir().target.model_copy(update={"expression": "(F*1)/m"})}
        )
        contract = build_proof_contract(ir, "a = F/m")
        self.assertEqual(contract.conclusion, "a = (F / m)")

    def test_zero_mass_cannot_be_combined_with_nonzero_guard(self) -> None:
        ir = newton_ir().model_copy(update={"constraints": ["m = 0"]})
        with self.assertRaisesRegex(ProofContractError, "to zero"):
            build_proof_contract(ir, "a = F/m")

    def test_candidate_cannot_be_ir_parameter(self) -> None:
        ir = newton_ir().model_copy(update={"parameters": {"a": "F/m"}})
        with self.assertRaisesRegex(ProofContractError, "among IR parameters"):
            build_proof_contract(ir, "a = F/m")

    def test_literal_zero_denominator_is_rejected(self) -> None:
        ir = newton_ir().model_copy(
            update={"target": newton_ir().target.model_copy(update={"expression": "F/0"})}
        )
        with self.assertRaisesRegex(ProofContractError, "literal zero"):
            build_proof_contract(ir, "a = F/0")

    def test_nonfinite_numeric_constant_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProofContractError, "finite"):
            build_proof_contract(newton_ir(), "a = 1e999")

    def test_validator_removes_reversed_candidate_premise(self) -> None:
        ir = newton_ir().model_copy(update={"equations": ["F = m*a", "F/m = a"]})
        self.assertEqual(validate_physics_ir(ir).equations, ["F = m*a"])

    def test_generated_theorem_must_prove_contract(self) -> None:
        source = {
            "good": """import Mathlib.Data.Real.Basic
theorem answer (F m a : ℝ) (h : F = m*a) (hm : m ≠ 0) : a = F/m := by
  apply (eq_div_iff hm).2
  calc
    a*m = m*a := mul_comm a m
    _ = F := h.symm
""",
            "answer_as_premise": """import Mathlib.Data.Real.Basic
theorem answer (F m a : ℝ) (h : a = F/m) : a = F/m := h
""",
            "changed_conclusion": """import Mathlib.Data.Real.Basic
theorem answer (F m a : ℝ) : a = a := rfl
""",
        }

        class FakeParser:
            def __init__(self, config: object) -> None:
                pass

            def parse(self, problem: str, answer: str) -> PhysicsIR:
                return newton_ir()

        class FakeGenerator:
            def __init__(self, config: object) -> None:
                pass

            def generate(self, ir: PhysicsIR) -> LeanFormalization:
                return LeanFormalization(
                    lean_code=source[self.case_name],
                    answer_expression="F/m",
                )

        with patch.object(checker_module, "PhysicsParser", FakeParser):
            for case_name, expected in [
                ("good", "verified"),
                ("answer_as_premise", "rejected"),
                ("changed_conclusion", "rejected"),
            ]:
                with self.subTest(case_name=case_name):
                    FakeGenerator.case_name = case_name
                    with patch.object(checker_module, "IRLeanGenerator", FakeGenerator):
                        result = checker_module.check_answer(
                            "F = m*a and m != 0",
                            "a = F/m",
                            project_dir="lean",
                            use_ir=True,
                        )
                    self.assertEqual(result.status, expected, result.error)
                    self.assertEqual(result.lean_verified, expected == "verified")
                    self.assertEqual(
                        result.proof_contract_verified, expected == "verified"
                    )

    def test_repair_is_checked_against_the_same_contract(self) -> None:
        invalid = LeanFormalization(
            lean_code="""import Mathlib.Data.Real.Basic
theorem answer (F m a : ℝ) : a = a := rfl
""",
            answer_expression="F/m",
        )
        repaired = LeanFormalization(
            lean_code="""import Mathlib.Data.Real.Basic
theorem answer (F m a : ℝ) (h : F = m*a) (hm : m ≠ 0) : a = F/m := by
  apply (eq_div_iff hm).2
  calc
    a*m = m*a := mul_comm a m
    _ = F := h.symm
""",
            answer_expression="F/m",
        )

        class FakeParser:
            def __init__(self, config: object) -> None:
                pass

            def parse(self, problem: str, answer: str) -> PhysicsIR:
                return newton_ir()

        class FakeGenerator:
            def __init__(self, config: object) -> None:
                pass

            def generate(self, ir: PhysicsIR) -> LeanFormalization:
                return invalid

        class FakeRepairer:
            def __init__(self, config: object) -> None:
                pass

            def repair(self, *args: object, **kwargs: object) -> LeanFormalization:
                return repaired

        with (
            patch.object(checker_module, "PhysicsParser", FakeParser),
            patch.object(checker_module, "IRLeanGenerator", FakeGenerator),
            patch.object(checker_module, "LeanRepairer", FakeRepairer),
        ):
            result = checker_module.check_answer(
                "F = m*a and m != 0",
                "a = F/m",
                project_dir="lean",
                use_ir=True,
                max_repairs=1,
            )
        self.assertEqual(result.status, "verified", result.error)
        self.assertEqual(result.repair_attempts, 1)
        self.assertTrue(result.proof_contract_verified)
        self.assertEqual(result.attempt_history[0]["status"], "verified")


if __name__ == "__main__":
    unittest.main()
