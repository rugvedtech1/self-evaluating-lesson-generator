"""Known evaluation dataset: one good RAG lesson + deliberately flawed variants with expected outcomes.

Used to test the evaluator (Step 5) and to validate new prompt versions before activation (Step 7).
Each flawed lesson is built from the good one, so it differs ONLY by the introduced flaw.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.evaluator.engine import EvaluationRequest, LessonEvaluator
from app.core.exceptions import LLMError
from app.topics.intro_to_rag import INTRO_TO_RAG

TITLE = "# Introduction to RAG: Helping AI Look Things Up"
H_INTRO, H_LM, H_RAG = "What you will learn", "First, what is a language model?", "What is RAG?"
H_WHY, H_RET, H_HOW = "Why is RAG needed?", "What does retrieval mean?", "How is information retrieved?"
H_USE, H_FLOW = "How does the AI use what it found?", "The complete RAG workflow"
H_EX, H_BL, H_SUM = "A practical example: a school help desk", "Benefits and limitations", "Summary"

GOOD_SECTIONS: tuple[tuple[str, str], ...] = (
    (H_INTRO, "In this lesson you will learn what RAG is, why it is useful and how it works, step by step. "
              "RAG stands for Retrieval-Augmented Generation. It is a way to help artificial intelligence (AI) "
              "tools give better answers. You do not need any technical background. By the end, you will be able "
              "to explain RAG to a friend using a simple example."),
    (H_LM, "A large language model (LLM) is a computer program that has read a huge amount of text and learned "
           "which words usually come next. Chat assistants are built on LLMs. An LLM can write answers, explain "
           "ideas and summarise text. It writes by predicting likely words, one after another. It does not look "
           "anything up while it writes. This detail matters for the rest of the lesson."),
    (H_RAG, "RAG stands for Retrieval-Augmented Generation. The name has three parts. Retrieval means finding "
            "useful information. Augmented means improved by adding something. Generation means writing an answer. "
            "So RAG means: first find useful information, then use it to write a better answer. You can think of "
            "RAG as giving the AI an open-book exam instead of a closed-book exam."),
    (H_WHY, "An LLM on its own has three common problems. First, its knowledge is frozen. It only knows what was "
            "in the text it learned from, so it does not know about anything that happened later. Second, it cannot "
            "see private documents. It has never read your school's rules or your company's handbook. Third, it can "
            "sound confident even when it is wrong. When it does not know something, it may still produce an answer "
            "that sounds correct. People call this a hallucination. RAG helps with all three problems, because the "
            "AI can read fresh, relevant information before it answers."),
    (H_RET, "Retrieval simply means looking something up. Imagine you have a big cookbook and want to know how long "
            "to boil an egg. You do not read the whole book. You use the index, jump to the right page and read only "
            "that part. Retrieval in RAG works the same way. The system finds the few small pieces of text that are "
            "most likely to help answer the question."),
    (H_HOW, "Before any questions arrive, the documents are prepared in three steps. First, each long document is "
            "split into small pieces called chunks, such as one or two paragraphs each. Second, each chunk is turned "
            "into an embedding. An embedding is a list of numbers that represents the meaning of the text. Texts with "
            "similar meanings get similar numbers, a bit like nearby points on a map. Third, these embeddings are "
            "stored in a searchable database. When a question arrives, the question is also turned into an embedding. "
            "The system then finds the chunks whose embeddings are closest to the question's embedding. Those chunks "
            "are the most likely to contain the answer. Some systems also use simple keyword search, which looks for "
            "chunks that contain the same important words as the question."),
    (H_USE, "The retrieved chunks are added to the question before it is sent to the LLM. This extra text is called "
            "context. The instruction might say: answer the question using only the information below. Because the "
            "LLM can now read the relevant facts, its answer is based on them instead of only on its memory. A good "
            "RAG system can also show which documents it used, so you can check the answer yourself."),
    (H_FLOW, "Here is the whole process from start to finish:\n\n"
             "1. Prepare: split the documents into chunks, create embeddings and store them.\n"
             "2. Ask: a user types a question.\n"
             "3. Retrieve: the system finds the chunks most related to the question.\n"
             "4. Augment: the system adds those chunks to the question as context.\n"
             "5. Generate: the LLM writes an answer using that context.\n"
             "6. Return: the user receives the answer, ideally with links to the sources."),
    (H_EX, "Imagine your school builds a chatbot that answers questions about school rules. The rule book is split "
           "into chunks and stored with embeddings. A student asks: can I bring my phone to the exam hall? The system "
           "turns the question into an embedding and retrieves the chunk about exam-hall rules. That chunk says that "
           "phones must be switched off and left in bags. The chunk is added to the question as context. The LLM then "
           "answers that phones must be switched off and kept in your bag during exams. Without RAG, the chatbot would "
           "have had to guess, because it never read your school's rule book."),
    (H_BL, "RAG has clear benefits. It lets an AI use up-to-date information and private documents without retraining "
           "the model. It makes answers more grounded, which reduces made-up answers. It can also show its sources, "
           "which builds trust.\n\nRAG also has limitations. If the retrieval step finds the wrong chunks, the answer "
           "will be poor. The extra steps add some cost and make answers a little slower. RAG reduces mistakes, but it "
           "does not remove them completely, so important answers should still be checked."),
    (H_SUM, "- RAG stands for Retrieval-Augmented Generation: find useful information first, then write the answer.\n"
            "- An LLM alone has frozen knowledge, cannot see private documents and can be confidently wrong.\n"
            "- Retrieval means looking up the most relevant pieces of text, like using a cookbook's index.\n"
            "- Documents are split into chunks and turned into embeddings, which are numbers that capture meaning.\n"
            "- The retrieved chunks are added to the question as context so the LLM can answer from them.\n"
            "- RAG makes answers more current and grounded, but it is not perfect."),
)


def render(sections: Sequence[tuple[str, str]], title: str = TITLE) -> str:
    return "\n\n".join([title, *(f"## {heading}\n\n{body}" for heading, body in sections)]) + "\n"


def _variant(*, replace: dict[str, str] | None = None, drop: Sequence[str] = (), reverse: bool = False) -> str:
    replace = replace or {}
    unknown = (set(replace) | set(drop)) - {h for h, _ in GOOD_SECTIONS}
    if unknown:
        raise KeyError(f"Unknown sections: {unknown}")
    sections = [(h, replace.get(h, b)) for h, b in GOOD_SECTIONS if h not in drop]
    if reverse:
        sections.reverse()
    return render(sections)


GOOD_LESSON = render(GOOD_SECTIONS)
DATASET_PROFILE = {"topic": "Introduction to RAG", "education_level": "12th standard",
                   "english_proficiency": "Beginner", "technical_background": "None",
                   "ai_knowledge": "Never used AI tools", "preferred_style": "Step-by-step"}


@dataclass(frozen=True)
class EvaluationCase:
    key: str
    description: str
    lesson_markdown: str
    must_fail: frozenset[str]  # empty = the lesson must PASS overall


CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase("good", "Well-structured beginner lesson covering all eight concepts", GOOD_LESSON, frozenset()),
    EvaluationCase("factual_error", "False claims and a fabricated study", _variant(replace={H_WHY: (
        "An LLM on its own already knows about events that happened today, because it automatically reads the "
        "whole internet every time you ask a question. RAG is needed mainly because it permanently retrains the "
        "model with every question, which makes the model 100% accurate. A 2023 Stanford study proved that RAG "
        "removes all mistakes from AI answers.")}), frozenset({"accuracy"})),
    EvaluationCase("unexplained_jargon", "Retrieval explained only with unexplained technical terms", _variant(replace={H_HOW: (
        "Documents are chunked and vectorised with a bi-encoder into dense embeddings, then indexed in an ANN "
        "store such as HNSW. At query time the query vector is compared using cosine similarity, the top-k chunks "
        "are fetched, and a cross-encoder re-ranks them before injection into the context window. Hybrid setups add "
        "BM25 for lexical recall.")}), frozenset({"jargon_explanation"})),
    EvaluationCase("no_examples", "All analogies and the worked example removed", _variant(
        drop=(H_EX,),
        replace={
            H_RAG: "RAG stands for Retrieval-Augmented Generation. The name has three parts. Retrieval means finding "
                   "useful information. Augmented means improved by adding something. Generation means writing an "
                   "answer. So RAG means: first find useful information, then use it to write a better answer.",
            H_RET: "Retrieval simply means looking something up. In RAG, the system finds the few small pieces of "
                   "text that are most likely to help answer the question.",
            H_HOW: "Each document is split into small pieces called chunks. Each chunk is turned into an embedding, "
                   "which is a list of numbers that represents its meaning. The embeddings are stored in a database. "
                   "A question is also turned into an embedding, and the closest chunks are retrieved.",
            H_SUM: "- RAG stands for Retrieval-Augmented Generation: find useful information first, then write the "
                   "answer.\n- Documents are split into chunks and turned into embeddings.\n- The retrieved chunks "
                   "are added to the question as context.\n- RAG makes answers more current, but it is not perfect.",
        }), frozenset({"practical_examples"})),
    EvaluationCase("missing_concepts", "Context use, full workflow and benefits/limitations removed",
                   _variant(drop=(H_USE, H_FLOW, H_BL)), frozenset({"topic_coverage"})),
    EvaluationCase("poor_flow", "No introduction, no summary, sections in reverse order",
                   _variant(drop=(H_INTRO, H_SUM), reverse=True), frozenset({"teaching_flow"})),
    EvaluationCase("too_advanced", "Key sections rewritten in dense academic language", _variant(replace={
        H_LM: "Autoregressive transformer architectures parameterise a conditional probability distribution over "
              "subword tokens, approximating the likelihood of each token given all preceding tokens through "
              "multi-head self-attention over high-dimensional contextual representations learned via large-scale "
              "self-supervised pretraining on heterogeneous corpora.",
        H_RAG: "Retrieval-augmented generation conditions the decoder on a non-parametric memory, marginalising over "
               "latent retrieved passages so that the output distribution is grounded in an external datastore "
               "rather than relying exclusively on parametric knowledge encoded in the network weights.",
        H_WHY: "Purely parametric models exhibit temporal staleness, lack access to proprietary corpora and are prone "
               "to confabulation under epistemic uncertainty; retrieval mitigates these failure modes by injecting "
               "query-conditioned evidence into the context, thereby constraining the posterior over continuations.",
    }), frozenset({"beginner_friendliness"})),
)


@dataclass(frozen=True)
class CaseResult:
    case: EvaluationCase
    overall_status: str | None
    failed_criteria: tuple[str, ...]
    matched: bool
    error: str | None = None


def run_dataset(evaluator: LessonEvaluator, instructions: str | None = None,
                only: Sequence[str] | None = None) -> list[CaseResult]:
    """Evaluate every case. A case matches if 'good' PASSes, or a flawed lesson FAILs its target criteria."""
    results: list[CaseResult] = []
    for case in CASES:
        if only and case.key not in only:
            continue
        request = EvaluationRequest(lesson_markdown=case.lesson_markdown, topic="Introduction to RAG",
                                    topic_config=INTRO_TO_RAG, learner_profile=DATASET_PROFILE)
        if instructions is not None:
            request = EvaluationRequest(**{**request.__dict__, "instructions": instructions})
        try:
            report = evaluator.evaluate(request)
        except LLMError as exc:
            results.append(CaseResult(case, None, (), False, error=str(exc)))
            continue
        failed = tuple(report.failed_criteria)
        matched = (report.overall_status == "PASS") if not case.must_fail else case.must_fail <= set(failed)
        results.append(CaseResult(case, report.overall_status, failed, matched))
    return results
