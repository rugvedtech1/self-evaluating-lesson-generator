"""Per-browser-session UI state. Temporary only: permanent data lives in the backend/Postgres."""

import streamlit as st

from services.api_client import Tokens

_TOKENS = "auth_tokens"
_EMAIL = "user_email"
_CHAT = "current_chat_id"
_FLASH = "flash_message"


def get_tokens() -> Tokens | None:
    return st.session_state.get(_TOKENS)


def save_tokens(tokens: Tokens) -> None:
    st.session_state[_TOKENS] = tokens


def start_session(tokens: Tokens, email: str) -> None:
    save_tokens(tokens)
    st.session_state[_EMAIL] = email
    st.session_state[_CHAT] = None


def end_session(flash: str | None = None) -> None:
    for key in (_TOKENS, _EMAIL, _CHAT):
        st.session_state.pop(key, None)
    if flash:
        set_flash(flash)


def user_email() -> str:
    return st.session_state.get(_EMAIL, "")


def current_chat_id() -> str | None:
    return st.session_state.get(_CHAT)


def select_chat(chat_id: str | None) -> None:
    st.session_state[_CHAT] = chat_id


def set_flash(message: str) -> None:
    st.session_state[_FLASH] = message


def pop_flash() -> str | None:
    return st.session_state.pop(_FLASH, None)
