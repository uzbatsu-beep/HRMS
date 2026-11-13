"""Stable keyset audit pagination with strict tenant filtering.

The explorer intentionally omits details_json, which may contain human-entered
evidence references or reasons. An existing admin-only legacy endpoint remains
untouched for backward compatibility.
"""

import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.equipment.models import EquipmentAuditEvent
from app.equipment.schemas import EquipmentAuditPage, EquipmentAuditRow
from app.identity.models import UserAccount


def cursor_for(row: EquipmentAuditEvent) -> str:
    stamp = row.created_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    data = f"{stamp.isoformat()}|{row.id}".encode("ascii")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def parse_cursor(cursor: str) -> tuple[datetime, UUID]:
    if len(cursor) > 180:
        raise ValueError("Invalid audit cursor")
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        ).decode("ascii")
        timestamp, identifier = raw.rsplit("|", 1)
        stamp = datetime.fromisoformat(timestamp)
        if stamp.tzinfo is None:
            raise ValueError("Cursor timezone required")
        return stamp.astimezone(timezone.utc), UUID(identifier)
    except (binascii.Error, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("Invalid audit cursor") from exc


def read_page(
    db: Session, enterprise_id: UUID, limit: int,
    action: str | None = None, subject_id: UUID | None = None,
    actor_id: UUID | None = None,
    since: datetime | None = None, until: datetime | None = None,
    cursor: str | None = None,
) -> EquipmentAuditPage:
    """Only administration-visible metadata; stable (timestamp, id) ordering."""
    if since is not None and until is not None and since > until:
        raise ValueError("Audit 'since' must not be later than 'until'")
    query = (
        select(EquipmentAuditEvent, UserAccount.username)
        .join(UserAccount, UserAccount.id == EquipmentAuditEvent.actor_id)
        .where(EquipmentAuditEvent.enterprise_id == enterprise_id)
    )
    if action is not None:
        query = query.where(EquipmentAuditEvent.action == action)
    if subject_id is not None:
        query = query.where(EquipmentAuditEvent.subject_id == subject_id)
    if actor_id is not None:
        query = query.where(EquipmentAuditEvent.actor_id == actor_id)
    if since is not None:
        query = query.where(EquipmentAuditEvent.created_at >= since)
    if until is not None:
        query = query.where(EquipmentAuditEvent.created_at <= until)
    if cursor:
        stamp, identifier = parse_cursor(cursor)
        query = query.where(or_(
            EquipmentAuditEvent.created_at < stamp,
            and_(
                EquipmentAuditEvent.created_at == stamp,
                EquipmentAuditEvent.id < identifier,
            ),
        ))
    rows = db.execute(
        query.order_by(
            EquipmentAuditEvent.created_at.desc(),
            EquipmentAuditEvent.id.desc(),
        ).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    chosen = rows[:limit]
    return EquipmentAuditPage(
        enterprise_id=enterprise_id,
        items=[
            EquipmentAuditRow(
                id=row.id, action=row.action, actor_id=row.actor_id,
                actor_username=username, subject_id=row.subject_id,
                created_at=row.created_at,
            )
            for row, username in chosen
        ],
        has_more=has_more,
        next_cursor=cursor_for(chosen[-1][0]) if has_more else None,
    )
