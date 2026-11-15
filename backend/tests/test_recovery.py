"""Startup recovery: unfinished runs are found and resumed (each with its own user)."""

from contextlib import contextmanager

import pytest

from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc
from app.services import lessons as lesson_svc
from app.workflows.recovery import find_interrupted_runs, recover_interrupted_runs
from app.workflows.runner import start_lesson_run

pytestmark = pytest.mark.db


def _scope(db_session):
    @contextmanager
    def scope():
        with db_session.begin_nested():
            yield db_session
    return scope


def _run(db_session, make_user):
    user = make_user()
    chat = chat_svc.create_chat(db_session, user)
    profile_svc.upsert_learner_profile(db_session, user, chat.id, {"topic": "Introduction to RAG"})
    profile_svc.confirm_learner_profile(db_session, user, chat.id)
    chat.status = "generating"
    return user, start_lesson_run(db_session, user, chat.id)


def test_only_unfinished_runs_are_found(db_session, make_user) -> None:
    user_a, running = _run(db_session, make_user)
    user_b, finished = _run(db_session, make_user)
    lesson_svc.finish_lesson_run(db_session, user_b, finished.id, status="approved", final_attempt_number=1)
    assert find_interrupted_runs(db_session) == [(running.id, user_a)]


def test_recovery_resumes_each_unfinished_run(db_session, make_user) -> None:
    user, run = _run(db_session, make_user)

    class FakeRunner:
        def __init__(self) -> None:
            self.resumed = []

        def resume(self, run_id, user_id) -> None:
            self.resumed.append((run_id, user_id))

    runner = FakeRunner()
    assert recover_interrupted_runs(runner, session_scope=_scope(db_session)) == 1
    assert runner.resumed == [(run.id, user)]
