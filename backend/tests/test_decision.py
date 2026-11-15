"""The Python Decision Gate: the complete decision table."""

import pytest

from app.workflows.decision import decide


@pytest.mark.parametrize(("status", "attempt", "max_attempts", "expected"), [
    ("PASS", 1, 3, "approve"),
    ("PASS", 3, 3, "approve"),
    ("FAIL", 1, 3, "regenerate"),
    ("FAIL", 2, 3, "regenerate"),
    ("FAIL", 3, 3, "reject"),
    ("PASS", 4, 3, "reject"),   # never approve beyond the limit
])
def test_decision_table(status: str, attempt: int, max_attempts: int, expected: str) -> None:
    assert decide(status, attempt, max_attempts) == expected


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide("MOSTLY_PASS", 1, 3)
