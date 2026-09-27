"""The V0 pipeline: supplied Lean source -> compiler -> result."""

from pathlib import Path

from .lean_verifier import verify_lean
from .schema import VerificationResult


def verify_source(code: str, project_dir: str | Path = "lean") -> VerificationResult:
    """Verify one generated theorem without silently changing it."""

    return verify_lean(code, project_dir=project_dir)
