"""Resume lesson runs that were interrupted (e.g. by a server restart), using their checkpoints."""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope as default_session_scope
from app.models import LessonRun
from app.services.lessons import ACTIVE_RUN_STATUSES


class Resumable(Protocol):
    def resume(self, run_id: uuid.UUID, user_id: uuid.UUID) -> None: ...


def find_interrupted_runs(db: Session) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """System-level query (server process): each run is later resumed with its OWN user's id."""
    runs = db.scalars(select(LessonRun).where(LessonRun.status.in_(ACTIVE_RUN_STATUSES))
                      .order_by(LessonRun.created_at))
    return [(run.id, run.user_id) for run in runs]


def recover_interrupted_runs(
    runner: Resumable,
    session_scope: Callable[[], AbstractContextManager[Session]] = default_session_scope,
) -> int:
    with session_scope() as db:
        runs = find_interrupted_runs(db)
    for run_id, user_id in runs:
        runner.resume(run_id, user_id)
    return len(runs)
