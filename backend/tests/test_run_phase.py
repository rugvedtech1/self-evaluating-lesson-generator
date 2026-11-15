"""What the learner sees while a run is in progress, derived from stored data."""

import pytest

from app.services.lessons import run_phase


@pytest.mark.parametrize(("status", "versions", "evaluations", "expected"), [
    ("running", 0, 0, ("writing", 1)),
    ("running", 1, 0, ("evaluating", 1)),
    ("running", 1, 1, ("improving", 2)),
    ("running", 3, 2, ("evaluating", 3)),
    ("approved", 2, 2, ("approved", 2)),
    ("rejected", 3, 3, ("rejected", 3)),
])
def test_run_phase(status: str, versions: int, evaluations: int, expected: tuple[str, int]) -> None:
    assert run_phase(status, versions, evaluations, max_attempts=3) == expected
