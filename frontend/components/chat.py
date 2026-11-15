"""Main conversation window."""

import streamlit as st

from services.api_client import ApiError, ChatApi, SessionExpiredError
from state import current_chat_id, pop_flash, select_chat, set_flash

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
    st.subheader(chat["title"])
    if profile:
        _render_profile_panel(profile)

    with st.chat_message("assistant"):
        st.markdown(WELCOME)
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    status = chat["status"]
    if status == "awaiting_confirmation":
        if st.button("✅ Confirm profile", type="primary", key="confirm_profile"):
            try:
                api.confirm_profile(chat_id)
            except SessionExpiredError:
                raise
            except ApiError as exc:
                set_flash(exc.message)
            st.rerun()
    elif status == "generating":
        st.info("Your learner profile is confirmed. Your lesson will be generated here.")

    collecting = status in ("intake", "awaiting_confirmation")
    prompt = st.chat_input("Type your answer…" if collecting else "This chat has finished collecting information.",
                           disabled=not collecting)
    if prompt:
        _send(api, chat_id, prompt)


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
                api.send_message(chat_id, prompt)
            except SessionExpiredError:
                raise
            except ApiError as exc:
                set_flash(f"{exc.message} Your message was not saved. Please send it again.")
    st.rerun()


def _render_profile_panel(profile: dict) -> None:
    title = "Learner profile" + (" ✅ confirmed" if profile.get("is_confirmed") else "")
    with st.expander(title, expanded=False):
        for key, label in PROFILE_LABELS.items():
            st.markdown(f"**{label}:** {profile.get(key) or '—'}")
