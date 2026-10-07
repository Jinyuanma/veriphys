"""The V0 pipeline: supplied Lean source -> compiler -> result."""

from pathlib import Path

from .lean_verifier import verify_lean
from .safety import UnsafeLeanError, normalize_lean_source
from .schema import VerificationResult


def verify_source(code: str, project_dir: str | Path = "lean") -> VerificationResult:
    """Check the generated-source boundary, then verify one Lean theorem."""

    try:
        normalized = normalize_lean_source(code)
    except UnsafeLeanError as exc:
        return VerificationResult(
            success=False,
            returncode=None,
            stdout="",
            stderr=f"Generated Lean was rejected by the safety checks: {exc}",
            command=("safety",),
        )
    return verify_lean(normalized, project_dir=project_dir)
