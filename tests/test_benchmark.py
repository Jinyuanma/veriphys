"""Focused checks for benchmark labels and outcome accounting."""

import unittest

from veriphys.benchmark import (
    DEFAULT_CASES,
    BenchmarkCase,
    BenchmarkSuite,
    load_suite,
    run_benchmark,
)
from veriphys.check_answer import AnswerCheckResult


class BenchmarkTests(unittest.TestCase):
    def test_default_suite_has_balanced_labels(self) -> None:
        suite = load_suite(DEFAULT_CASES)
        self.assertEqual(len(suite.cases), 8)
        self.assertEqual(sum(case.expected_correct for case in suite.cases), 4)

    def test_duplicate_ids_are_rejected(self) -> None:
        case = BenchmarkCase(
            id="same",
            domain="newton_second_law",
            problem="F = m*a",
            answer="a = F/m",
            expected_correct=True,
            rationale="m != 0",
        )
        with self.assertRaises(ValueError):
            BenchmarkSuite(name="duplicate", cases=[case, case])

    def test_false_positives_and_errors_are_not_counted_as_success(self) -> None:
        suite = BenchmarkSuite(
            name="accounting",
            cases=[
                BenchmarkCase(
                    id="correct",
                    domain="newton_second_law",
                    problem="F = m*a and m != 0",
                    answer="a = F/m",
                    expected_correct=True,
                    rationale="divide by m",
                ),
                BenchmarkCase(
                    id="wrong",
                    domain="newton_second_law",
                    problem="F = m*a and m != 0 and F != 0",
                    answer="a = 2*F/m",
                    expected_correct=False,
                    rationale="factor of two",
                ),
            ],
        )

        def checker(problem: str, answer: str, *, use_ir: bool, **kwargs: object) -> AnswerCheckResult:
            if use_ir and answer == "a = 2*F/m":
                raise RuntimeError("relay unavailable")
            return AnswerCheckResult(
                status="rejected" if use_ir else "verified",
                problem=problem,
                candidate_answer=answer,
                lean_verified=not use_ir,
            )

        report = run_benchmark(suite, checker=checker)
        direct = report["summary"]["direct"]
        ir = report["summary"]["ir"]
        self.assertEqual(direct["counts"]["true_positive"], 1)
        self.assertEqual(direct["counts"]["false_positive"], 1)
        self.assertEqual(direct["accuracy_all_cases"], 0.5)
        self.assertEqual(ir["counts"]["false_negative"], 1)
        self.assertEqual(ir["counts"]["error"], 1)
        self.assertEqual(ir["accuracy_all_cases"], 0.0)
        self.assertEqual(ir["accuracy_decided_cases"], 0.0)
        self.assertEqual(len(report["results"]), 4)

    def test_verified_without_lean_success_is_an_error(self) -> None:
        suite = BenchmarkSuite(
            name="inconsistent",
            cases=[
                BenchmarkCase(
                    id="case",
                    domain="newton_second_law",
                    problem="F = m*a and m != 0",
                    answer="a = F/m",
                    expected_correct=True,
                    rationale="divide by m",
                )
            ],
        )

        def checker(problem: str, answer: str, **kwargs: object) -> AnswerCheckResult:
            return AnswerCheckResult(
                status="verified",
                problem=problem,
                candidate_answer=answer,
                lean_verified=False,
            )

        report = run_benchmark(suite, pipelines=("direct",), checker=checker)
        self.assertEqual(report["summary"]["direct"]["counts"]["error"], 1)
        self.assertEqual(report["results"][0]["observed_status"], "error")


if __name__ == "__main__":
    unittest.main()
