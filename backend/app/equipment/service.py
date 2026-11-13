"""Authoritative equipment/permit safety checks and mandatory credential gates.

Human sign-offs record assertions; they are NOT machine-interlock proof.
"""

import json
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.competence.models import PersonSkillAssessment, Skill, SkillScaleLevel
from app.availability.service import as_utc
from app.credentials.models import CredentialType, PersonCredential
from app.equipment.models import (
    AssetCredentialRequirement, AssetSkillRequirement, AssetDowntimeWindow,
    EquipmentAsset, EquipmentAuditEvent,
    WorkEquipmentLink, WorkPermit,
)
from app.identity.models import UserAccount
from app.personnel.models import Person
from app.work.models import WorkOrder


def link_for(db: Session, order_id: UUID) -> WorkEquipmentLink | None:
    return db.scalar(select(WorkEquipmentLink).where(
        WorkEquipmentLink.work_order_id == order_id
    ))


def latest_permit(db: Session, order_id: UUID) -> WorkPermit | None:
    return db.scalar(select(WorkPermit).where(
        WorkPermit.work_order_id == order_id
    ).order_by(WorkPermit.version.desc()).limit(1))



def conflicting_downtime(
    db: Session, enterprise_id: UUID, asset_id: UUID, start, end,
) -> list[AssetDowntimeWindow]:
    """Half-open [start, end) overlap; cancelled windows never block.

    The caller must hold the enterprise lock before performing writes that
    rely on this query. Read-side checks do not assert a future guarantee.
    """
    return list(db.scalars(select(AssetDowntimeWindow).where(
        AssetDowntimeWindow.enterprise_id == enterprise_id,
        AssetDowntimeWindow.asset_id == asset_id,
        AssetDowntimeWindow.cancelled_at.is_(None),
        AssetDowntimeWindow.starts_at < as_utc(end),
        AssetDowntimeWindow.ends_at > as_utc(start),
    ).order_by(
        AssetDowntimeWindow.starts_at, AssetDowntimeWindow.id,
    )).all())


def downtime_problems(db: Session, order: WorkOrder) -> list[str]:
    """Machine calendar is an extra gate for equipment-linked orders only."""
    link = link_for(db, order.id)
    if link is None:
        return []
    if conflicting_downtime(
        db, order.enterprise_id, link.asset_id, order.starts_at, order.ends_at
    ):
        return ["EQUIPMENT_DOWNTIME_CONFLICT"]
    return []

def equipment_problems(db: Session, order: WorkOrder) -> list[str]:
    """Evaluate the newest permit every time, including start, resume and recheck."""
    link = link_for(db, order.id)
    if link is None:
        return []  # Unlinked legacy/office work has no equipment-permit policy.
    asset = db.get(EquipmentAsset, link.asset_id)
    if asset is None or asset.enterprise_id != order.enterprise_id:
        return ["EQUIPMENT_MISSING"]
    reasons = []
    if asset.status != "active":
        reasons.append("EQUIPMENT_OUT_OF_SERVICE")
    reasons.extend(downtime_problems(db, order))
    permit = latest_permit(db, order.id)
    if permit is None or permit.status != "approved" or permit.approved_by is None:
        reasons.append("WORK_PERMIT_NOT_APPROVED")
    elif not (
        permit.hazards_reviewed
        and permit.energy_isolation_attested
        and permit.area_access_attested
        and permit.evidence_reference
    ):
        reasons.append("WORK_PERMIT_INCOMPLETE")
    return reasons


