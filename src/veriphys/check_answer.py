"""Verify a natural-language physics problem and a candidate answer."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .formalizer import (
    FormalizerConfig,
    LLMConfigurationError,
    LLMResponseError,
    OpenAIFormalizer,
)
from .ir_validator import InvalidPhysicsIRError
from .lean_generator import IRLeanGenerator
from .lean_verifier import LeanUnavailableError, verify_lean
from .parser import PhysicsParser
from .pipeline import verify_source
from .proof_contract import ProofContract, ProofContractError, build_proof_contract
from .repair import LeanRepairer
from .safety import UnsafeLeanError, normalize_lean_source
from .schema import VerificationResult


@dataclass(frozen=True)
class AnswerCheckResult:
    status: str
    problem: str
    candidate_answer: str
    pipeline: str = "direct"
    physics_ir: dict[str, object] | None = None
    answer_expression: str | None = None
    assumptions: list[str] | None = None
    lean_code: str | None = None
    lean_verified: bool = False
    proof_contract_verified: bool = False
    proof_contract_premises: list[str] | None = None
    repair_attempts: int = 0
    attempt_history: list[dict[str, object]] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _verify_generated(
    code: str,
    project_dir: str | Path,
    contract: ProofContract | None,
) -> VerificationResult:
    if contract is None:
        return verify_source(code, project_dir=project_dir)
    try:
        source = contract.attach(code)
    except ProofContractError as exc:
        return VerificationResult(
            success=False,
            returncode=None,
            stdout="",
            stderr=f"Proof contract rejected generated Lean: {exc}",
            command=("proof_contract",),
        )
    # ``source`` already passed the safety check before the deterministic
    # contract theorem was attached. Verify the combined file directly so the
    # contract's second theorem is not mistaken for model-generated code.
    return verify_lean(source, project_dir=project_dir)


def check_answer(
    problem: str,
    candidate_answer: str,
    *,
    project_dir: str | Path = "lean",
    model: str | None = None,
    use_ir: bool = False,
    max_repairs: int = 0,
) -> AnswerCheckResult:
    """Ask the model to formalize a candidate, then let Lean decide."""

    if max_repairs < 0:
        raise ValueError("max_repairs must be non-negative")
    if max_repairs > 3:
        raise ValueError("max_repairs must be at most 3")

    ir = None
    contract = None
    try:
        config = FormalizerConfig.from_environment(model)
        if use_ir:
            ir = PhysicsParser(config).parse(problem, candidate_answer)
            contract = build_proof_contract(ir, candidate_answer)
            formalization = IRLeanGenerator(config).generate(ir)
        else:
            formalization = OpenAIFormalizer(config).formalize(problem, candidate_answer)
        lean_code = normalize_lean_source(formalization.lean_code)
        verification = _verify_generated(lean_code, project_dir, contract)
    except UnsafeLeanError as exc:
        return AnswerCheckResult(
            status="rejected",
            problem=problem,
            candidate_answer=candidate_answer,
            pipeline="ir" if use_ir else "direct",
            physics_ir=ir.model_dump() if ir else None,
            error=f"Generated Lean was rejected by the safety checks: {exc}",
        )
    except (
        LLMConfigurationError,
        LLMResponseError,
        LeanUnavailableError,
        InvalidPhysicsIRError,
        ValueError,
    ) as exc:
        return AnswerCheckResult(
            status="error",
            problem=problem,
            candidate_answer=candidate_answer,
            pipeline="ir" if use_ir else "direct",
            physics_ir=ir.model_dump() if ir else None,
            error=str(exc),
        )
    except Exception as exc:  # Surface SDK/API failures as a user-facing result.
        return AnswerCheckResult(
            status="error",
            problem=problem,
            candidate_answer=candidate_answer,
            pipeline="ir" if use_ir else "direct",
            physics_ir=ir.model_dump() if ir else None,
            error=f"LLM request failed: {exc}",
        )

    if verification.success:
        return AnswerCheckResult(
            status="verified",
            problem=problem,
            candidate_answer=candidate_answer,
            pipeline="ir" if use_ir else "direct",
            physics_ir=ir.model_dump() if ir else None,
            answer_expression=formalization.answer_expression,
            assumptions=formalization.assumptions,
            lean_code=lean_code,
            lean_verified=True,
            proof_contract_verified=contract is not None,
            proof_contract_premises=list(contract.premises) if contract else None,
            attempt_history=[],
        )

    # A compiler failure can be repaired with bounded model feedback. Each
    # repaired source is normalized and passed through the same safety checks
    # before Lean sees it.
    attempt_history: list[dict[str, object]] = []
    current_formalization = formalization
    current_code = lean_code
    current_feedback = (
        verification.error_text or "Lean could not prove the candidate answer."
    )
    repair_attempts = 0

    if max_repairs:
        repairer = LeanRepairer(config)
        for attempt_number in range(1, max_repairs + 1):
            repair_attempts = attempt_number
            repaired = None
            try:
                repaired = repairer.repair(
                    problem,
                    candidate_answer,
                    current_code,
                    current_feedback,
                    physics_ir=ir,
                )
                repaired_code = normalize_lean_source(repaired.lean_code)
            except UnsafeLeanError as exc:
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "unsafe",
                        "error": str(exc),
                        "lean_code": repaired.lean_code if repaired is not None else None,
                    }
                )
                if repaired is not None:
                    current_code = repaired.lean_code
                current_feedback = f"Generated Lean was rejected by safety checks: {exc}"
                continue
            except (
                LLMConfigurationError,
                LLMResponseError,
                LeanUnavailableError,
                ValueError,
            ) as exc:
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "error",
                        "error": str(exc),
                    }
                )
                return AnswerCheckResult(
                    status="error",
                    problem=problem,
                    candidate_answer=candidate_answer,
                    pipeline="ir" if use_ir else "direct",
                    physics_ir=ir.model_dump() if ir else None,
                    answer_expression=current_formalization.answer_expression,
                    assumptions=current_formalization.assumptions,
                    lean_code=current_code,
                    repair_attempts=repair_attempts,
                    attempt_history=attempt_history,
                    error=f"Repair attempt {attempt_number} failed: {exc}",
                )
            except Exception as exc:  # Surface relay failures consistently.
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "error",
                        "error": f"LLM request failed: {exc}",
                    }
                )
                return AnswerCheckResult(
                    status="error",
                    problem=problem,
                    candidate_answer=candidate_answer,
                    pipeline="ir" if use_ir else "direct",
                    physics_ir=ir.model_dump() if ir else None,
                    answer_expression=current_formalization.answer_expression,
                    assumptions=current_formalization.assumptions,
                    lean_code=current_code,
                    repair_attempts=repair_attempts,
                    attempt_history=attempt_history,
                    error=f"Repair attempt {attempt_number} failed: LLM request failed: {exc}",
                )

            try:
                repaired_verification = _verify_generated(
                    repaired_code, project_dir, contract
                )
            except LeanUnavailableError as exc:
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "error",
                        "error": str(exc),
                        "lean_code": repaired_code,
                    }
                )
                return AnswerCheckResult(
                    status="error",
                    problem=problem,
                    candidate_answer=candidate_answer,
                    pipeline="ir" if use_ir else "direct",
                    physics_ir=ir.model_dump() if ir else None,
                    answer_expression=current_formalization.answer_expression,
                    assumptions=current_formalization.assumptions,
                    lean_code=current_code,
                    repair_attempts=repair_attempts,
                    attempt_history=attempt_history,
                    error=f"Repair attempt {attempt_number} could not run Lean: {exc}",
                )
            attempt_history.append(
                {
                    "attempt": attempt_number,
                    "status": "verified" if repaired_verification.success else "rejected",
                    "error": repaired_verification.error_text or None,
                    "lean_code": repaired_code,
                }
            )
            current_formalization = repaired
            current_code = repaired_code
            current_feedback = (
                repaired_verification.error_text
                or "Lean could not prove the candidate answer."
            )
            if repaired_verification.success:
                return AnswerCheckResult(
                    status="verified",
                    problem=problem,
                    candidate_answer=candidate_answer,
                    pipeline="ir" if use_ir else "direct",
                    physics_ir=ir.model_dump() if ir else None,
                    answer_expression=repaired.answer_expression,
                    assumptions=repaired.assumptions,
                    lean_code=repaired_code,
                    lean_verified=True,
                    proof_contract_verified=contract is not None,
                    proof_contract_premises=list(contract.premises) if contract else None,
                    repair_attempts=repair_attempts,
                    attempt_history=attempt_history,
                )

    return AnswerCheckResult(
        status="rejected",
        problem=problem,
        candidate_answer=candidate_answer,
        pipeline="ir" if use_ir else "direct",
        physics_ir=ir.model_dump() if ir else None,
        answer_expression=current_formalization.answer_expression,
        assumptions=current_formalization.assumptions,
        lean_code=current_code,
        repair_attempts=repair_attempts,
        attempt_history=attempt_history,
        error=current_feedback,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a candidate physics answer with Lean")
    parser.add_argument("--problem", required=True, help="natural-language physics problem")
    parser.add_argument("--answer", required=True, help="candidate answer to verify")
    parser.add_argument("--model", help="OpenAI model; defaults to VERIPHYS_MODEL")
    parser.add_argument("--project-dir", type=Path, default=Path("lean"))
    parser.add_argument(
        "--use-ir",
        action="store_true",
        help="parse through Physics IR before generating Lean",
    )
    parser.add_argument(
        "--max-repairs",
        type=int,
        default=0,
        help="retry Lean generation with compiler feedback (0-3, default: 0)",
    )
    parser.add_argument("--json", action="store_true", help="print the complete JSON result")
    args = parser.parse_args()

    result = check_answer(
        args.problem,
        args.answer,
        project_dir=args.project_dir,
        model=args.model,
        use_ir=args.use_ir,
        max_repairs=args.max_repairs,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Status: {result.status.upper()}")
        if result.answer_expression:
            print(f"Formalized answer: {result.answer_expression}")
        if result.assumptions:
            print("Assumptions:")
            for assumption in result.assumptions:
                print(f"- {assumption}")
        if result.error:
            print(f"Reason: {result.error}")
    return 0 if result.status == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
