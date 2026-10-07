"""Run a labeled answer set through the direct and Physics IR pipelines."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .check_answer import AnswerCheckResult, check_answer


DEFAULT_CASES = Path(__file__).resolve().parents[2] / "benchmarks" / "mechanics_v1.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPORT_SCHEMA_VERSION = "1"
PipelineName = Literal["direct", "ir"]


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    expected_correct: bool
    rationale: str = Field(min_length=1)


class BenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "BenchmarkSuite":
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark case ids must be unique")
        return self


def load_suite(path: str | Path) -> BenchmarkSuite:
    """Parse a labeled JSON suite before making any model requests."""

    return BenchmarkSuite.model_validate_json(Path(path).read_text(encoding="utf-8"))


def summarize(rows: list[dict[str, object]], pipelines: tuple[PipelineName, ...]) -> dict[str, dict[str, object]]:
    """Keep incorrect verification and operational errors separate."""

    summary: dict[str, dict[str, object]] = {}
    for pipeline in pipelines:
        selected = [row for row in rows if row["pipeline"] == pipeline]
        counts = {
            label: sum(row["classification"] == label for row in selected)
            for label in ("true_positive", "true_negative", "false_positive", "false_negative", "error")
        }
        decided = len(selected) - counts["error"]
        correct = counts["true_positive"] + counts["true_negative"]
        summary[pipeline] = {
            "total": len(selected),
            "counts": counts,
            "accuracy_all_cases": correct / len(selected) if selected else None,
            "accuracy_decided_cases": correct / decided if decided else None,
            "decision_rate": decided / len(selected) if selected else None,
            "duration_seconds": round(sum(float(row["duration_seconds"]) for row in selected), 3),
        }
    return summary


def summarize_by_domain(
    rows: list[dict[str, object]], pipelines: tuple[PipelineName, ...]
) -> dict[str, dict[str, dict[str, object]]]:
    """Expose per-domain counts so a small suite cannot hide one weak topic."""

    domains = sorted({str(row["domain"]) for row in rows})
    return {
        domain: summarize(
            [row for row in rows if row["domain"] == domain], pipelines
        )
        for domain in domains
    }


def _command_version(command: list[str], cwd: Path) -> str | None:
    """Return a short local tool version without turning metadata into a gate."""

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output or None


def _git_sha() -> str | None:
    return _command_version(["git", "rev-parse", "HEAD"], REPOSITORY_ROOT)


def _suite_metadata(source: str | Path | None) -> dict[str, str | None]:
    if source is None:
        return {"path": None, "sha256": None}
    path = Path(source).resolve()
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        digest = None
    return {"path": str(path), "sha256": digest}


def _run_metadata(
    *,
    suite_source: str | Path | None,
    project_dir: str | Path,
    model: str | None,
    max_repairs: int,
    pipelines: tuple[PipelineName, ...],
) -> dict[str, object]:
    lean_dir = Path(project_dir).resolve()
    try:
        package_version = importlib.metadata.version("veriphys")
    except importlib.metadata.PackageNotFoundError:
        package_version = None
    try:
        toolchain = (lean_dir / "lean-toolchain").read_text(encoding="utf-8").strip()
    except OSError:
        toolchain = None
    return {
        "git_sha": _git_sha(),
        "veriphys_version": package_version,
        "python_version": sys.version.split()[0],
        "lean_version": _command_version(["lake", "env", "lean", "--version"], lean_dir),
        "lean_toolchain": toolchain,
        "api_mode": os.getenv("VERIPHYS_API_MODE", "chat").lower(),
        "api_base_url_configured": bool(os.getenv("OPENAI_BASE_URL")),
        "model": model or os.getenv("VERIPHYS_MODEL", "gpt-6-astra"),
        "max_repairs": max_repairs,
        "pipelines": list(pipelines),
        "suite": _suite_metadata(suite_source),
    }


def run_benchmark(
    suite: BenchmarkSuite,
    *,
    pipelines: tuple[PipelineName, ...] = ("direct", "ir"),
    project_dir: str | Path = "lean",
    model: str | None = None,
    max_repairs: int = 0,
    suite_source: str | Path | None = None,
    checker: Callable[..., AnswerCheckResult] = check_answer,
) -> dict[str, object]:
    """Run each case through each pipeline and retain the full proof evidence."""

    if not pipelines or len(set(pipelines)) != len(pipelines):
        raise ValueError("pipelines must be nonempty and unique")
    if any(pipeline not in ("direct", "ir") for pipeline in pipelines):
        raise ValueError("pipelines may contain only direct and ir")
    if max_repairs not in range(4):
        raise ValueError("max_repairs must be between 0 and 3")

    rows: list[dict[str, object]] = []
    for case in suite.cases:
        for pipeline in pipelines:
            started = time.perf_counter()
            try:
                result = checker(
                    case.problem,
                    case.answer,
                    project_dir=project_dir,
                    model=model,
                    use_ir=pipeline == "ir",
                    max_repairs=max_repairs,
                )
                result_data = result.to_dict()
                raw_status = result.status
                status = raw_status
                if status not in {"verified", "rejected", "error"}:
                    status = "error"
                    result_data["benchmark_error"] = (
                        f"Checker returned unsupported status: {raw_status}"
                    )
                if status == "verified" and not result.lean_verified:
                    status = "error"
                    result_data["benchmark_error"] = (
                        "Checker reported verified without a successful Lean verification."
                    )
                elif status == "rejected" and result.lean_verified:
                    status = "error"
                    result_data["benchmark_error"] = (
                        "Checker reported rejected despite a successful Lean verification."
                    )
                if status != raw_status:
                    result_data["raw_status"] = raw_status
                    result_data["status"] = status
            except Exception as exc:
                status = "error"
                result_data = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            duration = round(time.perf_counter() - started, 3)
            if status == "verified":
                classification = "true_positive" if case.expected_correct else "false_positive"
            elif status == "rejected":
                classification = "false_negative" if case.expected_correct else "true_negative"
            else:
                classification = "error"
            rows.append(
                {
                    "case_id": case.id,
                    "domain": case.domain,
                    "problem": case.problem,
                    "answer": case.answer,
                    "expected_correct": case.expected_correct,
                    "rationale": case.rationale,
                    "pipeline": pipeline,
                    "observed_status": status,
                    "classification": classification,
                    "duration_seconds": duration,
                    "result": result_data,
                }
            )

    return {
        "suite": suite.name,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "suite_description": suite.description,
        "case_count": len(suite.cases),
        "model": model or os.getenv("VERIPHYS_MODEL", "gpt-6-astra"),
        "max_repairs": max_repairs,
        "pipelines": list(pipelines),
        "metadata": _run_metadata(
            suite_source=suite_source,
            project_dir=project_dir,
            model=model,
            max_repairs=max_repairs,
            pipelines=pipelines,
        ),
        "summary": summarize(rows, pipelines),
        "summary_by_domain": summarize_by_domain(rows, pipelines),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare VeriPhys pipelines on labeled cases")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--project-dir", type=Path, default=Path("lean"))
    parser.add_argument("--model", help="model override; otherwise VERIPHYS_MODEL")
    parser.add_argument("--max-repairs", type=int, choices=range(4), default=0)
    parser.add_argument("--pipelines", nargs="+", choices=("direct", "ir"), default=["direct", "ir"])
    parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    parser.add_argument("--validate-only", action="store_true", help="check labels and schema without API calls")
    parser.add_argument(
        "--fail-on-misclassification",
        action="store_true",
        help="return nonzero when any false positive or false negative occurs",
    )
    args = parser.parse_args()

    suite = load_suite(args.cases)
    if args.validate_only:
        print(json.dumps({"suite": suite.name, "cases": len(suite.cases)}, indent=2))
        return 0
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is not set; use --validate-only for an offline check")

    report = run_benchmark(
        suite,
        pipelines=tuple(args.pipelines),
        project_dir=args.project_dir,
        model=args.model,
        max_repairs=args.max_repairs,
        suite_source=args.cases,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"Report: {args.output}")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    else:
        print(encoded)
    has_errors = any(item["counts"]["error"] for item in report["summary"].values())
    has_misclassification = any(
        item["counts"][label]
        for item in report["summary"].values()
        for label in ("false_positive", "false_negative")
    )
    return 1 if has_errors or (args.fail_on_misclassification and has_misclassification) else 0


if __name__ == "__main__":
    raise SystemExit(main())
