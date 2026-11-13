"""Append-only asset-specific minimum skill policy.

Revision ID: 0012_asset_skill_gates
Revises: 0011_equipment_permits
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_asset_skill_gates"
down_revision: Union[str, None] = "0011_equipment_permits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_skill_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("min_level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "added_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("asset_id", "skill_id", name="uq_asset_required_skill"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_asset_skill_asset_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_asset_skill_tenant_scale",
        ),
        sa.ForeignKeyConstraint(
            ["scale_id", "min_level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_asset_skill_min_level_scale",
        ),
    )


def downgrade() -> None:
    op.drop_table("asset_skill_requirements")
