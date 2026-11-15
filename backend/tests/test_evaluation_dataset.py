"""The known evaluation dataset is well-formed (it is also the Step 7 prompt-validation set)."""

from app.evaluator.criteria import CRITERION_KEYS
from app.evaluator.dataset import CASES, GOOD_LESSON
from app.evaluator.structural import run_structural_checks


def test_dataset_has_one_good_lesson_and_six_targeted_flaws() -> None:
    assert [c.key for c in CASES][0] == "good"
    assert CASES[0].must_fail == frozenset()
    assert len(CASES) == 7
    assert len({c.key for c in CASES}) == 7
    for case in CASES[1:]:
        assert case.must_fail and case.must_fail <= set(CRITERION_KEYS)


def test_every_flawed_lesson_differs_from_the_good_one() -> None:
    assert all(case.lesson_markdown != GOOD_LESSON for case in CASES[1:])


def test_good_lesson_passes_every_structural_check() -> None:
    assert run_structural_checks(GOOD_LESSON) == []


def test_poor_flow_lesson_fails_teaching_flow_structurally() -> None:
    poor = next(c for c in CASES if c.key == "poor_flow")
    assert any(f.criterion == "teaching_flow" and f.severity == "fail"
               for f in run_structural_checks(poor.lesson_markdown))
