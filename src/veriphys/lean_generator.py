"""Generate Lean from a validated Physics IR."""

from __future__ import annotations

import json
import os

from .formalizer import FormalizerConfig, LLMConfigurationError, LLMResponseError
from .physics_ir import PhysicsIR
from .schema import LeanFormalization


GENERATOR_PROMPT = """You generate Lean 4 formalizations from a validated Physics IR.

Return JSON only with exactly these fields:
{
  "lean_code": "complete Lean source",
  "answer_expression": "the target expression",
  "assumptions": ["assumption 1"],
  "notes": ""
}

Rules:
- The theorem conclusion must express the IR target exactly.
- Use real numbers (`ℝ`) for all physical quantities.
- Use only these imports unless absolutely necessary:
  `Mathlib.Data.Real.Basic`, `Mathlib.Tactic.Linarith`, and
  `Mathlib.Tactic.NormNum`.
- Do not use the umbrella `import Mathlib`.
- Do not introduce `axiom`, `sorry`, `admit`, `unsafe`, or hidden assumptions.
- Do not put the target conclusion in the theorem assumptions.
- Translate equations and constraints from the IR into theorem hypotheses.
- Return a complete Lean file with exactly one named theorem and a proof.
- The theorem must be provable using only IR equations and constraints, plus
  a nonzero-mass guard when dividing by a physical mass. A separate Lean
  contract will check this claim.
"""


class LeanGenerationError(RuntimeError):
    """Raised when IR-to-Lean generation cannot produce a formalization."""


class IRLeanGenerator:
    """LLM-backed generator using the same relay configuration as the parser."""

    def __init__(self, config: FormalizerConfig | None = None) -> None:
        self.config = config or FormalizerConfig.from_environment()
        if not os.getenv(self.config.api_key_env):
            raise LLMConfigurationError(
                f"{self.config.api_key_env} is not set. Export your API key in the shell."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "The OpenAI SDK is not installed. Run `python3 -m pip install -e .`."
            ) from exc
        client_args: dict[str, str] = {"api_key": os.environ[self.config.api_key_env]}
        if self.config.base_url:
            client_args["base_url"] = self.config.base_url
        self._client = OpenAI(**client_args)

    def generate(self, ir: PhysicsIR) -> LeanFormalization:
        ir_json = ir.model_dump_json(indent=2)
        messages = [
            {"role": "system", "content": GENERATOR_PROMPT},
            {"role": "user", "content": f"PHYSICS IR:\n{ir_json}"},
        ]

        try:
            if self.config.api_mode == "responses":
                response = self._client.responses.parse(
                    model=self.config.model,
                    store=False,
                    input=messages,
                    text_format=LeanFormalization,
                )
                parsed = getattr(response, "output_parsed", None)
            else:
                response = self._client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                if not hasattr(response, "choices"):
                    raise LLMResponseError(
                        "The relay response is not a Chat Completions response."
                    )
                content = response.choices[0].message.content or ""
                if not content.strip():
                    raise LLMResponseError("The Lean generator returned an empty message.")
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise LLMResponseError(
                        "The Lean generator returned non-JSON output."
                    ) from exc
                parsed = LeanFormalization.model_validate(payload)
        except Exception as exc:
            if exc.__class__.__name__ == "AuthenticationError":
                raise LLMConfigurationError(
                    "The configured API endpoint rejected OPENAI_API_KEY (401)."
                ) from exc
            raise

        if parsed is None:
            raise LeanGenerationError("The generator did not return Lean formalization.")
        return parsed
