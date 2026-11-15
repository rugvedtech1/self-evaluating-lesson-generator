"""Streamlit entry point: the login screen, or the chat application."""

import streamlit as st

from components.auth import render_auth_page
from components.chat import render_chat
from components.sidebar import render_sidebar
from services.api_client import ApiError, BackendClient, ChatApi, SessionExpiredError
from services.settings import get_frontend_settings
from state import end_session, get_tokens, save_tokens

st.set_page_config(page_title="Lesson Generator", page_icon="📘", layout="centered")


@st.cache_resource
def get_backend_client() -> BackendClient:
    """One HTTP client, reused across Streamlit reruns."""
    settings = get_frontend_settings()
    return BackendClient(base_url=settings.backend_url, timeout=settings.request_timeout_seconds)


def main() -> None:
    client = get_backend_client()
    if get_tokens() is None:
        render_auth_page(client)
        return

    api = ChatApi(client, get_tokens, save_tokens)
    try:
        render_sidebar(api)
        render_chat(api)
    except SessionExpiredError as exc:
        end_session(exc.message)
        st.rerun()
    except ApiError as exc:
        st.error(exc.message)


main()
