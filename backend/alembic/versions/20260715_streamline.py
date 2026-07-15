"""streamline award lead workflow

Revision ID: 20260715_streamline
Revises:
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa

revision = "20260715_streamline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("credit_decision", sa.String(32), nullable=True))
    op.add_column("opportunities", sa.Column("lost_reason", sa.Text(), nullable=True))
    op.add_column("opportunities", sa.Column("conditions_checklist", sa.JSON(), nullable=True))
    op.add_column("opportunities", sa.Column("needs_enrichment", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("uq_opportunities_award_id", "opportunities", ["award_id"], unique=True, postgresql_where=sa.text("award_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_opportunities_award_id", table_name="opportunities")
    op.drop_column("opportunities", "needs_enrichment")
    op.drop_column("opportunities", "conditions_checklist")
    op.drop_column("opportunities", "lost_reason")
    op.drop_column("opportunities", "credit_decision")