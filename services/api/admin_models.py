"""Admin credential model — separate from user accounts.

Per plans/paymob-integration.md, admin endpoints are authorized with a
separate admin credential (username + hashed password), never with a user
tier. Admins are provisioned out-of-band (env-var bootstrap at startup or
manual DB insert); there is no self-service registration endpoint.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from services.api.models import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class Admin(Base):
    __tablename__ = "admins"

    # String(36) to match the users.id convention (dashed UUID strings),
    # so FKs from audit/resolution columns work on both SQLite and Postgres.
    id = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), nullable=False
    )
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
