"""study plan weeks and note views

Revision ID: 0896ef413e5c
Revises: b5fc7992aa61
Create Date: 2026-11-05 09:09:11.504642

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0896ef413e5c'
down_revision: Union[str, None] = 'b5fc7992aa61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # study_plan_days -> study_plan_weeks: the Study Plan feature moved from a single-day task list to
    # a real multi-day plan tied to the exam countdown (docs/dev_plans/rigorous_study_planner.md) - the
    # old table's shape (one row per calendar day) can't represent that, so it's dropped outright rather
    # than kept behind a flag. No data migration: study_plan_days was always a regenerable cache
    # (studyplan/planner.py decides it fresh from the student's live progress), never a record anyone
    # needs to keep.
    op.drop_table('study_plan_days')

    op.create_table(
        'study_plan_weeks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('week_start_date', sa.Date(), nullable=False),
        sa.Column('days', sa.JSON(), nullable=False),
        sa.Column('day_rationales', sa.JSON(), nullable=False),
        sa.Column('weekly_note', sa.Text(), nullable=False),
        sa.Column('realistic', sa.Boolean(), nullable=False),
        sa.Column('shortfall_minutes', sa.Integer(), nullable=False),
        sa.Column('profile_snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'week_start_date', name='uq_study_plan_week'),
    )
    op.create_index(op.f('ix_study_plan_weeks_user_id'), 'study_plan_weeks', ['user_id'], unique=False)

    # Per-student "I opened this Study Note" log - the global study_notes cache (one row per unit,
    # shared by every student) has no per-student signal on its own; this is the curriculum-coverage
    # input studyplan/profile.py needs that attempt history alone can't provide.
    op.create_table(
        'study_note_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('grade', sa.SmallInteger(), nullable=False),
        sa.Column('subject', sa.String(length=64), nullable=False),
        sa.Column('unit', sa.String(length=255), nullable=False),
        sa.Column('first_viewed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'grade', 'subject', 'unit', name='uq_study_note_view'),
    )
    op.create_index(op.f('ix_study_note_views_user_id'), 'study_note_views', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_study_note_views_user_id'), table_name='study_note_views')
    op.drop_table('study_note_views')

    op.drop_index(op.f('ix_study_plan_weeks_user_id'), table_name='study_plan_weeks')
    op.drop_table('study_plan_weeks')

    op.create_table(
        'study_plan_days',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_date', sa.Date(), nullable=False),
        sa.Column('tasks', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'plan_date', name='uq_study_plan_day'),
    )
    op.create_index(op.f('ix_study_plan_days_user_id'), 'study_plan_days', ['user_id'], unique=False)
