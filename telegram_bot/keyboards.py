"""Tiny shared keyboard builders reused across guided flows - extracted once a third feature
(explain, after practice and exam already had their own copy) needed the exact same "Grade
9/10/11/12" button row, each just keyed to its own callback_data prefix."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def grade_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"Grade {g}", callback_data=f"{prefix}|{g}") for g in (9, 10, 11, 12)]]
    )
