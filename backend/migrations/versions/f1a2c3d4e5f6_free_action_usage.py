"""free action usage

Revision ID: f1a2c3d4e5f6
Revises: ac40bef3bbe2
Create Date: 2026-11-09 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a2c3d4e5f6'
down_revision: Union[str, None] = 'ac40bef3bbe2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'free_action_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feature', sa.String(length=32), nullable=False),
        sa.Column('resource_key', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint(
            "feature IN ('notes','elaborate','ask','explain','exam_solve')",
            name='ck_free_action_usage_feature',
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'feature', 'resource_key', name='uq_free_action_usage'),
    )
    op.create_index(
        op.f('ix_free_action_usage_user_id'), 'free_action_usage', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_free_action_usage_user_id'), table_name='free_action_usage')
    op.drop_table('free_action_usage')
