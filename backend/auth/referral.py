"""Referral codes: every user gets one, generated once at signup and never changed. See
api/routes_auth.py's signup() for how a NEW user's optional referral_code field links them to
whoever referred them, and payments/referral.py for how that referrer's count gets credited."""

import secrets

from sqlalchemy.orm import Session

from db.models import User

# Deliberately excludes 0/O and 1/I - a referral code is meant to be read aloud or typed from memory
# (shared over chat, read off a phone screen to a friend), and those pairs are the ones people actually
# misread/mistype in practice.
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CODE_LENGTH = 8


def generate_referral_code(db: Session) -> str:
    """A fresh, unused 8-character code. A collision is astronomically unlikely (33^8 possibilities)
    but checked for anyway, since this column is UNIQUE and a clash would otherwise surface as a raw
    IntegrityError instead of a clean retry."""
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
        if db.query(User).filter(User.referral_code == code).one_or_none() is None:
            return code
