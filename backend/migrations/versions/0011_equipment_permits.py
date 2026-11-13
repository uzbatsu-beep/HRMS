"""Equipment register, asset credential gates, job targets and human work permits.

Revision ID: 0011_equipment_permits
Revises: 0010_configuration

Only application-level human attestations; not physical safety interlocks.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_equipment_permits"
down_revision: Union[str, None] = "0010_configuration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "equipment_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("serial_number", sa.String(120)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_asset_tenant_id"),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_asset_code"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_asset_unit_tenant",
        ),
        sa.CheckConstraint(
            "kind IN ('machine', 'robot', 'production_line', 'other')",
            name="ck_asset_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'out_of_service')", name="ck_asset_status",
        ),
    )
    op.create_table(
        "asset_credential_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("added_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "type_id", name="uq_asset_credential_requirement"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_asset_requirement_asset_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_asset_requirement_type_tenant",
        ),
    )
    op.create_table(
        "work_equipment_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("work_order_id", name="uq_work_equipment_single_target"),
        sa.UniqueConstraint(
            "enterprise_id", "work_order_id", name="uq_work_equipment_tenant_order"
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_work_equipment_order_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_work_equipment_asset_tenant",
        ),
    )
    op.create_table(
        "work_permits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("hazards_reviewed", sa.Boolean, nullable=False),
        sa.Column("energy_isolation_attested", sa.Boolean, nullable=False),
        sa.Column("area_access_attested", sa.Boolean, nullable=False),
        sa.Column("evidence_reference", sa.String(200)),
        sa.Column("prepared_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(400)),
        sa.UniqueConstraint("work_order_id", "version", name="uq_work_permit_version"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_equipment_links.enterprise_id", "work_equipment_links.work_order_id"],
            name="fk_work_permit_order_equipment_tenant",
        ),
        sa.CheckConstraint("version > 0", name="ck_work_permit_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'revoked')",
            name="ck_work_permit_status",
        ),
    )
    op.create_table(
        "equipment_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("details_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_equipment_audit_enterprise", "equipment_audit_events",
        ["enterprise_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_equipment_audit_enterprise", table_name="equipment_audit_events")
    op.drop_table("equipment_audit_events")
    op.drop_table("work_permits")
    op.drop_table("work_equipment_links")
    op.drop_table("asset_credential_requirements")
    op.drop_table("equipment_assets")
