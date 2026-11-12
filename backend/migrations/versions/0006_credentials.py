"""Credential types, verified records, mandatory activity rules and audit.

Revision ID: 0006_credentials
Revises: 0005_competence
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_credentials"
down_revision: Union[str, None] = "0005_competence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credential_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("is_safety_critical", sa.Boolean(), nullable=False),
        sa.Column("requires_expiry", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_credential_type_tenant_id"),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_credential_type_code"),
        sa.CheckConstraint(
            "kind IN ('permit', 'certificate', 'qualification', 'training')",
            name="ck_credential_type_kind",
        ),
        sa.CheckConstraint(
            "NOT is_safety_critical OR requires_expiry", name="ck_safety_requires_expiry"
        ),
    )
    op.create_table(
        "person_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_reference", sa.String(180), nullable=False),
        sa.Column("issuer", sa.String(180), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("expires_on", sa.Date()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "submitted_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "reviewed_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.Column(
            "revoked_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.Text()),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"],
            name="fk_credential_person_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_credential_type_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'revoked')",
            name="ck_person_credential_status",
        ),
        sa.CheckConstraint(
            "expires_on IS NULL OR expires_on >= valid_from",
            name="ck_person_credential_validity",
        ),
    )
    op.create_index(
        "ix_person_credentials_person_type", "person_credentials", ["person_id", "type_id"]
    )
    op.create_table(
        "credential_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("activity_code", sa.String(64), nullable=False),
        sa.Column("type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_requirement_type_tenant",
        ),
        sa.UniqueConstraint(
            "enterprise_id", "activity_code", "type_id",
            name="uq_credential_activity_requirement",
        ),
    )
    op.create_index(
        "ix_credential_requirements_activity",
        "credential_requirements", ["enterprise_id", "activity_code"],
    )
    op.create_table(
        "credential_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("credential_audit_events")
    op.drop_index("ix_credential_requirements_activity", table_name="credential_requirements")
    op.drop_table("credential_requirements")
    op.drop_index("ix_person_credentials_person_type", table_name="person_credentials")
    op.drop_table("person_credentials")
    op.drop_table("credential_types")
