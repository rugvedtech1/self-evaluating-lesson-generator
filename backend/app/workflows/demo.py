"""Demo mode (OFF by default, server-side only).

Replaces chosen Generator attempts with a known-flawed lesson from the evaluation dataset, so a recording can
show evaluation, regeneration, rejection and self-evolution on demand. ONLY the Generator is replaced: the
Evaluator, Decision Gate, feedback, rejection log and failure-pattern counting all run for real.

  off    normal behaviour
  first  attempt 1 is flawed; the real Generator then revises it using the real Evaluator feedback
  all    every attempt is flawed, so the run is rejected after max attempts
"""

import logging

from app.evaluator.dataset import CASES
from app.generator.schemas import GenerationRequest, LessonDraft

logger = logging.getLogger(__name__)

MODES = ("off", "first", "all")
DEMO_TOPIC_KEY = "intro_to_rag"  # the dataset lessons are about this topic
BANNER = ("> **Demo mode:** this attempt was deliberately replaced with a known-flawed sample lesson "
          "to demonstrate evaluation and regeneration.")


def _with_banner(markdown: str) -> str:
    title, _, rest = markdown.partition("\n")
    return f"{title}\n\n{BANNER}\n{rest}"


class DemoFlawGenerator:
    def __init__(self, inner, mode: str = "off", case_key: str = "unexplained_jargon") -> None:
        if mode not in MODES:
            raise ValueError(f"DEMO_FLAW_MODE must be one of {MODES}, got {mode!r}.")
        cases = {case.key: case for case in CASES}
        if case_key not in cases or not cases[case_key].must_fail:
            flawed = sorted(k for k, c in cases.items() if c.must_fail)
            raise ValueError(f"DEMO_FLAW_CASE must be one of {flawed}, got {case_key!r}.")
        self.inner, self.mode, self.case = inner, mode, cases[case_key]
        if mode != "off":
            logger.warning("DEMO MODE ON: generator attempts will be replaced with a flawed lesson",
                           extra={"context": {"mode": mode, "case": case_key}})

    def _replace(self, request: GenerationRequest) -> bool:
        if self.mode == "off" or getattr(request.topic_config, "key", None) != DEMO_TOPIC_KEY:
            return False
        return self.mode == "all" or request.previous_lesson is None

    def generate(self, request: GenerationRequest) -> LessonDraft:
        if not self._replace(request):
            return self.inner.generate(request)
        markdown = self.case.lesson_markdown
        return LessonDraft(title=markdown.partition("\n")[0].lstrip("# ").strip(),
                           lesson_markdown=_with_banner(markdown),
                           change_summary="Demo mode: deliberately flawed attempt (feedback not applied).")
