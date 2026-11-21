"""Allowlisted, fail-closed access logging for sensitive successful reads."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.identity.models import UserAccount
from app.privacy.models import PersonalDataReadEvent

READ_SURFACES = frozenset({
    "personnel.list",
    "personnel.detail",
    "credentials.list",
    "credentials.eligibility",
    "competence.assessments",
    "competence.matrix",
})


def record_personal_data_read(
    db: Session, user: UserAccount, enterprise_id: UUID,
    surface: str, *, person_id: UUID | None = None, count: int = 0,
) -> None:
    """Persist after successful scope check, before releasing any sensitive response.

    Deliberately excludes queries, search input, names, notes, document content and IP.
    A failed audit write fails the request; sensitive data must not escape unlogged.
    """
    if surface not in READ_SURFACES or count < 0:
        raise ValueError("Invalid privacy read audit metadata")
    db.add(PersonalDataReadEvent(
        enterprise_id=enterprise_id, person_id=person_id,
        actor_user_id=user.id, surface=surface, record_count=count,
    ))
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Read audit unavailable") from exc
