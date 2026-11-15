"""Streamlit entry point. Step 1: verify the frontend can reach the backend."""

import streamlit as st

from services.api_client import BackendClient
from services.settings import get_frontend_settings

st.set_page_config(page_title="Lesson Content Generator", page_icon="📘", layout="centered")


@st.cache_resource
def get_backend_client() -> BackendClient:
    """Create one HTTP client and reuse it across Streamlit reruns."""
    settings = get_frontend_settings()
    return BackendClient(base_url=settings.backend_url, timeout=settings.request_timeout_seconds)


st.title("📘 Self-Evaluating Lesson Generator")
st.caption("Step 1 skeleton — login, chat and lesson generation arrive in later steps.")

st.subheader("Backend connection")
status = get_backend_client().check_health()

if status.ok:
    st.success(status.detail)
    st.json(status.payload)
else:
    st.error(status.detail)
    st.info("Start the backend in another terminal, then click the button below.")

st.button("Check again")  # any button click re-runs the script
