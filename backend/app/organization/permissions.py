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


PERMISSION_CODES = (
    "equipment.policy.read",
    "equipment.policy.propose",
    "equipment.policy.review",
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
        "can_read": any(can(db, user, unit, code) for code in PERMISSION_CODES),
        "can_propose": can(db, user, unit, "equipment.policy.propose"),
        "can_review": can(db, user, unit, "equipment.policy.review"),
    }