def required_asset_credentials(
    db: Session, order: WorkOrder, person: Person, days: set[date],
) -> tuple[list[str], set[UUID]]:
    """AND all asset-specific requirements with existing activity requirements.

    Never substitutes an asset credential for the base work activity permits.
    """
    link = link_for(db, order.id)
    if link is None:
        return [], set()
    asset = db.get(EquipmentAsset, link.asset_id)
    if asset is None or asset.enterprise_id != order.enterprise_id:
        return ["EQUIPMENT_MISSING"], set()
    problems: list[str] = []
    matches: set[UUID] = set()
    if asset.status != "active":
        problems.append("EQUIPMENT_OUT_OF_SERVICE")
    for req in db.scalars(select(AssetCredentialRequirement).where(
        AssetCredentialRequirement.enterprise_id == order.enterprise_id,
        AssetCredentialRequirement.asset_id == asset.id,
    )).all():
        kind = db.get(CredentialType, req.type_id)
        if kind is None or kind.enterprise_id != order.enterprise_id:
            problems.append("INVALID_EQUIPMENT_CREDENTIAL_POLICY")
            continue
        records = db.scalars(select(PersonCredential).where(
            PersonCredential.enterprise_id == order.enterprise_id,
            PersonCredential.person_id == person.id,
            PersonCredential.type_id == kind.id,
        )).all()
        for on in sorted(days):
            valid = [
                row for row in records
                if row.status == "verified"
                and row.revoked_at is None
                and row.issued_on <= on
                and row.valid_from <= on
                and (row.expires_on is None or on <= row.expires_on)
                and (not kind.requires_expiry or row.expires_on is not None)
            ]
            if not valid:
                problems.append(f"EQUIPMENT_CREDENTIAL_MISSING:{kind.code}:{on.isoformat()}")
            else:
                matches.add(valid[0].id)
    return problems, matches



def required_asset_skills(
    db: Session, order: WorkOrder, person: Person,
) -> tuple[list[str], set[UUID]]:
    """Check every asset policy against latest approved skill assessment.

    The asset policy augments, and never replaces, WorkSkillRequirement.
    An old higher rating cannot override a newer approved lower rating.
    """
    link = link_for(db, order.id)
    if link is None:
        return [], set()
    asset = db.get(EquipmentAsset, link.asset_id)
    if asset is None or asset.enterprise_id != order.enterprise_id:
        return ["EQUIPMENT_MISSING"], set()
    failures: list[str] = []
    matches: set[UUID] = set()
    for requirement in db.scalars(select(AssetSkillRequirement).where(
        AssetSkillRequirement.enterprise_id == order.enterprise_id,
        AssetSkillRequirement.asset_id == asset.id,
    )).all():
        skill = db.get(Skill, requirement.skill_id)
        threshold = db.get(SkillScaleLevel, requirement.min_level_id)
        if (
            skill is None or not skill.is_active
            or skill.enterprise_id != order.enterprise_id
            or skill.scale_id != requirement.scale_id
            or threshold is None or threshold.scale_id != requirement.scale_id
        ):
            failures.append("INVALID_EQUIPMENT_SKILL_POLICY")
            continue
        assessment = db.scalar(select(PersonSkillAssessment).where(
            PersonSkillAssessment.enterprise_id == order.enterprise_id,
            PersonSkillAssessment.person_id == person.id,
            PersonSkillAssessment.skill_id == skill.id,
            PersonSkillAssessment.status == "approved",
        ).order_by(
            PersonSkillAssessment.reviewed_at.desc(),
            PersonSkillAssessment.id.desc(),
        ).limit(1))
        if assessment is None:
            failures.append(f"EQUIPMENT_SKILL_UNVERIFIED:{skill.code}")
            continue
        rating = db.get(SkillScaleLevel, assessment.level_id)
        if rating is None or rating.scale_id != requirement.scale_id:
            failures.append(f"EQUIPMENT_SKILL_INVALID_RATING:{skill.code}")
        elif rating.ordinal < threshold.ordinal:
            failures.append(f"EQUIPMENT_SKILL_BELOW_MINIMUM:{skill.code}")
        else:
            matches.add(skill.id)
    return failures, matches

def audit(
    db: Session, actor: UserAccount, enterprise_id: UUID,
    action: str, subject_id: UUID, details: dict,
) -> None:
    db.add(EquipmentAuditEvent(
        enterprise_id=enterprise_id, actor_id=actor.id,
        action=action, subject_id=subject_id,
        details_json=json.dumps(details, ensure_ascii=False, default=str),
    ))
