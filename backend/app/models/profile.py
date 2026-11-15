"""Application-level user profile linked to Supabase Auth."""

import uuid

from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Profile(TimestampMixin, Base):
    """`id` equals the Supabase Auth user id (auth.users.id).

    Passwords never live here: Supabase Auth owns identities and credentials.
    The foreign key to auth.users is created in the migration, because the
    `auth` schema belongs to Supabase, not to our models.
    """

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
