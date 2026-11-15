"""LangGraph lesson workflow: nodes, conditional routing, checkpoints, crash handling (fake generator)."""

from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.exceptions import LLMUnavailableError
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.generator.schemas import LessonDraft
from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc
from app.services import lessons as lesson_svc
from app.workflows.lesson_graph import LessonWorkflowDeps, build_lesson_graph, route_after_generation
from app.workflows.runner import LessonWorkflowRunner, start_lesson_run

pytestmark = pytest.mark.db
MARKDOWN = "# RAG for beginners\n\n" + "Short, simple sentences explain each idea. " * 10


@dataclass
class FakeGenerator:
    draft: LessonDraft | None = None
    error: Exception | None = None
    requests: list = field(default_factory=list)

    def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.draft


def _scope(db_session):
    @contextmanager
    def scope():
        with db_session.begin_nested():  # like a real short transaction, but inside the test's rollback
            yield db_session
    return scope


def _graph(db_session, generator, checkpointer=None):
    deps = LessonWorkflowDeps(session_scope=_scope(db_session), generator=generator)
    return build_lesson_graph(deps, checkpointer=checkpointer or InMemorySaver())


def _config(run) -> dict:
    return {"configurable": {"thread_id": str(run.id)}}


@pytest.fixture
def started(db_session, make_user):
    user = make_user()
    chat = chat_svc.create_chat(db_session, user)
    profile_svc.upsert_learner_profile(db_session, user, chat.id,
                                       {"topic": "Introduction to RAG", "education_level": "8th standard"})
    profile_svc.confirm_learner_profile(db_session, user, chat.id)
    chat.status = "generating"
    run = start_lesson_run(db_session, user, chat.id)
    return user, chat, run


def test_successful_generation_saves_version_1(db_session, started) -> None:
    user, chat, run = started
    generator = FakeGenerator(draft=LessonDraft(title="RAG for beginners", lesson_markdown=MARKDOWN))
    state = _graph(db_session, generator).invoke({"run_id": str(run.id), "user_id": str(user)}, _config(run))

    assert state["attempt_number"] == 1
    history = lesson_svc.get_lesson_run_history(db_session, user, run.id)
    assert [a.version.content for a in history.attempts] == [MARKDOWN]
    assert history.run.attempt_count == 1
    assert chat_svc.list_messages(db_session, user, chat.id)[-1].kind == "lesson_draft"


def test_generator_receives_profile_topic_config_and_active_prompt(db_session, started) -> None:
    user, _, run = started
    generator = FakeGenerator(draft=LessonDraft(title="RAG", lesson_markdown=MARKDOWN))
    _graph(db_session, generator).invoke({"run_id": str(run.id), "user_id": str(user)}, _config(run))
    request = generator.requests[0]
    assert request.topic_config.key == "intro_to_rag"
    assert request.learner_profile["education_level"] == "8th standard"
    assert request.instructions == DEFAULT_GENERATOR_INSTRUCTIONS


def test_llm_failure_is_a_technical_error_not_a_rejection(db_session, started) -> None:
    user, chat, run = started
    generator = FakeGenerator(error=LLMUnavailableError("The AI service is temporarily unavailable."))
    state = _graph(db_session, generator).invoke({"run_id": str(run.id), "user_id": str(user)}, _config(run))

    assert state["error"]
    db_session.expire_all()
    assert lesson_svc.get_lesson_run(db_session, user, run.id).status == "error"
    assert chat_svc.get_chat(db_session, user, chat.id).status == "failed"
    assert lesson_svc.get_lesson_run_history(db_session, user, run.id).attempts == []
    last = chat_svc.list_messages(db_session, user, chat.id)[-1]
    assert last.kind == "lesson_error" and "not a judgement" in last.content


def test_routing_after_generation() -> None:
    assert route_after_generation({"error": "API down"}) == "mark_error"
    assert route_after_generation({"error": None}) == "save_version"
    assert route_after_generation({}) == "save_version"


def test_state_is_checkpointed_per_run(db_session, started) -> None:
    user, _, run = started
    saver = InMemorySaver()
    graph = _graph(db_session, FakeGenerator(draft=LessonDraft(title="RAG", lesson_markdown=MARKDOWN)), saver)
    graph.invoke({"run_id": str(run.id), "user_id": str(user)}, _config(run))
    snapshot = graph.get_state(_config(run))
    assert snapshot.values["lesson_version_id"]
    assert snapshot.next == ()  # finished: no node pending


def test_runner_records_unexpected_crash_as_technical_failure(db_session, started) -> None:
    user, chat, run = started

    class ExplodingGraph:
        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("bug")

    LessonWorkflowRunner(ExplodingGraph(), session_scope=_scope(db_session)).run(run.id, user)
    db_session.expire_all()
    assert lesson_svc.get_lesson_run(db_session, user, run.id).status == "error"
    assert chat_svc.get_chat(db_session, user, chat.id).status == "failed"
