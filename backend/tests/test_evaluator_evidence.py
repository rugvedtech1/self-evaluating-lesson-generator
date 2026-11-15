"""Evidence verification: real quotes pass, invented ones fail."""

from app.evaluator.evidence import normalise_text, quote_in_lesson, verified_quotes

LESSON = ("**RAG** stands for “Retrieval-Augmented Generation”. The system finds the few small pieces of text "
          "that are most likely to help answer the question. Texts with similar meanings get similar numbers.")
NORMALISED = normalise_text(LESSON)


def test_exact_quote_is_found() -> None:
    assert quote_in_lesson("Texts with similar meanings get similar numbers.", NORMALISED)


def test_formatting_and_quote_style_differences_are_ignored() -> None:
    assert quote_in_lesson('rag stands for "retrieval-augmented generation"', NORMALISED)


def test_tiny_copying_difference_is_tolerated() -> None:
    assert quote_in_lesson("the system finds the few small pieces of text that are most likely to help answr",
                           NORMALISED)


def test_shortened_quote_with_ellipsis_is_found() -> None:
    assert quote_in_lesson("The system finds the few small pieces ... most likely to help answer the question",
                           NORMALISED)


def test_invented_quote_is_rejected() -> None:
    assert not quote_in_lesson("RAG permanently retrains the model with every question.", NORMALISED)


def test_too_short_quote_is_not_accepted_as_evidence() -> None:
    assert verified_quotes(["RAG", "text"], LESSON) == []


def test_quote_spanning_numbered_list_items_is_found() -> None:
    lesson = normalise_text("Steps:\n\n1. Prepare: split the documents into chunks.\n2. Ask: a user types a question.\n")
    assert quote_in_lesson("Prepare: split the documents into chunks. Ask: a user types a question.", lesson)


def test_one_invented_sentence_inside_a_real_quote_is_rejected() -> None:
    lesson = normalise_text("Retrieval simply means looking something up. It finds the most useful text.")
    assert not quote_in_lesson("Retrieval simply means looking something up. RAG retrains the model every time.",
                               lesson)
