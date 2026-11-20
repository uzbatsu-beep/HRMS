"""Minimal, non-content audit trail for successful sensitive API reads."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy import Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PersonalDataReadEvent(Base):
    """Metadata only: no names, search strings, document references or note text."""

    __tablename__ = "personal_data_read_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"],
            name="fk_personal_data_read_person_tenant",
        ),
        CheckConstraint("record_count >= 0", name="ck_personal_data_read_count_nonnegative"),
        Index("ix_personal_data_read_enterprise_time", "enterprise_id", "created_at"),
        Index("ix_personal_data_read_person_time", "person_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False,
    )
    surface: Mapped[str] = mapped_column(String(48), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
