# VeriPhys

**VeriPhys** is a small neuro-symbolic physics prototype. It translates a
classical-mechanics problem into a Lean 4 theorem and uses the Lean compiler as
the final verifier.

## Current milestone: V2 prototype

The prototype now has the complete verification loop:

1. ask an LLM to extract a Physics IR and generate Lean source;
2. reject unsafe generated source;
3. compile the source locally with Lean;
4. optionally send compiler diagnostics to a bounded repair loop;
5. capture the final result as structured data.

The first supported domain is one-dimensional algebraic mechanics. Physical
quantities are plain `Real` values for now; units and vectors are later work.

## Repository layout

```text
veriphys/
├── src/veriphys/
│   ├── cli.py             # command-line entry point
│   ├── lean_verifier.py   # Python -> Lean compiler bridge
│   ├── parser.py          # problem -> Physics IR
│   ├── lean_generator.py  # Physics IR -> Lean
│   ├── repair.py          # bounded compiler-feedback repair
│   └── check_answer.py    # end-to-end CLI
├── lean/
│   ├── lakefile.lean
│   ├── lean-toolchain
│   └── VeriPhys/
│       ├── Basic.lean
│       └── Examples.lean
└── scripts/demo_verifier.py
```

## Setup

Install Lean 4 through the official `elan` tool, then fetch Mathlib:

```bash
cd lean
lake update
lake build VeriPhys
lake env lean VeriPhys/Examples.lean
```

From the repository root, run the Python demo:

```bash
PYTHONPATH=src python3 scripts/demo_verifier.py
```

Expected result after Lean is installed:

```text
Lean Verification: PASS
```

To see the failure path, run:

```bash
PYTHONPATH=src python3 -m veriphys.cli --example failure
```

## Configure and verify a candidate answer

Install the Python dependencies into the project environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Set the OpenAI key in your shell. Do not put it in source files:

```bash
export OPENAI_API_KEY="your_api_key_here"
export VERIPHYS_MODEL="gpt-6-astra"
```

For an OpenAI-compatible relay, set the exact base URL, wire mode, and model
name that the relay exposes. The value must be a plain URL, without Markdown
link syntax:

```bash
export OPENAI_BASE_URL="https://your-relay.example"
export VERIPHYS_API_MODE="responses"
export VERIPHYS_MODEL="the-model-name-from-your-relay"
```

The default `chat` mode uses `/v1/chat/completions`, which is supported by most
relay services. Set `VERIPHYS_API_MODE=responses` only when the endpoint
explicitly supports the OpenAI Responses API.

Then check a candidate answer:

```bash
.venv/bin/python -m veriphys.check_answer \
  --problem "A body has mass m and force F. Given F = m*a, check a = F/m." \
  --answer "a = F/m"
```

The checker asks the model for a structured Lean formalization, rejects unsafe
generated code, and lets the local Lean compiler decide whether the candidate is
`VERIFIED` or `REJECTED`. The model never gets to mark an answer as verified by
itself.

## Physics IR stage

The next stage is available as a separate parser so it can be inspected before
it is connected to Lean generation:

```bash
.venv/bin/python -m veriphys.parse_ir \
  --problem "A block of mass m slides down a frictionless incline of angle theta. Find its acceleration." \
  --answer "a = g * sin(theta)"
```

The parser returns a validated object containing the problem type, objects,
parameters, forces, constraints, equations, and target. The answer checker can
run this IR through Lean generation with `--use-ir`.

For scalar algebraic IR, the checker builds an independent Lean proof contract
from the IR premises and candidate answer. The model's theorem must prove that
contract before an IR run can return `VERIFIED`. This rejects proofs that put
the answer in a new hypothesis or change the theorem conclusion. The JSON
fields `proof_contract_verified` and `proof_contract_premises` expose this
check and the premises it used. The direct pipeline remains the unconstrained
baseline for comparison.

To run the IR pipeline end to end:

```bash
.venv/bin/python -m veriphys.check_answer --use-ir \
  --problem "A block of mass m slides down a frictionless incline of angle theta. Find its acceleration." \
  --answer "a = g * sin(theta)"
```

Use `--json` to save the IR, generated Lean, assumptions, and verification
status as one machine-readable result.

If the first Lean proof does not compile, enable up to three compiler-feedback
repairs explicitly:

```bash
.venv/bin/python -m veriphys.check_answer --use-ir --max-repairs 3 --json \
  --problem "A body has mass m and force F. Given F = m*a, check a = F/m." \
  --answer "a = F/m"
```

The JSON result then includes `repair_attempts` and `attempt_history`. Every
repaired file passes the same import and forbidden-token checks before it is
sent to Lean. The default is `--max-repairs 0`, so an ordinary run remains a
single formalization and verification attempt.

## Labeled benchmark

The first comparison set is [benchmarks/mechanics_v1.json](benchmarks/mechanics_v1.json).
It contains eight introductory mechanics checks, split evenly between correct
and incorrect candidate answers. Validate its schema without making API calls:

```bash
.venv/bin/python -m veriphys.benchmark --validate-only
```

Run both pipelines against the configured model and keep the full report
locally. This makes 16 initial model runs; enabling repairs can make more.

```bash
.venv/bin/python -m veriphys.benchmark --output work/benchmark-report.json
```

Use `--pipelines direct` or `--pipelines ir` to run one path, and
`--max-repairs 3` to measure the repair-enabled version. The report retains
each problem, expected label, generated Lean, compiler result, repair history,
duration, and a separate count for false positives, false negatives, and
operational errors. `accuracy_all_cases` counts errors as failures;
`accuracy_decided_cases` excludes them. A Lean proof can still formalize the
wrong physical assumptions, so inspect false positives and theorem hypotheses
before drawing conclusions about correctness.

The proof contract currently accepts scalar arithmetic with `+`, `-`, `*`,
`/`, integer powers, and comparisons. Expressions outside this subset return
an error rather than silently bypassing the check. It does not establish that
the LLM's Physics IR faithfully represents the natural-language problem; that
is a separate validation stage.

## Next milestones

- **Done:** direct problem -> Lean generation with a model SDK.
- **Done:** bounded compiler-feedback repair loop (maximum three attempts).
- **Done:** natural language -> validated Physics IR -> Lean for the current
  introductory mechanics templates.
- **Done:** a labeled benchmark runner for direct versus IR comparison.
- **Done:** an IR proof contract that checks the generated theorem against IR
  premises and the candidate conclusion in Lean.
- **Next:** run the benchmark with the configured model, inspect false
  positives, validate IR faithfulness, expand coverage, and build a user-facing
  interface.

The project will not claim a theorem is meaningful merely because it compiles:
the eventual pipeline must also reject hidden assumptions, new axioms, and
theorems that do not faithfully represent the original problem.
