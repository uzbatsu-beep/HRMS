"""Operation grants supplement, never replace, organizational unit visibility.

Non-admin rights are limited to the exact asset unit. Admins keep legacy
global capabilities. Grants are queried per request, not session-cached, so
revocations take effect for existing authenticated sessions immediately.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models import UserAccount
from app.organization.access import allowed_unit_ids
from app.organization.models import OrganizationUnit, UserUnitPermission
from app.personnel.models import Person, WorkforceResource
from app.personnel.service import current_assignment


PERMISSION_CODES = (
    "equipment.policy.read",
    "equipment.policy.propose",
    "equipment.policy.review",
    "competence.assessment.review",
    "credentials.record.review",
)


def can(db: Session, user: UserAccount, unit: OrganizationUnit, code: str) -> bool:
    if code not in PERMISSION_CODES or not user.is_active:
        return False
    if user.role == "admin":
        return True
    if unit.id not in allowed_unit_ids(db, user, unit.enterprise_id):
        return False
    granted = db.scalar(select(UserUnitPermission.id).where(
        UserUnitPermission.user_id == user.id,
        UserUnitPermission.unit_id == unit.id,
        UserUnitPermission.code == code,
    ))
    return granted is not None


def capabilities(db: Session, user: UserAccount, unit: OrganizationUnit) -> dict[str, bool]:
    return {
        "can_read": any(can(db, user, unit, code) for code in (
            "equipment.policy.read", "equipment.policy.propose",
            "equipment.policy.review",
        )),
        "can_propose": can(db, user, unit, "equipment.policy.propose"),
        "can_review": can(db, user, unit, "equipment.policy.review"),
    }



def can_review_person(
    db: Session, user: UserAccount, person: Person, code: str,
) -> bool:
    """Credential/skill reviewer: legacy scoped management OR exact-unit grant.

    The caller also requires ordinary Person visibility. An exact-unit grant
    alone never exposes private person records or changes a login role.
    """
    if code not in {"competence.assessment.review", "credentials.record.review"}:
        return False
    if not user.is_active or person.archived_at is not None:
        return False
    if user.role in {"admin", "manager"}:
        return True
    resource = db.scalar(select(WorkforceResource).where(
        WorkforceResource.person_id == person.id,
        WorkforceResource.enterprise_id == person.enterprise_id,
        WorkforceResource.is_active.is_(True),
    ))
    if resource is None:
        return False
    assignment = current_assignment(db, resource.id)
    if assignment is None or assignment.enterprise_id != person.enterprise_id:
        return False
    unit = db.get(OrganizationUnit, assignment.unit_id)
    return bool(unit and can(db, user, unit, code))
