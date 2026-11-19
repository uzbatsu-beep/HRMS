"""Persist failure counters across processes for bounded login attempts.

Revision ID: 0018_login_failure_buckets
Revises: 0017_personnel_review_grants
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_login_failure_buckets"
down_revision: Union[str, None] = "0017_personnel_review_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_failure_buckets",
        sa.Column("bucket_key", sa.String(length=64), primary_key=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("failure_count > 0", name="ck_login_failure_positive"),
    )
    op.create_index(
        "ix_login_failure_buckets_expires_at", "login_failure_buckets", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_login_failure_buckets_expires_at", table_name="login_failure_buckets")
    op.drop_table("login_failure_buckets")
