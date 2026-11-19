"""store why each wrong option looked right, per question

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-19 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quiz_questions', sa.Column('wrong_option_notes', postgresql.JSONB(), nullable=True))
    op.add_column('esslce_questions', sa.Column('wrong_option_notes', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('esslce_questions', 'wrong_option_notes')
    op.drop_column('quiz_questions', 'wrong_option_notes')
