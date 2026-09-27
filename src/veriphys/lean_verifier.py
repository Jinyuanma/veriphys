"""Run Lean in a subprocess and return structured compiler output."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .schema import VerificationResult


class LeanUnavailableError(RuntimeError):
    """Raised when the configured Lean project cannot be executed."""


def verify_lean(
    code: str,
    *,
    project_dir: str | Path = "lean",
    timeout_seconds: float = 30,
) -> VerificationResult:
    """Compile ``code`` with the project's Lake environment.

    The temporary file lives inside the Lean project so imports and the Lake
    toolchain resolve exactly as they do for a normal project source file.
    """

    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise LeanUnavailableError(f"Lean project directory does not exist: {project}")

    command = ("lake", "env", "lean")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".lean", prefix="veriphys_", dir=project, delete=False
        ) as source:
            source.write(code)
            source_path = Path(source.name)
        try:
            completed = subprocess.run(
                [*command, source_path.name],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        finally:
            source_path.unlink(missing_ok=True)
    except FileNotFoundError as exc:
        raise LeanUnavailableError(
            "Could not find `lake`. Install Lean 4 with elan and run `lake update` in lean/."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        return VerificationResult(
            success=False,
            returncode=None,
            stdout=exc.stdout or "",
            stderr=f"Lean timed out after {timeout_seconds:g}s",
            command=command,
        )

    return VerificationResult(
        success=completed.returncode == 0,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        command=command,
    )
