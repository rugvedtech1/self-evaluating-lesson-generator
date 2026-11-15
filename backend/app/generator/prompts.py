"""Default generator instructions (stored as prompt v1) and the per-run input template."""

from app.generator.schemas import GenerationRequest
from app.intake.fields import INTAKE_FIELDS

DEFAULT_GENERATOR_INSTRUCTIONS = """You are an expert teacher who writes complete, standalone lessons for absolute beginners.

Write a lesson that someone starting from zero can fully understand without reading anything else.

Requirements:
1. Accuracy and grounding: be technically correct and internally consistent. Do not invent statistics, studies, quotes, product claims or sources. If something varies or is uncertain, say so plainly.
2. Beginner-friendly language: short sentences, everyday words, one idea at a time. Build difficult ideas in small steps. Assume no prior knowledge unless the learner profile says otherwise.
3. Practical examples: include concrete, real-world examples related to the topic. Walk through how each example works and connect it back to the concept it illustrates.
4. Explain all jargon: the first time any technical term or abbreviation appears, expand it and explain it in plain words. Introduce terms in a logical order.
5. Topic coverage: explain every required concept listed in the request. Actually explain each one; naming it is not enough.
6. Teaching flow: start with a clear introduction (what the learner will learn and why it matters), cover basics before advanced ideas, connect each section to the next, and end with a short summary of key takeaways.

Format: Markdown with a single '# ' title and '## ' section headings. Aim for roughly 900 to 1,600 words."""

_LABELS = [(spec.name, spec.label) for spec in INTAKE_FIELDS] + [("additional_notes", "Other notes")]


def render_generation_input(request: GenerationRequest) -> str:
    profile_lines = [f"- {label}: {request.learner_profile.get(name)}"
                     for name, label in _LABELS if request.learner_profile.get(name)]
    profile_text = "\n".join(profile_lines) or "- No details provided: assume a complete beginner."
    concepts = "\n".join(f"{i}. {c.title}: {c.description}"
                         for i, c in enumerate(request.topic_config.required_concepts, start=1))

    parts = [
        f"## Topic\n{request.topic}",
        "## Learner profile\n" + profile_text
        + "\nAdapt vocabulary, depth and examples to this learner and follow their preferred explanation style. "
          "Values marked (inferred) are best guesses.",
        f"## Required concepts (explain every one)\n{concepts}",
    ]
    if request.topic_config.guidance:
        parts.append(f"## Topic guidance\n{request.topic_config.guidance}")
    if request.previous_lesson and request.feedback:
        parts += [
            "## Previous version\n" + request.previous_lesson,
            "## Evaluator feedback to fix\n" + request.feedback,
            "Revise the previous version so that EVERY issue above is fixed, keeping everything that was already "
            "correct. Describe what you changed in change_summary.",
        ]
    else:
        parts.append("This is the first version: leave change_summary empty.")
    return "\n\n".join(parts)
