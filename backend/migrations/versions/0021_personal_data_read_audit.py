"""Metadata-only, enterprise-bound audit of sensitive successful API reads.

Revision ID: 0021_personal_data_read_audit
Revises: 0020_workflow_v2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Match the ORM CHECK constraint on user_unit_permissions.
BEFORE_RIGHTS = (
    "code IN ('equipment.policy.read', 'equipment.policy.propose', "
    "'equipment.policy.review', 'competence.assessment.review', "
    "'credentials.record.review', 'work.order.create', 'work.order.assign', "
    "'work.crew.manage', 'work.order.priority', 'work.order.start', "
    "'work.order.complete', 'work.order.cancel', 'work.order.revalidate', "
    "'work.order.hold', 'work.order.resume')"
)
AFTER_RIGHTS = BEFORE_RIGHTS.replace(
    "'credentials.record.review',",
    "'credentials.record.review', 'credentials.record.read_sensitive',",
)

revision: str = "0021_personal_data_read_audit"
down_revision: Union[str, None] = "0020_workflow_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL rejects new grants until its persisted CHECK constraint is expanded.
    op.drop_constraint("ck_unit_permission_code", "user_unit_permissions", type_="check")
    op.create_check_constraint("ck_unit_permission_code", "user_unit_permissions", AFTER_RIGHTS)
    op.create_table(
        "personal_data_read_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("surface", sa.String(48), nullable=False),
        sa.Column("record_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"], ["persons.enterprise_id", "persons.id"],
            name="fk_personal_data_read_person_tenant",
        ),
        sa.CheckConstraint("record_count >= 0",
                           name="ck_personal_data_read_count_nonnegative"),
    )
    op.create_index("ix_personal_data_read_enterprise_time", "personal_data_read_events",
                    ["enterprise_id", "created_at"])
    op.create_index("ix_personal_data_read_person_time", "personal_data_read_events",
                    ["person_id", "created_at"])


def downgrade() -> None:
    from sqlalchemy import text

    if op.get_bind().execute(text(
        "SELECT COUNT(*) FROM user_unit_permissions "
        "WHERE code = 'credentials.record.read_sensitive'"
    )).scalar_one():
        raise RuntimeError("Cannot downgrade while sensitive-read grants exist")
    # Destructive: require signed retention/legal approval before dropping any audit history.
    op.drop_index("ix_personal_data_read_person_time", table_name="personal_data_read_events")
    op.drop_index("ix_personal_data_read_enterprise_time", table_name="personal_data_read_events")
    op.drop_table("personal_data_read_events")
    op.drop_constraint("ck_unit_permission_code", "user_unit_permissions", type_="check")
    op.create_check_constraint("ck_unit_permission_code", "user_unit_permissions", BEFORE_RIGHTS)
