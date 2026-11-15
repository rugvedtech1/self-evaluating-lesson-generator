"""Sidebar: new chat, recent chats, logout."""

import streamlit as st

from services.api_client import ChatApi
from state import current_chat_id, end_session, select_chat, user_email


def render_sidebar(api: ChatApi) -> None:
    with st.sidebar:
        st.markdown("### 📘 Lesson Generator")
        st.caption(f"Signed in as {user_email()}")

        if st.button("➕  New chat", key="new_chat"):
            select_chat(None)  # the chat itself is created when the first message is sent
            st.rerun()

        st.markdown("**Recent chats**")
        chats = api.list_chats()
        if not chats:
            st.caption("No chats yet.")
        selected = current_chat_id()
        for chat in chats:
            is_current = chat["id"] == selected
            if st.button(chat["title"], key=f"chat_{chat['id']}", type="primary" if is_current else "secondary"):
                select_chat(chat["id"])
                st.rerun()

        st.divider()
        if st.button("Log out", key="logout"):
            api.logout()
            end_session("You have been logged out.")
            st.rerun()
