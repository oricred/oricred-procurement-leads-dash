"""allow phone-only contacts

Revision ID: 20260720_nullable_contact_email
Revises: 20260715_streamline
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa


revision = "20260720_nullable_contact_email"
down_revision = "20260715_streamline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE contacts SET email = NULL WHERE email = ''")
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.alter_column("email", existing_type=sa.String(256), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE contacts SET email = '' WHERE email IS NULL")
    with op.batch_alter_table("contacts") as batch_op:
