"""Application profile management."""

import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Profile


def ensure_profile(db: Session, user_id: uuid.UUID, email: str | None) -> Profile:
    """Create the user's profile row if missing, otherwise refresh its email (one atomic upsert).

    `user_id` must come from a verified token or from Supabase Auth itself, never from client input.
    """
    stmt = pg_insert(Profile).values(id=user_id, email=email or "")
    stmt = stmt.on_conflict_do_update(
        index_elements=[Profile.id],
        set_={
            # keep the stored email if the new one is empty
            "email": func.coalesce(func.nullif(stmt.excluded.email, ""), Profile.email),
            "updated_at": func.now(),
        },
    ).returning(Profile)
    return db.scalars(stmt, execution_options={"populate_existing": True}).one()
