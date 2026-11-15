"""Schema, constraint and row-level-security tests against a real (local Docker) Postgres."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Chat, Evaluation, LessonRun, LessonVersion, Message, Profile, PromptVersion,
)

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "profiles", "chats", "messages", "chat_profiles", "lesson_runs",
    "lesson_versions", "evaluations", "failure_patterns", "prompt_versions",
}
MakeUser = Callable[..., uuid.UUID]


# ------------------------------------------------------------------ helpers
def _chat(db: Session, user_id: uuid.UUID, **kwargs) -> Chat:
    chat = Chat(user_id=user_id, **kwargs)
    db.add(chat)
    db.flush()
    return chat


def _run(db: Session, user_id: uuid.UUID, **kwargs) -> LessonRun:
    chat = _chat(db, user_id)
    run = LessonRun(chat_id=chat.id, user_id=user_id, topic="Introduction to RAG", **kwargs)
    db.add(run)
    db.flush()
    return run


def _act_as(db: Session, role: str, user_id: uuid.UUID | None = None) -> None:
    """Switch to a Supabase API role for the rest of this test's transaction."""
    db.execute(text(f"SET LOCAL ROLE {role}"))
    db.execute(text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
               {"sub": str(user_id) if user_id else ""})


# ------------------------------------------------------------- structure
def test_all_tables_exist(migrated_engine: Engine) -> None:
    assert EXPECTED_TABLES <= set(inspect(migrated_engine).get_table_names(schema="public"))


def test_rls_enabled_on_every_table(db_session: Session) -> None:
    rows = db_session.execute(text(
        "SELECT c.relname, c.relrowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r'"
    )).all()
    rls = dict(rows)
    for table in EXPECTED_TABLES | {"alembic_version"}:
        assert rls[table] is True, f"RLS disabled on {table}"


# ------------------------------------------------- integrity & cascades
def test_profile_requires_existing_auth_user(db_session: Session) -> None:
    db_session.add(Profile(id=uuid.uuid4(), email="ghost@example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_auth_user_cascades_to_their_data(db_session: Session, make_user: MakeUser) -> None:
    user = make_user()
    chat = _chat(db_session, user)
    db_session.add(Message(chat_id=chat.id, user_id=user, role="user", content="hello"))
    db_session.flush()

    db_session.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": user})
    db_session.expire_all()

    for model, column in ((Profile, Profile.id), (Chat, Chat.user_id), (Message, Message.user_id)):
        count = db_session.scalar(select(func.count()).select_from(model).where(column == user))
        assert count == 0, f"{model.__name__} rows survived user deletion"


def test_invalid_chat_status_rejected(db_session: Session, make_user: MakeUser) -> None:
    db_session.add(Chat(user_id=make_user(), status="dancing"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_invalid_message_role_rejected(db_session: Session, make_user: MakeUser) -> None:
    user = make_user()
    chat = _chat(db_session, user)
    db_session.add(Message(chat_id=chat.id, user_id=user, role="hacker", content="x"))
    with pytest.raises(IntegrityError):
        db_session.flush()


# --------------------------------------------- business rules in the DB
def test_max_attempts_cannot_exceed_three(db_session: Session, make_user: MakeUser) -> None:
    with pytest.raises(IntegrityError):
        _run(db_session, make_user(), max_attempts=4)


def test_attempt_number_cannot_exceed_three(db_session: Session, make_user: MakeUser) -> None:
    user = make_user()
    run = _run(db_session, user)
    db_session.add(LessonVersion(run_id=run.id, user_id=user, attempt_number=4, content="x"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_attempt_number_rejected(db_session: Session, make_user: MakeUser) -> None:
    user = make_user()
    run = _run(db_session, user)
    db_session.add(LessonVersion(run_id=run.id, user_id=user, attempt_number=1, content="v1"))
    db_session.flush()
    db_session.add(LessonVersion(run_id=run.id, user_id=user, attempt_number=1, content="v1 again"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_evaluation_status_must_be_pass_or_fail(db_session: Session, make_user: MakeUser) -> None:
    user = make_user()
    run = _run(db_session, user)
    version = LessonVersion(run_id=run.id, user_id=user, attempt_number=1, content="v1")
    db_session.add(version)
    db_session.flush()
    db_session.add(Evaluation(lesson_version_id=version.id, run_id=run.id, user_id=user,
                              overall_status="MOSTLY_PASS"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_active_prompt_per_component(db_session: Session) -> None:
    db_session.add(PromptVersion(component="generator", version=1, content="v1", status="active"))
    db_session.flush()
    db_session.add(PromptVersion(component="generator", version=2, content="v2", status="active"))
    with pytest.raises(IntegrityError):
        db_session.flush()


# ------------------------------------------------------ row-level security
def test_rls_user_sees_only_own_chats(db_session: Session, make_user: MakeUser) -> None:
    alice, bob = make_user(), make_user()
    _chat(db_session, alice, title="Alice's chat")
    _chat(db_session, bob, title="Bob's chat")

    _act_as(db_session, "authenticated", alice)
    titles = db_session.execute(text("SELECT title FROM public.chats")).scalars().all()
    assert titles == ["Alice's chat"]


def test_rls_blocks_creating_rows_for_another_user(db_session: Session, make_user: MakeUser) -> None:
    alice, bob = make_user(), make_user()
    _act_as(db_session, "authenticated", alice)
    with pytest.raises(DBAPIError, match="row-level security"):
        with db_session.begin_nested():
            db_session.execute(text("INSERT INTO public.chats (user_id, title) VALUES (:uid, 'sneaky')"),
                               {"uid": bob})


def test_rls_anonymous_sees_nothing(db_session: Session, make_user: MakeUser) -> None:
    _chat(db_session, make_user(), title="private")
    _act_as(db_session, "anon")
    assert db_session.execute(text("SELECT count(*) FROM public.chats")).scalar() == 0


def test_rls_system_tables_hidden_from_users(db_session: Session, make_user: MakeUser) -> None:
    alice = make_user()
    db_session.add(PromptVersion(component="generator", version=1, content="secret prompt", status="active"))
    db_session.flush()
    _act_as(db_session, "authenticated", alice)
    assert db_session.execute(text("SELECT count(*) FROM public.prompt_versions")).scalar() == 0
