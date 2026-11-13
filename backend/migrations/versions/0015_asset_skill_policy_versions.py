"""Versioned, independently approved increases to equipment skill thresholds.

Revision ID: 0015_asset_skill_policy_versions
Revises: 0014_asset_policy_governance
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_asset_skill_policy_versions"
down_revision: Union[str, None] = "0014_asset_policy_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_asset_skill_tenant_id", "asset_skill_requirements", ["enterprise_id", "id"]
    )
    op.add_column(
        "asset_policy_proposals", sa.Column("expected_version", sa.Integer())
    )
    op.drop_constraint(
        "ck_policy_proposal_kind_payload", "asset_policy_proposals", type_="check"
    )
    op.create_check_constraint(
        "ck_policy_proposal_kind_payload", "asset_policy_proposals",
        "(kind = 'credential' AND credential_type_id IS NOT NULL "
        "AND skill_id IS NULL AND scale_id IS NULL AND min_level_id IS NULL "
        "AND expected_version IS NULL) OR "
        "(kind = 'skill' AND credential_type_id IS NULL "
        "AND skill_id IS NOT NULL AND scale_id IS NOT NULL AND min_level_id IS NOT NULL "
        "AND expected_version IS NULL) OR "
        "(kind = 'skill_upgrade' AND credential_type_id IS NULL "
        "AND skill_id IS NOT NULL AND scale_id IS NOT NULL AND min_level_id IS NOT NULL "
        "AND expected_version IS NOT NULL AND expected_version >= 1)",
    )
    op.create_table(
        "asset_skill_policy_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("min_level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "proposal_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_policy_proposals.id"), nullable=False,
        ),
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "requirement_id", "version", name="uq_asset_skill_revision_version",
        ),
        sa.UniqueConstraint("proposal_id", name="uq_asset_skill_revision_proposal"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "requirement_id"],
            ["asset_skill_requirements.enterprise_id", "asset_skill_requirements.id"],
            name="fk_revision_skill_requirement_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["scale_id", "min_level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_revision_level_scale",
        ),
        sa.CheckConstraint("version >= 2", name="ck_asset_skill_revision_version"),
    )


def downgrade() -> None:
    # Deleting approved upgrades or their review history could silently
    # lower the enforced skill threshold on a downgraded backend. Fail closed.
    db = op.get_bind()
    count = db.execute(
        sa.text("SELECT COUNT(*) FROM asset_skill_policy_revisions")
    ).scalar_one()
    proposals = db.execute(
        sa.text("SELECT COUNT(*) FROM asset_policy_proposals "
                "WHERE kind = 'skill_upgrade'")
    ).scalar_one()
    if count or proposals:
        raise RuntimeError(
            "Refusing downgrade: skill policy revisions or proposal history exist"
        )
    op.drop_table("asset_skill_policy_revisions")
    op.drop_constraint(
        "ck_policy_proposal_kind_payload", "asset_policy_proposals", type_="check"
    )
    op.create_check_constraint(
        "ck_policy_proposal_kind_payload", "asset_policy_proposals",
        "(kind = 'credential' AND credential_type_id IS NOT NULL "
        "AND skill_id IS NULL AND scale_id IS NULL AND min_level_id IS NULL) OR "
        "(kind = 'skill' AND credential_type_id IS NULL "
        "AND skill_id IS NOT NULL AND scale_id IS NOT NULL AND min_level_id IS NOT NULL)",
    )
    op.drop_column("asset_policy_proposals", "expected_version")
    op.drop_constraint(
        "uq_asset_skill_tenant_id", "asset_skill_requirements", type_="unique",
    )
