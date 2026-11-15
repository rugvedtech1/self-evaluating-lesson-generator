"""Main conversation window: intake chat, confirmation, live lesson status, approved lesson, rejection log."""

import streamlit as st

from components.typewriter import typewriter
from services.api_client import ApiError, ChatApi, SessionExpiredError
from state import current_chat_id, end_session, pop_flash, select_chat, set_flash

WELCOME = ("Hi! 👋 I'll write you a beginner-friendly lesson on any topic.\n\n"
           "First, what would you like to learn? For example: "
           "*Introduction to RAG (Retrieval-Augmented Generation)*.")

PROFILE_LABELS = {
    "topic": "Topic",
    "education_level": "Education level",
    "english_proficiency": "English level",
    "technical_background": "Technical background",
    "ai_knowledge": "AI knowledge",
    "preferred_style": "Explanation style",
    "additional_notes": "Other notes",
}
ACTIVE_RUN_STATUSES = ("pending", "running")
PHASE_MESSAGES = {
    "writing": "✍️ Writing your lesson (attempt {a} of {m})…",
    "evaluating": "🔍 Checking quality against six criteria (attempt {a} of {m})…",
    "improving": "🔁 Improving the lesson based on the quality check (attempt {a} of {m})…",
}
_ANIMATE_MESSAGE = "animate_message_id"   # newest assistant reply to "type out" once
_ANIMATE_LESSON = "animate_version_id"    # newly approved lesson to "type out" once


def _show(text: str, animate: bool) -> None:
    if animate:
        st.write_stream(typewriter(text))
    else:
        st.markdown(text)


def render_chat(api: ChatApi) -> None:
    if flash := pop_flash():
        st.warning(flash)

    chat_id = current_chat_id()
    if chat_id is None:
        _render_new_chat(api)
        return

    try:
        detail = api.get_chat(chat_id)
    except SessionExpiredError:
        raise
    except ApiError as exc:
        if exc.status_code == 404:  # deleted, or not ours
            select_chat(None)
            st.rerun()
        raise

    chat, messages, profile = detail["chat"], detail["messages"], detail["learner_profile"]
    run = detail.get("latest_run")
    st.subheader(chat["title"])
    if profile:
        _render_profile_panel(profile)

    with st.chat_message("assistant"):
        st.markdown(WELCOME)
    animate_id = st.session_state.pop(_ANIMATE_MESSAGE, None)
    for message in messages:
        with st.chat_message(message["role"]):
            _show(message["content"], animate=message["id"] == animate_id)

    status = chat["status"]
    if status == "awaiting_confirmation":
        if st.button("✅ Confirm profile", type="primary", key="confirm_profile"):
            _call_and_rerun(lambda: api.confirm_profile(chat_id))
    elif status in ("generating", "failed", "completed"):
        _render_lesson_area(api, chat_id, run)

    collecting = status in ("intake", "awaiting_confirmation")
    prompt = st.chat_input("Type your answer…" if collecting else "This chat has finished collecting information.",
                           disabled=not collecting)
    if prompt:
        _send(api, chat_id, prompt)


def _render_lesson_area(api: ChatApi, chat_id: str, run: dict | None) -> None:
    if run is None:  # confirmed, but no run yet
        if st.button("✨ Generate my lesson", type="primary", key="start_lesson"):
            _call_and_rerun(lambda: api.start_lesson(chat_id))
        return
    if run["status"] in ACTIVE_RUN_STATUSES:
        _generation_progress(api, chat_id)
    elif run["status"] == "approved":
        _render_approved(run)
    elif run["status"] == "rejected":
        st.error(f"None of the {len(run['attempts'])} versions passed all six quality checks, so no lesson is "
                 "shown. The log below explains what failed.")
        _render_evaluation_details(run, expanded=True)
        if st.button("🔄 Try again", type="primary", key="retry_after_reject"):
            _call_and_rerun(lambda: api.start_lesson(chat_id))
    else:  # technical error
        st.warning("Lesson generation hit a technical problem. This is not a judgement of your lesson.")
        if run["attempts"]:
            _render_evaluation_details(run, expanded=False)
        if st.button("🔄 Try again", type="primary", key="retry_after_error"):
            _call_and_rerun(lambda: api.start_lesson(chat_id))


