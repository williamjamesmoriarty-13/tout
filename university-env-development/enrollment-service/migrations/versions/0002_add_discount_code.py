"""add discount_code (NOT NULL, sans default final)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enrollments",
        sa.Column("discount_code", sa.String(50), nullable=False, server_default="NONE"))
    op.alter_column("enrollments", "discount_code", server_default=None)


def downgrade():
    op.drop_column("enrollments", "discount_code")