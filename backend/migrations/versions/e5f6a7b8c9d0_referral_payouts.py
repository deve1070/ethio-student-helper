"""referral payouts

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-17 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'referral_payouts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount_etb', sa.Numeric(10, 2), nullable=False),
        sa.Column('method', sa.String(length=16), nullable=False),
        sa.Column('account_number', sa.String(length=32), nullable=False),
        sa.Column('account_name', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('admin_note', sa.Text(), nullable=True),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("method IN ('telebirr','cbe')", name='ck_referral_payout_method'),
        sa.CheckConstraint("status IN ('pending','paid','rejected')", name='ck_referral_payout_status'),
        sa.CheckConstraint('amount_etb > 0', name='ck_referral_payout_amount'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_referral_payouts_user_id', 'referral_payouts', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_referral_payouts_user_id', table_name='referral_payouts')
    op.drop_table('referral_payouts')
