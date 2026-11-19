"""free trials, nudge records, schools and ambassadors

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'schools',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.add_column('users', sa.Column('nudges_off', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('school_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_school_id_schools', 'users', 'schools', ['school_id'], ['id'], ondelete='SET NULL')
    op.add_column('users', sa.Column('is_ambassador', sa.Boolean(), nullable=False, server_default='false'))
    op.create_table(
        'free_trials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('identifier', sa.String(length=255), nullable=False, unique=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False, unique=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'nudges_sent',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('sent_on', sa.Date(), nullable=False),
        sa.UniqueConstraint('user_id', 'key', name='uq_nudge_user_key'),
    )
    op.create_index('ix_nudges_sent_user_id', 'nudges_sent', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_nudges_sent_user_id', table_name='nudges_sent')
    op.drop_table('nudges_sent')
    op.drop_table('free_trials')
    op.drop_column('users', 'is_ambassador')
    op.drop_constraint('fk_users_school_id_schools', 'users', type_='foreignkey')
    op.drop_column('users', 'school_id')
    op.drop_column('users', 'nudges_off')
    op.drop_table('schools')
