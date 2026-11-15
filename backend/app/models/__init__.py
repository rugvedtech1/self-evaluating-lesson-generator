"""Import every model so they register on Base.metadata (needed by Alembic)."""

from app.models.chat import Chat, ChatProfile, Message
from app.models.lesson import Evaluation, LessonRun, LessonVersion
from app.models.profile import Profile
from app.models.system import FailurePattern, PromptVersion

__all__ = [
    "Chat", "ChatProfile", "Evaluation", "FailurePattern", "LessonRun",
    "LessonVersion", "Message", "Profile", "PromptVersion",
]
