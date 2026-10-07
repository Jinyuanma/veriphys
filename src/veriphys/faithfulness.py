"""Conservative checks that Physics IR symbols come from the source problem."""

from __future__ import annotations

import re

from .physics_ir import PhysicsIR


class IRFaithfulnessError(ValueError):
    """Raised when the IR cannot be traced back to the supplied problem text."""


IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*\b")
BUILTIN_FUNCTIONS = {"abs", "cos", "exp", "log", "pi", "sin", "sqrt", "tan"}
TEMPLATE_SYMBOLS: dict[str, set[str]] = {
    "newton_second_law": {"m", "F", "a"},
    "free_fall": {"m", "F", "a", "g", "t", "v", "v0", "y", "y0"},
    "inclined_plane": {"m", "F", "a", "g", "theta", "x"},
    "hooke_law": {"F", "k", "x"},
    "kinematics_1d": {"x", "x0", "v", "v0", "a", "t"},
    "energy_conservation": {"m", "g", "h", "h0", "v", "v0", "K", "U"},
    "projectile_1d": {
        "m", "x", "x0", "y", "y0", "v", "v0", "vx", "vy", "a", "g", "t", "theta"
    },
}
AUXILIARY_SUFFIXES = {
    "final", "friction", "initial", "net", "normal", "parallel", "perp", "spring", "total"
}


def _identifiers(text: str) -> set[str]:
    return set(IDENTIFIER_RE.findall(text))


def _ir_expression_text(ir: PhysicsIR) -> list[str]:
    """Return fields whose identifiers represent algebraic symbols.

    Force directions and parameter labels are descriptive metadata (for
    example ``vertical`` or ``gravity``), so they must not be treated as
    algebraic variables. Their expressions still need auditing.
    """

    values = [*ir.equations, *ir.constraints, ir.target.symbol]
    if ir.target.expression:
        values.append(ir.target.expression)
    values.extend(obj.mass for obj in ir.objects if obj.mass)
    values.extend(ir.parameters.values())
    for force in ir.forces:
        if force.expression:
            values.append(force.expression)
    return values


def _implicit_symbols(problem: str) -> set[str]:
    """Map ordinary physics words to conventional symbols used by templates."""

    lower = problem.lower()
    symbols: set[str] = set()
    if any(word in lower for word in ("mass", "body", "block", "particle")):
        symbols.add("m")
    if "force" in lower:
        symbols.add("F")
    if any(word in lower for word in ("acceleration", "accelerate")):
        symbols.add("a")
    if any(word in lower for word in ("gravity", "gravitational", "free fall", "falling")):
        symbols.add("g")
    if any(word in lower for word in ("spring", "hooke")):
        symbols.update(("k", "x"))
    if any(word in lower for word in ("time", "second", "duration")):
        symbols.update(("t", "v0", "v"))
    if any(word in lower for word in ("displacement", "position", "distance")):
        symbols.update(("x", "x0"))
    if any(word in lower for word in ("angle", "incline", "inclined", "slope")):
        symbols.add("theta")
    if "projectile" in lower:
        symbols.update({"x", "y", "v0", "vx", "vy", "g", "t", "theta"})
    return symbols


def _is_allowed_symbol(symbol: str, allowed_symbols: set[str], ir: PhysicsIR) -> bool:
    template_symbols = TEMPLATE_SYMBOLS.get(ir.problem_type, set())
    if symbol in allowed_symbols or symbol in template_symbols:
        return True
    # Template equations often name an intermediate component such as
    # F_parallel or F_net. Permit that name only when its base is already a
    # recognized physical symbol and its suffix is a known component label.
    if "_" in symbol:
        base, suffix = symbol.split("_", 1)
        if base in allowed_symbols | template_symbols and suffix in AUXILIARY_SUFFIXES:
            return True
    return False


def audit_ir_faithfulness(problem: str, ir: PhysicsIR) -> None:
    """Reject unsupported or lexically invented IR content.

    This is deliberately conservative. It cannot prove that an equation means
    the same thing as a sentence, but it prevents the parser from introducing
    arbitrary symbols and from silently accepting an unknown problem class.
    """

    if ir.problem_type == "unknown":
        raise IRFaithfulnessError(
            "The parser classified this problem as unknown; no Lean proof is allowed."
        )

    source_symbols = _identifiers(problem)
    allowed_symbols = source_symbols | _implicit_symbols(problem) | BUILTIN_FUNCTIONS
    invented: set[str] = set()
    for text in _ir_expression_text(ir):
        for symbol in _identifiers(text):
            if symbol in BUILTIN_FUNCTIONS:
                continue
            if not _is_allowed_symbol(symbol, allowed_symbols, ir):
                invented.add(symbol)
    if invented:
        names = ", ".join(sorted(invented))
        raise IRFaithfulnessError(
            f"IR contains symbols absent from the problem text: {names}"
        )

    if not _is_allowed_symbol(ir.target.symbol, allowed_symbols, ir):
        raise IRFaithfulnessError(
            f"IR target symbol is absent from the problem text: {ir.target.symbol}"
        )

    if not ir.equations and not ir.constraints and not ir.forces:
        raise IRFaithfulnessError("IR contains no source facts that can be verified")