@st.fragment(run_every=3)
def _generation_progress(api: ChatApi, chat_id: str) -> None:
    """Re-runs every 3 seconds on its own; triggers a full page refresh once the run finishes."""
    try:
        detail = api.get_chat(chat_id)
    except SessionExpiredError as exc:
        end_session(exc.message)
        st.rerun()
    except ApiError:
        st.caption("Checking progress…")
        return
    run = detail.get("latest_run")
    if not run or run["status"] not in ACTIVE_RUN_STATUSES:
        if run and run["status"] == "approved" and run["attempts"]:
            st.session_state[_ANIMATE_LESSON] = run["attempts"][-1]["id"]  # type it out once
        st.rerun()
    message = PHASE_MESSAGES.get(run["phase"], "Working on your lesson…")
    st.info(message.format(a=run["current_attempt"], m=run["max_attempts"])
            + "  \nThis page updates automatically. You'll only see the lesson once it passes every check.")


def _render_approved(run: dict) -> None:
    final = run["attempts"][-1]
    st.divider()
    st.success(f"✅ Passed all six quality checks · attempt {final['attempt_number']} of {run['max_attempts']}")
    animate = st.session_state.get(_ANIMATE_LESSON) == final["id"]
    if animate:
        st.session_state.pop(_ANIMATE_LESSON, None)
    _show(final["content"], animate=animate)
    _render_evaluation_details(run, expanded=False)


def _render_evaluation_details(run: dict, expanded: bool) -> None:
    attempts = run["attempts"]
    with st.expander("🔎 Evaluation details and rejection log", expanded=expanded):
        labels = []
        for a in attempts:
            ev = a["evaluation"]
            verdict = "not evaluated" if ev is None else ("✅ PASS" if ev["overall_status"] == "PASS" else "❌ FAIL")
            labels.append(f"Attempt {a['attempt_number']} · {verdict}")
        for tab, attempt in zip(st.tabs(labels), attempts):
            with tab:
                _render_attempt(attempt)


def _render_attempt(attempt: dict) -> None:
    if attempt["generator_feedback"]:
        st.markdown("**Feedback this version was asked to fix:**")
        st.caption(attempt["generator_feedback"])
    if attempt["change_summary"]:
        st.markdown(f"**What changed in this version:** {attempt['change_summary']}")
    evaluation = attempt["evaluation"]
    if evaluation is None:
        st.caption("Not evaluated: a technical problem stopped the run.")
    else:
        for criterion in evaluation["criteria_results"]:
            icon = "✅" if criterion["status"] == "PASS" else "❌"
            st.markdown(f"{icon} **{criterion.get('label', criterion['criterion'])}**: {criterion.get('reason', '')}")
            if criterion["status"] == "FAIL" and criterion.get("improvement_instructions"):
                st.caption("How to fix: " + criterion["improvement_instructions"])
            for concept in criterion.get("coverage", []):
                st.caption(f"{'✅' if concept['status'] == 'PASS' else '❌'} {concept['title']}")
    st.markdown("**This version:**")
    with st.container(height=260):
        st.markdown(attempt["content"])


def _render_new_chat(api: ChatApi) -> None:
    st.title("What would you like to learn?")
    with st.chat_message("assistant"):
        st.markdown(WELCOME)
    prompt = st.chat_input("Tell me a topic you'd like to learn…")
    if prompt:
        chat = api.create_chat()
        select_chat(chat["id"])
        _send(api, chat["id"], prompt)


def _send(api: ChatApi, chat_id: str, prompt: str) -> None:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                turn = api.send_message(chat_id, prompt)
                st.session_state[_ANIMATE_MESSAGE] = turn["assistant_message"]["id"]
            except SessionExpiredError:
                raise
            except ApiError as exc:
                set_flash(f"{exc.message} Your message was not saved. Please send it again.")
    st.rerun()


def _call_and_rerun(action) -> None:
    try:
        action()
    except SessionExpiredError:
        raise
    except ApiError as exc:
        set_flash(exc.message)
    st.rerun()


def _render_profile_panel(profile: dict) -> None:
    title = "Learner profile" + (" ✅ confirmed" if profile.get("is_confirmed") else "")
    with st.expander(title, expanded=False):
        for key, label in PROFILE_LABELS.items():
            st.markdown(f"**{label}:** {profile.get(key) or '—'}")
