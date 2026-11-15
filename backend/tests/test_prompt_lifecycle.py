"""Prompt versions: candidate → activation (one active), rejection, rollback, refusal to restore unvalidated."""

import pytest

from app.core.exceptions import InvalidOperationError
from app.services.prompts import (
    activate_prompt, create_candidate_prompt, ensure_active_prompt, get_active_prompt, list_prompt_versions,
    reject_prompt, rollback_prompt,
)

pytestmark = pytest.mark.db


def _v2(db):
    v1 = ensure_active_prompt(db, "generator", "v1")
    return v1, create_candidate_prompt(db, "generator", "v2", parent=v1, change_reason="test")


def test_candidate_gets_next_version_and_waits_for_validation(db_session) -> None:
    v1, v2 = _v2(db_session)
    assert (v2.version, v2.status, v2.parent_version_id) == (2, "validating", v1.id)
    assert get_active_prompt(db_session, "generator").id == v1.id


def test_activation_retires_previous_and_keeps_exactly_one_active(db_session) -> None:
    v1, v2 = _v2(db_session)
    activate_prompt(db_session, v2)
    statuses = {p.version: p.status for p in list_prompt_versions(db_session, "generator")}
    assert statuses == {1: "retired", 2: "active"}


def test_rejected_candidate_never_becomes_active(db_session) -> None:
    v1, v2 = _v2(db_session)
    reject_prompt(db_session, v2)
    assert get_active_prompt(db_session, "generator").id == v1.id
    with pytest.raises(InvalidOperationError):
        activate_prompt(db_session, v2)
    with pytest.raises(InvalidOperationError, match="never validated"):
        rollback_prompt(db_session, "generator", to_version=2)


def test_rollback_restores_previous_version(db_session) -> None:
    v1, v2 = _v2(db_session)
    activate_prompt(db_session, v2)
    assert rollback_prompt(db_session, "generator").id == v1.id
    assert {p.version: p.status for p in list_prompt_versions(db_session, "generator")} == {1: "active", 2: "retired"}


def test_rollback_to_explicit_version_and_forward_again(db_session) -> None:
    v1, v2 = _v2(db_session)
    activate_prompt(db_session, v2)
    rollback_prompt(db_session, "generator")
    assert rollback_prompt(db_session, "generator", to_version=2).id == v2.id


def test_rollback_without_earlier_version_is_refused(db_session) -> None:
    ensure_active_prompt(db_session, "generator", "v1")
    with pytest.raises(InvalidOperationError, match="no earlier"):
        rollback_prompt(db_session, "generator")
