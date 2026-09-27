"""Build a Lean proof obligation from the algebraic part of Physics IR."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .physics_ir import PhysicsIR


class ProofContractError(ValueError):
    """The candidate or IR is outside the current algebraic contract domain."""


def _parse(value: str) -> ast.AST:
    normalized = value.replace("≠", "!=").replace("≤", "<=").replace("≥", ">=")
    normalized = re.sub(r"(?<![!<>=])=(?!=)", "==", normalized)
    try:
        return ast.parse(normalized, mode="eval").body
    except SyntaxError as exc:
        raise ProofContractError(f"Unsupported algebraic expression: {value}") from exc


def _render_expr(node: ast.AST, variables: set[str], denominators: set[str]) -> str:
    if isinstance(node, ast.Name):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id):
            raise ProofContractError(f"Unsupported variable name: {node.id}")
        variables.add(node.id)
        return node.id
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return str(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operator = "+" if isinstance(node.op, ast.UAdd) else "-"
        return f"({operator}{_render_expr(node.operand, variables, denominators)})"
    if isinstance(node, ast.BinOp):
        operators = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
        }
        if isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int:
                raise ProofContractError("Exponents must be integer literals")
            if node.right.value < 0:
                raise ProofContractError("Negative exponents are not yet supported")
            left = _render_expr(node.left, variables, denominators)
            return f"({left} ^ {node.right.value})"
        operator = operators.get(type(node.op))
        if operator is None:
            raise ProofContractError("Only +, -, *, /, and integer powers are supported")
        if (
            isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and node.right.value == 0
        ):
            raise ProofContractError("Division by literal zero is not a physical answer")
        left = _render_expr(node.left, variables, denominators)
        right = _render_expr(node.right, variables, denominators)
        if isinstance(node.op, ast.Div) and isinstance(node.right, ast.Name):
            denominators.add(node.right.id)
        return f"({left} {operator} {right})"
    raise ProofContractError("Only scalar algebraic expressions are supported")


def _render_relation(node: ast.AST, variables: set[str], denominators: set[str]) -> str:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        raise ProofContractError("Premises and answers must be single comparisons")
    operators = {
        ast.Eq: "=",
        ast.NotEq: "≠",
        ast.Lt: "<",
        ast.LtE: "≤",
        ast.Gt: ">",
        ast.GtE: "≥",
    }
    operator = operators.get(type(node.ops[0]))
    if operator is None:
        raise ProofContractError("Unsupported comparison operator")
    left = _render_expr(node.left, variables, denominators)
    right = _render_expr(node.comparators[0], variables, denominators)
    return f"{left} {operator} {right}"


def _is_zero_assignment(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    left, right = node.left, node.comparators[0]
    return (
        isinstance(left, ast.Name) and left.id == name
        and isinstance(right, ast.Constant) and right.value == 0
    ) or (
        isinstance(right, ast.Name) and right.id == name
        and isinstance(left, ast.Constant) and left.value == 0
    )


def _same_equality(left: ast.AST, right: ast.AST) -> bool:
    if not (
        isinstance(left, ast.Compare)
        and isinstance(right, ast.Compare)
        and len(left.ops) == len(right.ops) == 1
        and isinstance(left.ops[0], ast.Eq)
        and isinstance(right.ops[0], ast.Eq)
    ):
        return False
    left_parts = (ast.dump(left.left), ast.dump(left.comparators[0]))
    right_parts = (ast.dump(right.left), ast.dump(right.comparators[0]))
    return left_parts == right_parts or left_parts == right_parts[::-1]


@dataclass(frozen=True)
class ProofContract:
    variables: tuple[str, ...]
    premises: tuple[str, ...]
    conclusion: str

    def attach(self, generated_lean: str) -> str:
        """Require the generated theorem to prove the independently built goal."""

        names = re.findall(r"(?m)^\s*theorem\s+([A-Za-z_][A-Za-z0-9_']*)\b", generated_lean)
        if len(names) != 1:
            raise ProofContractError("Generated Lean must contain exactly one named theorem")
        binders = " ".join(f"({name} : ℝ)" for name in self.variables)
        hypotheses = " ".join(
            f"(premise_{index} : {premise})"
            for index, premise in enumerate(self.premises)
        )
        return (
            generated_lean.rstrip()
            + "\n\n"
            + f"theorem veriphys_contract {binders} {hypotheses} : {self.conclusion} := by\n"
            + f"  apply {names[0]} <;> assumption\n"
        )


def build_proof_contract(ir: PhysicsIR, candidate_answer: str) -> ProofContract:
    """Use only IR facts and a physical mass nonzero guard as premises."""

    candidate = _parse(candidate_answer)
    if (
        not isinstance(candidate, ast.Compare)
        or len(candidate.ops) != 1
        or not isinstance(candidate.ops[0], ast.Eq)
        or not isinstance(candidate.left, ast.Name)
        or candidate.left.id != ir.target.symbol
    ):
        raise ProofContractError("Candidate must be an equation for the IR target symbol")
    if not ir.target.expression:
        raise ProofContractError("IR target expression is missing")
    if ast.dump(candidate.comparators[0]) != ast.dump(_parse(ir.target.expression)):
        raise ProofContractError("IR target does not match the candidate answer")

    variables: set[str] = set()
    target_denominators: set[str] = set()
    conclusion = _render_relation(candidate, variables, target_denominators)
    premises: list[str] = []
    premise_nodes: list[ast.AST] = []
    for fact in [*ir.equations, *ir.constraints]:
        node = _parse(fact)
        relation = _render_relation(node, variables, set())
        if _same_equality(node, candidate):
            raise ProofContractError("The candidate answer appears among IR premises")
        if relation not in premises:
            premises.append(relation)
            premise_nodes.append(node)
    for name, value in ir.parameters.items():
        node = _parse(f"{name} = {value}")
        relation = _render_relation(node, variables, set())
        if _same_equality(node, candidate):
            raise ProofContractError("The candidate answer appears among IR parameters")
        if relation not in premises:
            premises.append(relation)
            premise_nodes.append(node)

    mass_symbols = {obj.mass for obj in ir.objects if obj.mass}
    for denominator in sorted(target_denominators & mass_symbols):
        if any(_is_zero_assignment(node, denominator) for node in premise_nodes):
            raise ProofContractError(f"IR sets denominator {denominator} to zero")
        nonzero = f"{denominator} ≠ 0"
        if nonzero not in premises:
            premises.append(nonzero)

    return ProofContract(tuple(sorted(variables)), tuple(premises), conclusion)
