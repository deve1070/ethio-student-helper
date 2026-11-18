"""record referral earnings as an amount

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users', sa.Column('referral_earned_etb', sa.Numeric(10, 2), server_default='0', nullable=False)
    )
    # Every referral so far was earned at the original 50 ETB reward.
    op.execute("UPDATE users SET referral_earned_etb = referral_paid_count * 50")


def downgrade() -> None:
    op.drop_column('users', 'referral_earned_etb')
