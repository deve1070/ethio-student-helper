"""referrals and password reset codes

Revision ID: ac40bef3bbe2
Revises: 0896ef413e5c
Create Date: 2026-11-05 09:49:57.626466

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ac40bef3bbe2'
down_revision: Union[str, None] = '0896ef413e5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same unambiguous alphabet as auth/referral.py's generate_referral_code - kept as a literal copy here
# rather than imported, since a migration is a frozen historical record and shouldn't depend on
# application code that's free to change later.
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _random_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def upgrade() -> None:
    op.add_column('users', sa.Column('referral_code', sa.String(length=16), nullable=True))
    op.add_column(
        'users',
        sa.Column('referred_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'users', sa.Column('referral_paid_count', sa.Integer(), nullable=False, server_default='0')
    )

    # referral_code must end up UNIQUE + NOT NULL, but existing rows have none yet - backfill each one
    # individually (not a single bulk UPDATE) so every existing user gets their OWN distinct code,
    # mirroring how a fresh signup through auth/referral.py would generate it.
    bind = op.get_bind()
    user_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM users")).fetchall()]
    used = set()
    for user_id in user_ids:
        code = _random_code()
        while code in used:
            code = _random_code()
        used.add(code)
        bind.execute(sa.text("UPDATE users SET referral_code = :code WHERE id = :id"), {"code": code, "id": user_id})

    op.alter_column('users', 'referral_code', nullable=False)
    op.create_unique_constraint('uq_users_referral_code', 'users', ['referral_code'])
    op.create_foreign_key(
        'fk_users_referred_by_user_id', 'users', 'users', ['referred_by_user_id'], ['id'], ondelete='SET NULL'
    )

    op.create_table(
        'password_reset_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_password_reset_codes_user_id'), 'password_reset_codes', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_password_reset_codes_user_id'), table_name='password_reset_codes')
    op.drop_table('password_reset_codes')

    op.drop_constraint('fk_users_referred_by_user_id', 'users', type_='foreignkey')
    op.drop_constraint('uq_users_referral_code', 'users', type_='unique')
    op.drop_column('users', 'referral_paid_count')
    op.drop_column('users', 'referred_by_user_id')
    op.drop_column('users', 'referral_code')
