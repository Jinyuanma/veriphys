"""Deterministic semantic checks for Physics IR."""

from __future__ import annotations

import re

from .physics_ir import PhysicsIR


class InvalidPhysicsIRError(ValueError):
    """Raised when an IR object is structurally valid but physically incomplete."""


def _equation_signature(expression: str) -> str:
    """Compare simple symbolic equations without whitespace differences."""

    return re.sub(r"\s+", "", expression).lower()


def validate_physics_ir(ir: PhysicsIR) -> PhysicsIR:
    """Validate the minimum fields needed by the supported mechanics templates."""

    object_ids = {obj.id for obj in ir.objects}
    if len(object_ids) != len(ir.objects):
        raise InvalidPhysicsIRError("objects must have unique ids")

    for force in ir.forces:
        if force.object and force.object not in object_ids:
            raise InvalidPhysicsIRError(
                f"force refers to unknown object: {force.object}"
            )

    # Store the target as an RHS expression (`F/m`), not as a duplicated
    # equation (`a = F/m`). This gives downstream Lean generation one stable
    # representation.
    target_expression = ir.target.expression
    if target_expression and "=" in target_expression:
        lhs, rhs = target_expression.split("=", 1)
        if _equation_signature(lhs) != _equation_signature(ir.target.symbol):
            raise InvalidPhysicsIRError(
                "target.expression must be an RHS expression or an equation "
                "whose left side is the target symbol"
            )
        ir = ir.model_copy(
            update={
                "target": ir.target.model_copy(update={"expression": rhs.strip()})
            }
        )

    # The candidate conclusion belongs in target, never among premises. Models
    # sometimes copy it into equations when they see the candidate answer.
    # Normalize target first so both `a = F/m` and `F/m` compare identically.
    target_equation = (
        _equation_signature(f"{ir.target.symbol} = {ir.target.expression}")
        if ir.target.expression
        else None
    )
    if target_equation:
        premise_equations = [
            equation
            for equation in ir.equations
            if _equation_signature(equation) != target_equation
        ]
        if len(premise_equations) != len(ir.equations):
            ir = ir.model_copy(update={"equations": premise_equations})

    if ir.problem_type == "inclined_plane":
        if "angle" not in ir.parameters and "theta" not in ir.parameters:
            raise InvalidPhysicsIRError(
                "inclined_plane problems require an angle or theta parameter"
            )
        if not any(obj.mass for obj in ir.objects):
            raise InvalidPhysicsIRError("inclined_plane problems require a mass")

    if ir.problem_type == "hooke_law":
        missing = [name for name in ("k", "x") if name not in ir.parameters]
        if missing:
            raise InvalidPhysicsIRError(
                "hooke_law problems require parameters: " + ", ".join(missing)
            )

    if ir.problem_type in {"newton_second_law", "free_fall"}:
        if not ir.equations and not ir.forces:
            raise InvalidPhysicsIRError(
                f"{ir.problem_type} requires at least one equation or force"
            )

    return ir
