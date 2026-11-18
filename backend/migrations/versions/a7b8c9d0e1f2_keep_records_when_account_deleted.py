"""keep payment and payout records when an account is deleted; allow deleting reviewers

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column): each foreign key to users.id becomes ON DELETE SET NULL
COLUMNS = [
    ('payments', 'user_id'),
    ('referral_payouts', 'user_id'),
    ('exam_answers', 'reviewed_by'),
    ('exam_question_submissions', 'submitted_by'),
]


def _fk_name(table: str, column: str) -> str:
    # looked up rather than assumed: the existing constraints were named by Postgres or by older
    # migrations, not by one convention
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk['constrained_columns'] == [column] and fk['referred_table'] == 'users':
            return fk['name']
    raise RuntimeError(f'no foreign key from {table}.{column} to users')


def _set_rule(ondelete: str | None) -> None:
    for table, column in COLUMNS:
        op.drop_constraint(_fk_name(table, column), table, type_='foreignkey')
        op.create_foreign_key(f'fk_{table}_{column}_users', table, 'users', [column], ['id'], ondelete=ondelete)


def upgrade() -> None:
    op.alter_column('payments', 'user_id', nullable=True)
    op.alter_column('referral_payouts', 'user_id', nullable=True)
    _set_rule('SET NULL')


def downgrade() -> None:
    op.execute("DELETE FROM payments WHERE user_id IS NULL")
    op.execute("DELETE FROM referral_payouts WHERE user_id IS NULL")
    for table, column in COLUMNS:
        op.drop_constraint(f'fk_{table}_{column}_users', table, type_='foreignkey')
    for table, column, rule in [
        ('payments', 'user_id', 'CASCADE'), ('referral_payouts', 'user_id', 'CASCADE'),
        ('exam_answers', 'reviewed_by', None), ('exam_question_submissions', 'submitted_by', None),
    ]:
        op.create_foreign_key(None, table, 'users', [column], ['id'], ondelete=rule)
    op.alter_column('payments', 'user_id', nullable=False)
    op.alter_column('referral_payouts', 'user_id', nullable=False)
