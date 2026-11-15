"""Login / signup screen."""

import streamlit as st

from services.api_client import ApiError, BackendClient, Tokens
from state import pop_flash, start_session


def render_auth_page(client: BackendClient) -> None:
    st.title("📘 Self-Evaluating Lesson Generator")
    st.caption("Tell us what you want to learn. We write a beginner-friendly lesson and "
               "check it against a quality rubric before you see it.")
    if flash := pop_flash():
        st.info(flash)

    login_tab, signup_tab = st.tabs(["Log in", "Sign up"])
    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            _login(client, email, password)

    with signup_tab:
        with st.form("signup_form"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password (8 or more characters)", type="password", key="signup_password")
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            _signup(client, email, password)


def _login(client: BackendClient, email: str, password: str) -> None:
    if not email or not password:
        st.error("Please enter your email and password.")
        return
    try:
        data = client.login(email.strip(), password)
    except ApiError as exc:
        st.error(exc.message)
        return
    start_session(Tokens(data["access_token"], data["refresh_token"]), data["user"].get("email") or email)
    st.rerun()


def _signup(client: BackendClient, email: str, password: str) -> None:
    if not email or not password:
        st.error("Please enter an email and a password.")
        return
    try:
        data = client.signup(email.strip(), password)
    except ApiError as exc:
        st.error(exc.message)
        return
    session = data.get("session")
    if session is None:
        st.success("Account created. Please confirm your email, then log in.")
        return
    start_session(Tokens(session["access_token"], session["refresh_token"]), data["user"].get("email") or email)
    st.rerun()
