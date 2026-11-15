"""Run the evaluator with the REAL LLM (costs a small amount).

Whole dataset (7 lessons):     PYTHONPATH=backend python -m app.evaluator.cli
One lesson file:               PYTHONPATH=backend python -m app.evaluator.cli --file /tmp/lesson_preview.md
"""

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.evaluator.dataset import DATASET_PROFILE, run_dataset
from app.evaluator.engine import EvaluationRequest, LessonEvaluator
from app.evaluator.llm import LangChainLessonJudge
from app.evaluator.schemas import EvaluationReport
from app.llm.factory import build_chat_model
from app.topics.registry import match_topic


def build_evaluator() -> LessonEvaluator:
    model = build_chat_model("evaluator", temperature=0, max_tokens=get_settings().evaluator_max_tokens)
    return LessonEvaluator(LangChainLessonJudge(model))


def print_report(report: EvaluationReport) -> None:
    print(f"\nOVERALL: {report.overall_status}")
    for result in report.criteria:
        print(f"\n[{result.status}] {result.label}\n  reason: {result.reason}")
        if result.evidence:
            print(f"  evidence: \"{result.evidence[0]}\"")
        if result.improvement_instructions:
            print(f"  fix: {result.improvement_instructions}")
    print("\nCOVERAGE:")
    for concept in report.coverage:
        print(f"  [{concept.status}] {concept.title}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="Evaluate one Markdown lesson file instead of the dataset.")
    parser.add_argument("--topic", default="Introduction to RAG")
    parser.add_argument("--case", action="append", help="Run only this dataset case (repeatable).")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)  # show detailed JSON logs
    evaluator = build_evaluator()

    if args.file:
        report = evaluator.evaluate(EvaluationRequest(
            lesson_markdown=Path(args.file).read_text(), topic=args.topic,
            topic_config=match_topic(args.topic), learner_profile=DATASET_PROFILE))
        print_report(report)
        return 0

    results = run_dataset(evaluator, only=args.case)
    print(f"\n{'CASE':<20}{'EXPECTED TO FAIL':<26}{'OVERALL':<9}{'FAILED CRITERIA':<55}RESULT")
    for r in results:
        expected = ", ".join(sorted(r.case.must_fail)) or "(must PASS)"
        failed = ", ".join(r.failed_criteria) or "-"
        outcome = "OK" if r.matched else ("ERROR: " + r.error if r.error else "MISMATCH")
        print(f"{r.case.key:<20}{expected:<26}{(r.overall_status or '-'):<9}{failed:<55}{outcome}")
    matched = sum(r.matched for r in results)
    print(f"\n{matched}/{len(results)} cases matched the expected outcome.")
    return 0 if matched == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
