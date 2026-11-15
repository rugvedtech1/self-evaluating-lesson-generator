"""OPTIONAL live run of the whole evaluation dataset (7 real evaluations, about $0.03). Skipped by default.

Run with:  RUN_LIVE_LLM_TESTS=1 pytest backend/tests/test_evaluator_live.py -v -s
"""

import os

import pytest

from app.evaluator.cli import build_evaluator
from app.evaluator.dataset import run_dataset

pytestmark = pytest.mark.live


def test_evaluator_matches_manually_reviewed_expectations() -> None:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to call the real LLM (costs a small amount).")
    results = run_dataset(build_evaluator())
    for r in results:
        print(f"{r.case.key:<20} expected={sorted(r.case.must_fail) or 'PASS'} "
              f"got={r.overall_status} failed={list(r.failed_criteria)} -> {'OK' if r.matched else 'MISMATCH'}"
              + (f" ({r.error})" if r.error else ""))
    assert all(r.matched for r in results)
