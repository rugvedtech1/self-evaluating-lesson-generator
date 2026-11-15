"""Lesson storage: ownership, sequential attempts (max 3), evaluation consistency, history."""

import pytest

from app.core.exceptions import InvalidOperationError, NotFoundError
from app.services import chats as chat_svc
from app.services import lessons as svc

pytestmark = pytest.mark.db

PASS_RESULTS = [{"criterion": "accuracy", "status": "PASS"}]
FAIL_RESULTS = [{"criterion": "jargon", "status": "FAIL"}]


@pytest.fixture
def alice_run(db_session, make_user):
    alice = make_user()
    chat = chat_svc.create_chat(db_session, alice)
    return alice, svc.create_lesson_run(db_session, alice, chat.id, topic="Introduction to RAG")


def test_cannot_create_run_in_other_users_chat(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    bobs_chat = chat_svc.create_chat(db_session, bob)
    with pytest.raises(NotFoundError):
        svc.create_lesson_run(db_session, alice, bobs_chat.id, topic="x")


def test_attempts_are_sequential_and_capped_at_three(db_session, alice_run) -> None:
    alice, run = alice_run
    numbers = [svc.add_lesson_version(db_session, alice, run.id, content=f"v{i}").attempt_number
               for i in range(3)]
    assert numbers == [1, 2, 3]
    with pytest.raises(InvalidOperationError, match="Maximum"):
        svc.add_lesson_version(db_session, alice, run.id, content="v4")


def test_other_user_cannot_add_version(db_session, alice_run, make_user) -> None:
    _, run = alice_run
    with pytest.raises(NotFoundError):
        svc.add_lesson_version(db_session, make_user(), run.id, content="intruder")


def test_finished_run_accepts_no_more_versions(db_session, alice_run) -> None:
    alice, run = alice_run
    run.status = "approved"
    db_session.flush()
    with pytest.raises(InvalidOperationError, match="finished"):
        svc.add_lesson_version(db_session, alice, run.id, content="late")


@pytest.mark.parametrize(
    ("status", "failed"),
    [("PASS", ["jargon"]), ("FAIL", []), ("MAYBE", ["jargon"])],
)
def test_inconsistent_evaluations_rejected(db_session, alice_run, status, failed) -> None:
    alice, run = alice_run
    version = svc.add_lesson_version(db_session, alice, run.id, content="v1")
    with pytest.raises(ValueError):
        svc.add_evaluation(db_session, alice, version.id, overall_status=status,
                           criteria_results=FAIL_RESULTS, failed_criteria=failed)


def test_other_user_cannot_evaluate_version(db_session, alice_run, make_user) -> None:
    alice, run = alice_run
    version = svc.add_lesson_version(db_session, alice, run.id, content="v1")
    with pytest.raises(NotFoundError):
        svc.add_evaluation(db_session, make_user(), version.id, overall_status="PASS",
                           criteria_results=PASS_RESULTS, failed_criteria=[])


def test_history_pairs_each_attempt_with_its_evaluation(db_session, alice_run) -> None:
    alice, run = alice_run
    v1 = svc.add_lesson_version(db_session, alice, run.id, content="v1")
    svc.add_evaluation(db_session, alice, v1.id, overall_status="FAIL", criteria_results=FAIL_RESULTS,
                       failed_criteria=["jargon"], feedback_for_generator="Explain 'embedding'.")
    v2 = svc.add_lesson_version(db_session, alice, run.id, content="v2",
                                generator_feedback="Explain 'embedding'.", change_summary="Added definitions.")
    svc.add_evaluation(db_session, alice, v2.id, overall_status="PASS",
                       criteria_results=PASS_RESULTS, failed_criteria=[])

    history = svc.get_lesson_run_history(db_session, alice, run.id)
    assert [a.version.attempt_number for a in history.attempts] == [1, 2]
    assert [a.evaluation.overall_status for a in history.attempts] == ["FAIL", "PASS"]
    assert history.attempts[1].version.change_summary == "Added definitions."
