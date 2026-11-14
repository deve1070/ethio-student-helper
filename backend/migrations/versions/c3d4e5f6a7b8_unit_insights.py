"""unit insights

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f7
Create Date: 2026-11-14 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'unit_insights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=64), nullable=False),
        sa.Column('grade', sa.Integer(), nullable=True),
        sa.Column('unit', sa.String(length=255), nullable=False),
        sa.Column('concepts', sa.JSON(), nullable=False),
        sa.Column('styles', sa.JSON(), nullable=False),
        sa.Column('tips', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subject', 'grade', 'unit', name='uq_unit_insight'),
    )


def downgrade() -> None:
    op.drop_table('unit_insights')
