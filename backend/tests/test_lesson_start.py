"""Starting lesson runs: preconditions, one active run per chat, retry after technical failure."""

import pytest

from app.core.exceptions import InvalidOperationError, NotFoundError
from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc
from app.services import lessons as lesson_svc
from app.workflows.lesson_graph import record_generation_failure
from app.workflows.runner import start_lesson_run

pytestmark = pytest.mark.db


@pytest.fixture
def confirmed(db_session, make_user):
    user = make_user()
    chat = chat_svc.create_chat(db_session, user)
    profile_svc.upsert_learner_profile(db_session, user, chat.id, {"topic": "Introduction to RAG"})
    profile_svc.confirm_learner_profile(db_session, user, chat.id)
    chat.status = "generating"
    db_session.flush()
    return user, chat


def test_start_requires_confirmed_profile(db_session, make_user) -> None:
    user = make_user()
    chat = chat_svc.create_chat(db_session, user)  # still in intake
    with pytest.raises(InvalidOperationError, match="Confirm"):
        start_lesson_run(db_session, user, chat.id)


def test_start_creates_running_run_with_topic_config_and_prompt(db_session, confirmed) -> None:
    user, chat = confirmed
    run = start_lesson_run(db_session, user, chat.id)
    assert run.status == "running"
    assert run.topic_key == "intro_to_rag"
    assert run.generator_prompt_version_id is not None
    assert chat.status == "generating"


def test_cannot_start_while_a_run_is_active(db_session, confirmed) -> None:
    user, chat = confirmed
    start_lesson_run(db_session, user, chat.id)
    with pytest.raises(InvalidOperationError, match="already"):
        start_lesson_run(db_session, user, chat.id)


def test_can_retry_after_technical_failure(db_session, confirmed) -> None:
    user, chat = confirmed
    first = start_lesson_run(db_session, user, chat.id)
    record_generation_failure(db_session, user, first.id, "API down")
    second = start_lesson_run(db_session, user, chat.id)
    assert second.id != first.id
    assert lesson_svc.get_latest_lesson_run(db_session, user, chat.id).id == second.id


def test_other_users_chat_is_not_found(db_session, confirmed, make_user) -> None:
    _, chat = confirmed
    with pytest.raises(NotFoundError):
        start_lesson_run(db_session, make_user(), chat.id)
