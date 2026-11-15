"""System learning page: recurring failure patterns, prompt versions, validation, evolution + rollback."""

import streamlit as st

from services.api_client import ApiError, ChatApi, SessionExpiredError
from state import pop_flash, set_flash

STATUS_BADGES = {"active": "🟢 active", "retired": "⚪ retired", "rejected": "🔴 rejected",
                 "validating": "🟡 validating", "draft": "⚪ draft (not validated)"}


def render_system(api: ChatApi) -> None:
    st.title("⚙️ System learning")
    st.caption("How the app learns from recurring quality failures across all lesson runs. Only anonymous "
               "counts are kept here: no messages, learner profiles or lessons.")
    if flash := pop_flash():
        st.info(flash)
    if st.button("🔄 Refresh", key="refresh_system"):
        st.rerun()

    st.subheader("Recurring failure patterns")
    st.caption("Counted for runs that used the currently active generator prompt.")
    patterns = api.list_failure_patterns()
    if patterns:
        st.dataframe([{"Pattern": p["description"], "Occurrences": p["occurrence_count"], "Status": p["status"]}
                      for p in patterns], hide_index=True)
    else:
        st.caption("No failures recorded for the current prompt yet.")

    st.subheader("Generator prompt versions")
    for prompt in api.list_prompts("generator"):
        title = f"v{prompt['version']} · {STATUS_BADGES.get(prompt['status'], prompt['status'])}"
        with st.expander(title, expanded=prompt["status"] == "active"):
            if prompt["change_reason"]:
                st.markdown(f"**Why this version exists:** {prompt['change_reason']}")
            report = prompt.get("validation_report")
            if report:
                verdict = "✅ passed" if report.get("passed") else ("⚠️ technical error" if report.get(
                    "technical_error") else "❌ failed")
                st.markdown(f"**Validation before activation:** {verdict}")
                for case in report.get("cases", []):
                    failed = ", ".join(case.get("failed_criteria") or []) or "-"
                    st.caption(f"{case['case']}: {case.get('overall_status') or 'ERROR'} (failed: {failed})")
            st.code(prompt["content"], language=None, wrap_lines=True)

    st.subheader("Admin actions")
    st.caption("Only accounts listed in ADMIN_EMAILS can run these.")
    left, right = st.columns(2)
    if left.button("🧠 Run self-evolution cycle", key="evolve"):
        _act(lambda: api.start_evolution(), "Self-evolution started. Refresh in about a minute.")
    if right.button("↩️ Roll back generator prompt", key="rollback"):
        _act(lambda: api.rollback_prompt("generator"), "Rolled back to the previous validated version.")


def _act(action, success: str) -> None:
    try:
        action()
        set_flash(success)
    except SessionExpiredError:
        raise
    except ApiError as exc:
        set_flash(exc.message)
    st.rerun()
