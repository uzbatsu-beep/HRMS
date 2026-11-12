"""Weekly shift patterns, absence intervals, planned reservations and immutable audit."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, Text, Time, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ShiftRule(Base):
    """One weekday's recurring local-time shift for an active workforce resource."""

    __tablename__ = "shift_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_shift_rule_resource_tenant",
        ),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_shift_rule_weekday"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_shift_rule_validity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    local_start: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    local_end: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(80), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarClosure(Base):
    """Enterprise-wide local-date closure, e.g., shutdown or holiday."""

    __tablename__ = "calendar_closures"
    __table_args__ = (
        UniqueConstraint(
            "enterprise_id", "local_date", "time_zone",
            name="uq_calendar_closure_tenant_local_day",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_zone: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(180), nullable=False)


class AbsencePeriod(Base):
    """A full blocking interval. Reason is optional admin-only metadata."""

    __tablename__ = "absence_periods"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_absence_resource_tenant",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_absence_dates"),
        CheckConstraint(
            "category IN ('leave', 'training', 'unavailable')",
            name="ck_absence_category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(400))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkReservation(Base):
    """Calendar-only hold, not a work order or safety authorization."""

    __tablename__ = "work_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_reservation_resource_tenant",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_reservation_dates"),
        UniqueConstraint(
            "enterprise_id", "external_reference", name="uq_reservation_external_ref"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SchedulingAuditEvent(Base):
    __tablename__ = "scheduling_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
