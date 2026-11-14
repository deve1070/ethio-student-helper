"""mass challenge

Revision ID: a1b2c3d4e5f7
Revises: f1a2c3d4e5f6
Create Date: 2026-11-09 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'f1a2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mass_challenges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('stream', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('subject', sa.String(length=64), nullable=False),
        sa.Column('grade', sa.Integer(), nullable=True),
        sa.Column('unit', sa.String(length=255), nullable=False),
        sa.Column('question_ids', sa.JSON(), nullable=False),
        sa.Column('opens_at', sa.DateTime(), nullable=False),
        sa.Column('question_seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', 'stream', name='uq_mass_challenge_date_stream'),
    )

    op.create_table(
        'mass_challenge_polls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('telegram_poll_id', sa.String(length=64), nullable=False),
        sa.Column('sent_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['challenge_id'], ['mass_challenges.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['esslce_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_poll_id'),
    )
    op.create_index(
        op.f('ix_mass_challenge_polls_challenge_id'), 'mass_challenge_polls', ['challenge_id'], unique=False
    )
    op.create_index(
        op.f('ix_mass_challenge_polls_telegram_poll_id'), 'mass_challenge_polls', ['telegram_poll_id'], unique=True
    )

    op.create_table(
        'private_group_memberships',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('joined_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.add_column('esslce_attempts', sa.Column('mass_challenge_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_esslce_attempts_mass_challenge_id', 'esslce_attempts', 'mass_challenges',
        ['mass_challenge_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_esslce_attempts_mass_challenge_id'), 'esslce_attempts', ['mass_challenge_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_esslce_attempts_mass_challenge_id'), table_name='esslce_attempts')
    op.drop_constraint('fk_esslce_attempts_mass_challenge_id', 'esslce_attempts', type_='foreignkey')
    op.drop_column('esslce_attempts', 'mass_challenge_id')

    op.drop_table('private_group_memberships')

    op.drop_index(op.f('ix_mass_challenge_polls_telegram_poll_id'), table_name='mass_challenge_polls')
    op.drop_index(op.f('ix_mass_challenge_polls_challenge_id'), table_name='mass_challenge_polls')
    op.drop_table('mass_challenge_polls')

    op.drop_table('mass_challenges')
