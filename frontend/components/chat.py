"""Main conversation window: intake chat, profile confirmation, and the generated lesson."""

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
_ANIMATE_MESSAGE = "animate_message_id"   # newest assistant reply to "type out" once
_ANIMATE_LESSON = "animate_version_id"    # newly arrived lesson version to "type out" once


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
    elif status in ("generating", "failed"):
        _render_lesson_area(api, chat_id, status, run)

    collecting = status in ("intake", "awaiting_confirmation")
    prompt = st.chat_input("Type your answer…" if collecting else "This chat has finished collecting information.",
                           disabled=not collecting)
    if prompt:
        _send(api, chat_id, prompt)


def _render_lesson_area(api: ChatApi, chat_id: str, status: str, run: dict | None) -> None:
    if run and run["versions"]:
        _render_lesson(run)
    elif run and run["status"] in ACTIVE_RUN_STATUSES:
        _generation_progress(api, chat_id)
    elif status == "failed" or (run and run["status"] == "error"):
        st.warning("Lesson generation hit a technical problem. Nothing is wrong with your profile.")
        if st.button("🔄 Try again", type="primary", key="retry_lesson"):
            _call_and_rerun(lambda: api.start_lesson(chat_id))
    else:  # confirmed, but no run yet (e.g. a chat confirmed before generation existed)
        if st.button("✨ Generate my lesson", type="primary", key="start_lesson"):
            _call_and_rerun(lambda: api.start_lesson(chat_id))


@st.fragment(run_every=3)
def _generation_progress(api: ChatApi, chat_id: str) -> None:
    """Re-runs every 3 seconds on its own; triggers a full page refresh once the run moves on."""
    try:
        detail = api.get_chat(chat_id)
    except SessionExpiredError as exc:
        end_session(exc.message)
        st.rerun()
    except ApiError:
        st.caption("Checking progress…")
        return
    run = detail.get("latest_run")
    if run and run["versions"]:
        st.session_state[_ANIMATE_LESSON] = run["versions"][-1]["id"]  # type it out once
    if not run or run["status"] not in ACTIVE_RUN_STATUSES or run["versions"]:
        st.rerun()
    st.info("✍️ Writing your lesson… this usually takes 20–40 seconds. This page updates automatically.")


def _render_lesson(run: dict) -> None:
    version = run["versions"][-1]
    st.divider()
    st.caption(f"📄 Lesson draft · version {version['attempt_number']} of {run['max_attempts']} · "
               "not yet quality-checked")
    animate = st.session_state.get(_ANIMATE_LESSON) == version["id"]
    if animate:
        st.session_state.pop(_ANIMATE_LESSON, None)
    _show(version["content"], animate=animate)


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
