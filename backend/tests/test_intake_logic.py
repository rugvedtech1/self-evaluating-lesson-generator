"""Pure-Python intake rules: question order, no repeats, give-up limit, inference, cleaning, summary."""

from types import SimpleNamespace

from app.intake.fields import NOT_SPECIFIED, plan_next_question
from app.intake.service import (
    INFERRED_NOTE, asked_field_counts, build_profile_summary, clean_updates, is_inferred, last_asked_field,
)

FIELD_ORDER = ["topic", "education_level", "english_proficiency",
               "technical_background", "ai_knowledge", "preferred_style"]


def _msg(role: str, kind: str = "chat", field: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(role=role, kind=kind, payload={"intake_field": field} if field else {})


def test_first_question_is_about_the_topic() -> None:
    assert plan_next_question({}, {}).next_field.name == "topic"


def test_answered_fields_are_skipped_in_order() -> None:
    profile = {"topic": "RAG", "education_level": "Undergraduate"}
    assert plan_next_question(profile, {}).next_field.name == "english_proficiency"


def test_inferred_fields_count_as_answered() -> None:
    profile = {"topic": "RAG", "education_level": "8th standard", "english_proficiency": "Basic",
               "technical_background": "None (inferred)", "ai_knowledge": "Beginner (inferred)"}
    assert plan_next_question(profile, {}).next_field.name == "preferred_style"


def test_unanswered_field_given_up_after_two_asks() -> None:
    plan = plan_next_question({"topic": "RAG"}, {"education_level": 2})
    assert plan.give_up_fields == ("education_level",)
    assert plan.next_field.name == "english_proficiency"


def test_topic_is_never_given_up() -> None:
    plan = plan_next_question({}, {"topic": 5})
    assert plan.next_field.name == "topic"
    assert plan.give_up_fields == ()


def test_complete_profile_needs_no_more_questions() -> None:
    assert plan_next_question({name: "x" for name in FIELD_ORDER}, {}).next_field is None


def test_clean_updates_normalises_and_drops_unchanged_or_unknown() -> None:
    current = {"topic": "RAG", "education_level": None}
    raw = {"topic": "RAG", "education_level": "  Second-year   CS student ",
           "english_proficiency": None, "unknown_field": "x", "preferred_style": "   "}
    assert clean_updates(raw, current) == {"education_level": "Second-year CS student"}


def test_inference_never_overwrites_what_the_learner_said() -> None:
    current = {"technical_background": "I build websites", "ai_knowledge": None}
    raw = {"technical_background": "None (inferred)", "ai_knowledge": "Beginner (inferred)"}
    assert clean_updates(raw, current) == {"ai_knowledge": "Beginner (inferred)"}


def test_clean_updates_truncates_very_long_values() -> None:
    assert len(clean_updates({"additional_notes": "a" * 1000}, {})["additional_notes"]) == 300


def test_asked_counts_and_last_question_come_from_history() -> None:
    history = [_msg("user"), _msg("assistant", "intake_question", "education_level"),
               _msg("user"), _msg("assistant", "intake_question", "education_level"), _msg("user")]
    assert asked_field_counts(history)["education_level"] == 2
    assert last_asked_field(history) == "education_level"
    assert last_asked_field([*history, _msg("assistant", "profile_summary")]) is None


def test_summary_lists_every_field_from_stored_values() -> None:
    summary = build_profile_summary({"topic": "Introduction to RAG", "preferred_style": "Analogies"})
    for label in ("Topic", "Education level", "English level", "Technical background",
                  "AI knowledge", "Explanation style"):
        assert f"**{label}:**" in summary
    assert "Introduction to RAG" in summary
    assert NOT_SPECIFIED in summary
    assert INFERRED_NOTE not in summary


def test_summary_flags_inferred_values() -> None:
    assert is_inferred("None (inferred)")
    assert not is_inferred("none")
    assert INFERRED_NOTE in build_profile_summary({"topic": "RAG", "technical_background": "None (inferred)"})
