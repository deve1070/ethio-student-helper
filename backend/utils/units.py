"""Sorting textbook/practice unit names in their natural (printed) order - "Unit 2" before "Unit 10",
not alphabetical (which would put "Unit 10" before "Unit 2"). Shared by anything that lists units:
practice (routes_practice.py) and Study Notes (notes/store.py) both."""

import re


def unit_sort_key(unit: str | None):
    m = re.search(r"\d+", unit or "")
    return (int(m.group()) if m else 10_000, unit or "")
