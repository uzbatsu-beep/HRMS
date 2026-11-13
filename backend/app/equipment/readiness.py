"""Read-only, redacted crew readiness assessment for equipment-linked work.

Reuses the central transactional team checker without persisting a check or
changing work status. This is an advisory point-in-time snapshot only.
"""

from sqlalchemy.orm import Session

from app.equipment.schemas import CrewReadinessSnapshot
from app.work.execution import team_safety_check
from app.work.models import WorkOrder


def snapshot(db: Session, order: WorkOrder) -> CrewReadinessSnapshot:
    checked = team_safety_check(db, order)
    codes = sorted({
        block.code
        for member in checked.members
        for block in member.candidate.blockers
    })
    if not any(member.role == "lead" for member in checked.members):
        codes = sorted(set(codes) | {"LEADER_NOT_ASSIGNED"})
    return CrewReadinessSnapshot(
        work_order_id=order.id, work_status=order.status,
        checked_at=checked.checked_at,
        last_persisted_safety_check_at=order.last_safety_check_at,
        leader_assigned=any(member.role == "lead" for member in checked.members),
        members_checked=len(checked.members),
        members_blocked=sum(not member.candidate.eligible for member in checked.members),
        equipment_blocker_codes=sorted({x.code for x in checked.equipment_blockers}),
        crew_blocker_codes=codes,
        gates_passed=checked.passed,
    )
