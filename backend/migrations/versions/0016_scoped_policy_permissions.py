"""Scoped operation grants for equipment policy governance.

Revision ID: 0016_scoped_policy_permissions
Revises: 0015_asset_skill_policy_versions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_scoped_policy_permissions"
down_revision: Union[str, None] = "0015_asset_skill_policy_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_unit_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "unit_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_units.id"), nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column(
            "granted_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "unit_id", "code", name="uq_user_unit_permission_grant"
        ),
        sa.CheckConstraint(
            "code IN ('equipment.policy.read', 'equipment.policy.propose', "
            "'equipment.policy.review')",
            name="ck_unit_permission_code",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_unit_permissions")
