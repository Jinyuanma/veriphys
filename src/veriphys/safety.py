"""Cheap deterministic checks before generated code reaches Lean."""

from __future__ import annotations

import re


FORBIDDEN_TOKEN_RE = re.compile(
    r"\b(?:axiom|sorry|sorryAx|admit|unsafe|unsafeCast|run_tac|run_cmd|"
    r"run_elab|run_meta|by_elab|native_decide|elab|macro|syntax|parser|command|"
    r"Lean\.Elab|Lean\.Meta|TermElabM|MetaM|CommandElabM|liftIO)\b"
    r"|#(?:eval|check|reduce|print|load|guard_msgs)\b"
    r"|\b(?:IO|System|set_option|namespace|section|end|open|export|include|"
    r"omit|variable|local|scoped|attribute|def|opaque|abbrev|example|instance|"
    r"class|structure|inductive)\b"
)
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
IMPORT_RE = re.compile(r"import\s+([A-Za-z_][A-Za-z0-9_.']*)$")
THEOREM_RE = re.compile(r"theorem\s+[A-Za-z_][A-Za-z0-9_']*\b")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")


class UnsafeLeanError(ValueError):
    """Raised when generated Lean violates the V1 safety boundary."""


def _mask_comments_and_strings(code: str) -> str:
    """Mask comments and literals while preserving newlines and nesting."""

    output: list[str] = []
    index = 0
    block_depth = 0
    state = "normal"
    while index < len(code):
        pair = code[index : index + 2]
        char = code[index]
        if state == "line":
            if char == "\n":
                output.append(char)
                state = "normal"
            else:
                output.append(" ")
            index += 1
            continue
        if state == "block":
            if pair == "/-":
                block_depth += 1
                output.extend("  ")
                index += 2
            elif pair == "-/":
                block_depth -= 1
                output.extend("  ")
                index += 2
                if block_depth == 0:
                    state = "normal"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if state in {"string", "char"}:
            closing = '"' if state == "string" else "'"
            if char == "\\":
                output.append(" ")
                if index + 1 < len(code):
                    output.append("\n" if code[index + 1] == "\n" else " ")
                    index += 2
                else:
                    index += 1
            elif char == closing:
                output.append(" ")
                index += 1
                state = "normal"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if pair == "--":
            output.extend("  ")
            index += 2
            state = "line"
        elif pair == "/-":
            output.extend("  ")
            index += 2
            block_depth = 1
            state = "block"
        elif char == '"':
            output.append(" ")
            index += 1
            state = "string"
        elif char == "'" and index + 2 < len(code) and code[index + 2] == "'":
            output.append(" ")
            index += 1
            state = "char"
        else:
            output.append(char)
            index += 1

    if state == "block" or block_depth:
        raise UnsafeLeanError("Unterminated Lean block comment")
    if state in {"string", "char"}:
        raise UnsafeLeanError("Unterminated Lean string or character literal")
    return "".join(output)


def _theorem_tokens(masked: str) -> list[re.Match[str]]:
    return [
        match for match in IDENTIFIER_RE.finditer(masked)
        if match.group(0) == "theorem"
    ]


def check_lean_source(code: str) -> None:
    """Reject commands and declarations outside the generated-proof boundary."""

    if not code.strip():
        raise UnsafeLeanError("The model returned empty Lean code.")
    masked = _mask_comments_and_strings(code)
    forbidden = FORBIDDEN_TOKEN_RE.search(masked)
    if forbidden:
        raise UnsafeLeanError(f"Forbidden Lean token: {forbidden.group(0)}")

    theorem_tokens = _theorem_tokens(masked)
    if len(theorem_tokens) != 1:
        raise UnsafeLeanError(
            f"Generated code must contain exactly one theorem; found {len(theorem_tokens)}."
        )

    theorem_seen = False
    top_level_theorem_seen = False
    for line in masked.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent > 0:
            if re.match(r"(?:import|theorem)\b", stripped):
                raise UnsafeLeanError("Imports and theorem declarations must be top-level")
            continue
        if stripped.startswith("import"):
            if theorem_seen:
                raise UnsafeLeanError("Imports must appear before the theorem")
            match = IMPORT_RE.fullmatch(stripped)
            if not match:
                raise UnsafeLeanError("Each import must name exactly one allowlisted module")
            module = match.group(1)
            if module not in ALLOWED_IMPORTS:
                raise UnsafeLeanError(f"Import is outside the V1 allowlist: {module}")
            continue
        if stripped.startswith("theorem"):
            if theorem_seen:
                raise UnsafeLeanError("Generated code must contain exactly one theorem")
            if not THEOREM_RE.match(stripped):
                raise UnsafeLeanError("The theorem declaration is malformed")
            theorem_seen = True
            top_level_theorem_seen = True
            continue
        raise UnsafeLeanError(
            f"Top-level Lean command is outside the proof allowlist: {stripped.split()[0]}"
        )

    if not top_level_theorem_seen:
        raise UnsafeLeanError("The theorem declaration must be top-level")


def normalize_lean_source(code: str) -> str:
    """Normalize a harmless umbrella import before validating generated code."""

    masked = _mask_comments_and_strings(code)
    normalized_lines: list[str] = []
    for line, masked_line in zip(code.splitlines(), masked.splitlines()):
        if masked_line.strip() == "import Mathlib":
            normalized_lines.extend(MINIMAL_MATHLIB_IMPORTS)
        else:
            normalized_lines.append(line)
    normalized = "\n".join(normalized_lines)
    check_lean_source(normalized)
    return normalized
