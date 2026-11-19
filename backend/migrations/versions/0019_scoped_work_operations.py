"""Add exact-unit work management operation grants.

Revision ID: 0019_scoped_work_operations
Revises: 0018_login_failure_buckets
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0019_scoped_work_operations"
down_revision: Union[str, None] = "0018_login_failure_buckets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = "code IN ('equipment.policy.read', 'equipment.policy.propose', 'equipment.policy.review', 'competence.assessment.review', 'credentials.record.review')"
AFTER = "code IN ('equipment.policy.read', 'equipment.policy.propose', 'equipment.policy.review', 'competence.assessment.review', 'credentials.record.review', 'work.order.create', 'work.order.assign', 'work.crew.manage', 'work.order.priority', 'work.order.start', 'work.order.complete', 'work.order.cancel', 'work.order.revalidate', 'work.order.hold', 'work.order.resume')"


def upgrade() -> None:
    op.drop_constraint("ck_unit_permission_code", "user_unit_permissions", type_="check")
    op.create_check_constraint("ck_unit_permission_code", "user_unit_permissions", AFTER)


def downgrade() -> None:
    count = op.get_bind().execute(text(
        "SELECT COUNT(*) FROM user_unit_permissions WHERE code LIKE 'work.%'"
    )).scalar_one()
    if count:
        raise RuntimeError("Cannot downgrade while work operation grants exist")
    op.drop_constraint("ck_unit_permission_code", "user_unit_permissions", type_="check")
    op.create_check_constraint("ck_unit_permission_code", "user_unit_permissions", BEFORE)
