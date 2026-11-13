"""Independently reviewed proposals for additive equipment policies.

Revision ID: 0014_asset_policy_governance
Revises: 0013_asset_downtime
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_asset_policy_governance"
down_revision: Union[str, None] = "0013_asset_downtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_policy_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("credential_type_id", postgresql.UUID(as_uuid=True)),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True)),
        sa.Column("scale_id", postgresql.UUID(as_uuid=True)),
        sa.Column("min_level_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.String(400), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "proposed_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "proposed_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "reviewed_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.String(400)),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_asset_policy_tenant_id"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_policy_proposal_asset_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "credential_type_id"],
            ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_policy_proposal_credential_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_policy_proposal_skill_scale_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["scale_id", "min_level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_policy_proposal_threshold_scale",
        ),
        sa.CheckConstraint(
            "(kind = 'credential' AND credential_type_id IS NOT NULL "
            "AND skill_id IS NULL AND scale_id IS NULL AND min_level_id IS NULL) OR "
            "(kind = 'skill' AND credential_type_id IS NULL "
            "AND skill_id IS NOT NULL AND scale_id IS NOT NULL AND min_level_id IS NOT NULL)",
            name="ck_policy_proposal_kind_payload",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_policy_proposal_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(status != 'pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_by != proposed_by AND review_note IS NOT NULL)",
            name="ck_policy_proposal_independent_review",
        ),
    )
    op.create_index(
        "uq_pending_asset_credential", "asset_policy_proposals",
        ["asset_id", "credential_type_id"], unique=True,
        postgresql_where=sa.text(
            "status = 'pending' AND credential_type_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "status = 'pending' AND credential_type_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_pending_asset_skill", "asset_policy_proposals",
        ["asset_id", "skill_id"], unique=True,
        postgresql_where=sa.text("status = 'pending' AND skill_id IS NOT NULL"),
        sqlite_where=sa.text("status = 'pending' AND skill_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pending_asset_skill", table_name="asset_policy_proposals")
    op.drop_index("uq_pending_asset_credential", table_name="asset_policy_proposals")
    op.drop_table("asset_policy_proposals")
