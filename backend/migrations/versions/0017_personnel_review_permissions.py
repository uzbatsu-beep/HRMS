"""Allow scoped independent verification of skills and personnel credentials.

Revision ID: 0017_personnel_review_grants
Revises: 0016_scoped_policy_permissions
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017_personnel_review_grants"
down_revision: Union[str, None] = "0016_scoped_policy_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = (
    "code IN ('equipment.policy.read', 'equipment.policy.propose', "
    "'equipment.policy.review')"
)
AFTER = (
    "code IN ('equipment.policy.read', 'equipment.policy.propose', "
    "'equipment.policy.review', 'competence.assessment.review', "
    "'credentials.record.review')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_unit_permission_code", "user_unit_permissions", type_="check"
    )
    op.create_check_constraint(
        "ck_unit_permission_code", "user_unit_permissions", AFTER
    )


def downgrade() -> None:
    # Never discard delegated grants or turn them into invalid historical rows.
    # Reject downgrade before constraint replacement if either code is in use.
    from sqlalchemy import text

    session = op.get_bind()
    used = session.execute(text(
        "SELECT COUNT(*) FROM user_unit_permissions "
        "WHERE code IN ('competence.assessment.review', 'credentials.record.review')"
    )).scalar_one()
    if used:
        raise RuntimeError("Cannot downgrade while personnel reviewer grants exist")
    op.drop_constraint(
        "ck_unit_permission_code", "user_unit_permissions", type_="check"
    )
    op.create_check_constraint(
        "ck_unit_permission_code", "user_unit_permissions", BEFORE
    )
