"""Mandatory coverage for the assessment's sample topic: Introduction to RAG."""

from app.topics.base import RequiredConcept, TopicConfig

INTRO_TO_RAG = TopicConfig(
    key="intro_to_rag",
    title="Introduction to RAG (Retrieval-Augmented Generation)",
    aliases=("rag", "retrieval augmented generation"),
    required_concepts=(
        RequiredConcept("what_is_rag", "What RAG is",
                        "A plain-language definition of Retrieval-Augmented Generation and its two halves: "
                        "retrieval and generation."),
        RequiredConcept("why_rag", "Why RAG is needed",
                        "The limits of a language model on its own: knowledge fixed at training time, no access to "
                        "private or recent documents, and the risk of confident but wrong answers."),
        RequiredConcept("what_is_retrieval", "What retrieval means",
                        "Finding the pieces of information relevant to a question, explained with an everyday analogy."),
        RequiredConcept("how_retrieval_works", "How information is retrieved",
                        "Splitting documents into chunks, turning text into embeddings (numbers that capture meaning), "
                        "storing them, and finding the chunks most similar to the question; keyword search as an "
                        "alternative."),
        RequiredConcept("how_llm_uses_context", "How retrieved information is used by an LLM",
                        "Adding the retrieved chunks to the prompt as context so the model answers from them, "
                        "ideally pointing to its sources."),
        RequiredConcept("workflow", "The complete RAG workflow",
                        "The end-to-end flow: prepare and index documents, receive a question, retrieve, "
                        "augment the prompt, generate, return the answer."),
        RequiredConcept("use_case", "A practical use case",
                        "A concrete scenario (for example a company help-desk assistant answering from its policy "
                        "documents), walked through step by step."),
        RequiredConcept("benefits_limitations", "Benefits and limitations of RAG",
                        "Benefits such as up-to-date and private knowledge and fewer made-up answers; limitations such "
                        "as poor retrieval leading to poor answers, extra cost and delay, and that it reduces but does "
                        "not eliminate errors."),
    ),
    guidance=("Explain embeddings and similarity search conceptually, with analogies; include code only if the "
              "learner is technical. Never present RAG as a guarantee of correctness."),
)
