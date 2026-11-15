"""Streamlit entry point: the login screen, the chat application, or the system learning page."""

import streamlit as st

from components.auth import render_auth_page
from components.chat import render_chat
from components.sidebar import render_sidebar
from components.system import render_system
from services.api_client import ApiError, BackendClient, ChatApi, SessionExpiredError
from services.settings import get_frontend_settings
from state import current_view, end_session, get_tokens, save_tokens

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
        if current_view() == "system":
            render_system(api)
        else:
            render_chat(api)
    except SessionExpiredError as exc:
        end_session(exc.message)
        st.rerun()
    except ApiError as exc:
        st.error(exc.message)


main()
