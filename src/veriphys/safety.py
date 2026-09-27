"""Cheap deterministic checks before generated code reaches Lean."""

from __future__ import annotations

import re


FORBIDDEN_TOKEN_RE = re.compile(r"\b(?:axiom|sorry|admit|unsafe)\b")
ALLOWED_IMPORTS = {
    "Mathlib.Data.Real.Basic",
    "Mathlib.Tactic.Linarith",
    "Mathlib.Tactic.NormNum",
    "Mathlib.Tactic.Ring",
    "Mathlib.Tactic.Nlinarith",
    "VeriPhys.Basic",
}
MINIMAL_MATHLIB_IMPORTS = (
    "import Mathlib.Data.Real.Basic",
    "import Mathlib.Tactic.Linarith",
    "import Mathlib.Tactic.NormNum",
)


class UnsafeLeanError(ValueError):
    """Raised when generated Lean violates the V1 safety boundary."""


def check_lean_source(code: str) -> None:
    """Reject forbidden declarations and unexpected imports."""

    if not code.strip():
        raise UnsafeLeanError("The model returned empty Lean code.")
    forbidden = FORBIDDEN_TOKEN_RE.search(code)
    if forbidden:
        raise UnsafeLeanError(f"Forbidden Lean token: {forbidden.group(0)}")

    for line in code.splitlines():
        stripped = line.strip()
        if not stripped.startswith("import "):
            continue
        module = stripped.removeprefix("import ").split()[0]
        if module not in ALLOWED_IMPORTS:
            raise UnsafeLeanError(f"Import is outside the V1 allowlist: {module}")

    if "theorem " not in code and "example " not in code:
        raise UnsafeLeanError("Generated code must contain a theorem or example.")


def normalize_lean_source(code: str) -> str:
    """Normalize a harmless umbrella import before validating generated code.

    Models often emit ``import Mathlib`` by habit. Replacing it with the small
    V1 import set keeps the generated theorem within the allowlist and avoids a
    needless full Mathlib rebuild.
    """

    normalized_lines: list[str] = []
    for line in code.splitlines():
        if line.strip() == "import Mathlib":
            normalized_lines.extend(MINIMAL_MATHLIB_IMPORTS)
        else:
            normalized_lines.append(line)
    normalized = "\n".join(normalized_lines)
    check_lean_source(normalized)
    return normalized
