"""Structured representation of the small V1/V2 mechanics domain."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ProblemType = Literal[
    "newton_second_law",
    "free_fall",
    "inclined_plane",
    "hooke_law",
    "kinematics_1d",
    "energy_conservation",
    "projectile_1d",
    "unknown",
]

ForceType = Literal[
    "gravity",
    "normal",
    "friction",
    "spring",
    "external",
    "net_force",
    "unknown",
]


class PhysicsObject(BaseModel):
    id: str = Field(min_length=1)
    type: str = Field(default="particle", min_length=1)
    mass: str | None = None


class PhysicsForce(BaseModel):
    type: ForceType
    object: str | None = None
    expression: str | None = None
    direction: str | None = None


class PhysicsTarget(BaseModel):
    quantity: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    expression: str | None = None


class PhysicsIR(BaseModel):
    """LLM output between natural language and Lean generation."""

    schema_version: Literal["1"] = "1"
    problem_type: ProblemType
    objects: list[PhysicsObject] = Field(default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict)
    forces: list[PhysicsForce] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    equations: list[str] = Field(default_factory=list)
    target: PhysicsTarget
    notes: str = ""
