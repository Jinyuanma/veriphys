"""Small stable data structures shared by the V0 pipeline.

The Physics IR will grow here in V3. Keeping result types explicit from the
start makes compiler failures easy to benchmark later.
"""

from dataclasses import dataclass
from typing import Optional

try:
    from pydantic import BaseModel, Field
except ImportError:  # Keep V0 usable before optional V1 dependencies are installed.
    BaseModel = None  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment,misc]


if BaseModel is not None:

    class LeanFormalization(BaseModel):
        """Structured output expected from the formalizer model."""

        lean_code: str = Field(min_length=1)
        answer_expression: str = Field(min_length=1)
        assumptions: list[str] = Field(default_factory=list)
        notes: str = ""

else:

    @dataclass(frozen=True)
    class LeanFormalization:  # type: ignore[no-redef]
        """Fallback type so V0 imports still work without Pydantic."""

        lean_code: str
        answer_expression: str
        assumptions: list[str]
        notes: str = ""


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    returncode: Optional[int]
    stdout: str
    stderr: str
    command: tuple[str, ...]

    @property
    def error_text(self) -> str:
        """Return the useful compiler diagnostics as one string."""

        return (self.stderr or self.stdout).strip()
