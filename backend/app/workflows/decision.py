"""Python Decision Gate: the ONLY place that decides approve / regenerate / reject. Never the LLM."""

from typing import Literal

Decision = Literal["approve", "regenerate", "reject"]


def decide(overall_status: str, attempt_number: int, max_attempts: int) -> Decision:
    if overall_status not in ("PASS", "FAIL"):
        raise ValueError(f"Unknown evaluation status: {overall_status!r}")
    if attempt_number < 1 or max_attempts < 1:
        raise ValueError("Attempt numbers start at 1.")
    if attempt_number > max_attempts:
        return "reject"  # defensive: never approve beyond the limit
    if overall_status == "PASS":
        return "approve"  # all six criteria passed (no partial credit)
    return "regenerate" if attempt_number < max_attempts else "reject"
