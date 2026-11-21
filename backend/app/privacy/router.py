"""Administrator-only metadata audit explorer; never returns record content."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import require_admin
from app.privacy.models import PersonalDataReadEvent


router = APIRouter(prefix=f"{settings.api_v1_prefix}/privacy", tags=["privacy"])


class PersonalDataReadView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    person_id: UUID | None
    actor_user_id: UUID
    surface: str
    record_count: int
    created_at: datetime


@router.get("/read-events", response_model=list[PersonalDataReadView])
def list_read_events(
    enterprise_id: UUID | None = None,
    person_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=100),  # noqa: B008
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[PersonalDataReadEvent]:
    """Auditor metadata, not free-text logs; non-admin callers receive 403."""
    stmt = select(PersonalDataReadEvent)
    if enterprise_id is not None:
        stmt = stmt.where(PersonalDataReadEvent.enterprise_id == enterprise_id)
    if person_id is not None:
        stmt = stmt.where(PersonalDataReadEvent.person_id == person_id)
    return list(db.scalars(
        stmt.order_by(PersonalDataReadEvent.created_at.desc(), PersonalDataReadEvent.id.desc())
        .limit(limit)
    ).all())
