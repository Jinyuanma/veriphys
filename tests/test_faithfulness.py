"""Tests for the conservative IR source-symbol gate."""

import unittest

from veriphys.faithfulness import IRFaithfulnessError, audit_ir_faithfulness
from veriphys.physics_ir import PhysicsIR


def make_ir(**updates: object) -> PhysicsIR:
    values: dict[str, object] = {
        "problem_type": "newton_second_law",
        "objects": [{"id": "body", "mass": "m"}],
        "equations": ["F = m*a"],
        "target": {
            "quantity": "acceleration",
            "symbol": "a",
            "expression": "F/m",
        },
    }
    values.update(updates)
    return PhysicsIR.model_validate(values)


class FaithfulnessTests(unittest.TestCase):
    def test_accepts_symbols_stated_in_problem(self) -> None:
        audit_ir_faithfulness(
            "A body has mass m, force F, and acceleration a with F = m*a.",
            make_ir(),
        )

    def test_accepts_conventional_symbols_implied_by_words(self) -> None:
        audit_ir_faithfulness(
            "A body of mass 2 kg experiences force 10 N and has acceleration.",
            make_ir(equations=["F = m*a", "m = 2", "F = 10"]),
        )

    def test_ignores_force_direction_metadata(self) -> None:
        ir = make_ir(
            forces=[
                {
                    "type": "net_force",
                    "object": "body",
                    "expression": "F",
                    "direction": "unspecified",
                }
            ]
        )
        audit_ir_faithfulness("A body has mass m, force F, and acceleration a.", ir)

    def test_accepts_incline_component_symbols(self) -> None:
        audit_ir_faithfulness(
            "A block of mass m slides down an incline of angle theta under gravity g.",
            make_ir(
                problem_type="inclined_plane",
                parameters={"angle": "theta", "gravity": "g"},
                equations=["F_parallel = m*g*sin(theta)", "F_parallel = m*a"],
            ),
        )

    def test_accepts_projectile_coordinate_symbols(self) -> None:
        audit_ir_faithfulness(
            "A projectile is launched with speed v0 at angle theta; find position at time t.",
            make_ir(
                problem_type="projectile_1d",
                equations=["x = v0*cos(theta)*t", "y = v0*sin(theta)*t - g*t^2/2"],
                target={
                    "quantity": "position",
                    "symbol": "y",
                    "expression": "v0*sin(theta)*t - g*t^2/2",
                },
            ),
        )

    def test_rejects_unknown_problem_type(self) -> None:
        with self.assertRaisesRegex(IRFaithfulnessError, "unknown"):
            audit_ir_faithfulness(
                "A body has mass m and force F.", make_ir(problem_type="unknown")
            )

    def test_rejects_invented_expression_symbol(self) -> None:
        with self.assertRaisesRegex(IRFaithfulnessError, "absent"):
            audit_ir_faithfulness(
                "A body has mass m, force F, and acceleration a.",
                make_ir(equations=["F = m*a + invented"]),
            )

    def test_rejects_ir_without_source_facts(self) -> None:
        with self.assertRaisesRegex(IRFaithfulnessError, "no source facts"):
            audit_ir_faithfulness(
                "A body has mass m, force F, and acceleration a.",
                make_ir(equations=[], forces=[], constraints=[]),
            )


if __name__ == "__main__":
    unittest.main()
