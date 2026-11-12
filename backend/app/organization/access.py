"""Fail-closed organization-scope decisions for non-admin accounts."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models import UserAccount
from app.organization.models import OrganizationUnit, UserUnitScope


def allowed_unit_ids(db: Session, user: UserAccount, enterprise_id: UUID) -> set[UUID]:
    """Calculate allowed IDs from a user's explicit grants within one enterprise.

    Admins are installation-wide for this first release. Every other role is
    denied by default. Descendant grants follow the current hierarchy and are
    recalculated after a structural move; they are not cached across requests.
    """
    units = list(
        db.scalars(
            select(OrganizationUnit).where(OrganizationUnit.enterprise_id == enterprise_id)
        ).all()
    )
    if user.role == "admin":
        return {unit.id for unit in units}

    children: dict[UUID, list[UUID]] = defaultdict(list)
    unit_ids = {unit.id for unit in units}
    for unit in units:
        if unit.parent_id is not None:
            children[unit.parent_id].append(unit.id)

    grants = db.scalars(
        select(UserUnitScope).where(UserUnitScope.user_id == user.id)
    ).all()
    allowed: set[UUID] = set()
    for grant in grants:
        if grant.unit_id not in unit_ids:
            continue
        allowed.add(grant.unit_id)
        if not grant.include_descendants:
            continue
        pending = [grant.unit_id]
        visited: set[UUID] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            allowed.add(current)
            pending.extend(children[current])
    return allowed


def can_read_enterprise(db: Session, user: UserAccount, enterprise_id: UUID) -> bool:
    return user.role == "admin" or bool(allowed_unit_ids(db, user, enterprise_id))
