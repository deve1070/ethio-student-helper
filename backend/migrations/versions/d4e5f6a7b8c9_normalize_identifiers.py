"""one stored format for phone numbers and emails

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from auth.identifiers import normalize_email, normalize_phone


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rewrite stored phone numbers and emails into the format signup now produces. A number that
    # isn't a valid Ethiopian mobile is left as it is. Two accounts that would collapse onto the same
    # value stop the migration, since merging accounts needs a person to decide.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, phone_number, email FROM users")).fetchall()
    updates, seen_phone, seen_email = [], {}, {}
    for user_id, phone, email in rows:
        new_phone = phone
        if phone:
            try:
                new_phone = normalize_phone(phone)
            except ValueError:
                pass
        new_email = normalize_email(email) if email else email
        for value, seen, kind in ((new_phone, seen_phone, 'phone'), (new_email, seen_email, 'email')):
            if value is None:
                continue
            if value in seen:
                raise RuntimeError(f"users {seen[value]} and {user_id} share the {kind} {value} once normalized")
            seen[value] = user_id
        if (new_phone, new_email) != (phone, email):
            updates.append({'id': user_id, 'phone': new_phone, 'email': new_email})
    for u in updates:
        conn.execute(sa.text("UPDATE users SET phone_number = :phone, email = :email WHERE id = :id"), u)


def downgrade() -> None:
    pass  # the original spellings aren't kept, and every lookup accepts the normalized form
