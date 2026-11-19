"""remember which exam questions the channel has posted, and where each student signed up from

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('esslce_questions', sa.Column('channel_posted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('signup_source', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'signup_source')
    op.drop_column('esslce_questions', 'channel_posted_at')
