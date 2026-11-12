"""Fail-closed, reusable eligibility evaluation for mandatory work permits."""

import json
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.credentials.models import (
    CredentialAuditEvent, CredentialRequirement, CredentialType, PersonCredential,
)
from app.credentials.schemas import EligibilityBlocker, EligibilityCheck, EligibilityResult
from app.identity.models import UserAccount
from app.organization.models import Enterprise
from app.personnel.models import Person, WorkforceResource
from app.personnel.service import current_assignment


def commit_safe(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting credentials data") from exc


def flush_safe(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting credentials data") from exc


def lock_enterprise(db: Session, enterprise_id: UUID) -> None:
    db.execute(select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update())


def audit(
    db: Session, actor: UserAccount, enterprise_id: UUID, action: str,
    subject_id: UUID, details: dict[str, object],
) -> None:
    db.add(
        CredentialAuditEvent(
            enterprise_id=enterprise_id, actor_id=actor.id, action=action,
            subject_id=subject_id,
            details_json=json.dumps(details, ensure_ascii=False, default=str),
        )
    )


def evaluate_activity(
    db: Session, person: Person, activity_code: str, on: date | None = None
) -> EligibilityResult:
    """Check mandatory requirements without relying on UI, caller role or skills.

    This predicate is intended to be called *inside* the future work assignment
    transaction, after the caller's personnel access has been verified. A positive
    result is not a legal authorization or independent document authentication.
    """
    when = on or date.today()
    requirements = list(
        db.scalars(
            select(CredentialRequirement).where(
                CredentialRequirement.enterprise_id == person.enterprise_id,
                CredentialRequirement.activity_code == activity_code.lower(),
            )
        ).all()
    )
    blockers: list[EligibilityBlocker] = []
    matched: list[EligibilityCheck] = []
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person.id)
    )
    if person.archived_at is not None or resource is None or not resource.is_active:
        blockers.append(
            EligibilityBlocker(
                code="INACTIVE_PERSON", type_id=None, message="Person or resource is inactive",
            )
        )
    elif current_assignment(db, resource.id, when) is None:
        blockers.append(
            EligibilityBlocker(
                code="NO_ASSIGNMENT", type_id=None,
                message="No primary assignment at the requested date",
            )
        )

    if not requirements:
        blockers.append(
            EligibilityBlocker(
                code="NO_POLICY", type_id=None,
                message="No mandatory credential policy has been configured for this activity",
            )
        )

    for required in requirements:
        kind = db.get(CredentialType, required.type_id)
        if kind is None or kind.enterprise_id != person.enterprise_id:
            blockers.append(
                EligibilityBlocker(
                    code="INVALID_POLICY", type_id=required.type_id,
                    message="Required document type is missing or belongs to another enterprise",
                )
            )
            continue
        candidates = list(
            db.scalars(
                select(PersonCredential).where(
                    PersonCredential.person_id == person.id,
                    PersonCredential.enterprise_id == person.enterprise_id,
                    PersonCredential.type_id == kind.id,
                )
            ).all()
        )
        approved = [
            record for record in candidates
            if record.status == "verified"
            and record.revoked_at is None
            and record.issued_on <= when
            and record.valid_from <= when
            and (record.expires_on is None or when <= record.expires_on)
            and (not kind.requires_expiry or record.expires_on is not None)
        ]
        if approved:
            approved.sort(
                key=lambda row: (row.expires_on or date.max, row.valid_from), reverse=True
            )
            chosen = approved[0]
            matched.append(
                EligibilityCheck(
                    type_id=kind.id, credential_id=chosen.id, expires_on=chosen.expires_on,
                )
            )
            continue

        if not candidates:
            reason = "MISSING_CREDENTIAL"
        elif any(item.status == "revoked" for item in candidates):
            reason = "REVOKED_CREDENTIAL"
        elif any(
            item.status == "verified"
            and item.expires_on is not None and item.expires_on < when
            for item in candidates
        ):
            reason = "EXPIRED_CREDENTIAL"
        elif any(item.status == "verified" and item.valid_from > when for item in candidates):
            reason = "NOT_YET_VALID"
        elif any(
            item.status == "verified" and kind.requires_expiry and item.expires_on is None
            for item in candidates
        ):
            reason = "MISSING_EXPIRATION"
        elif any(item.status == "pending" for item in candidates):
            reason = "UNVERIFIED_CREDENTIAL"
        elif any(item.status == "rejected" for item in candidates):
            reason = "REJECTED_CREDENTIAL"
        else:
            reason = "INVALID_CREDENTIAL"
        blockers.append(
            EligibilityBlocker(
                code=reason, type_id=kind.id,
                message=f"Mandatory credential '{kind.code}' is not valid and verified",
            )
        )
    return EligibilityResult(
        person_id=person.id, enterprise_id=person.enterprise_id,
        activity_code=activity_code.lower(), checked_on=when,
        eligible=not blockers, blockers=blockers, valid_credentials=matched,
    )
