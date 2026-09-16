"""One strict calendar-date boundary for journals, ledgers and report cutoffs."""

import re
from datetime import date


def accounting_date(value: object) -> date:
    """Accept date (never datetime) or an exact YYYY-MM-DD calendar string."""
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("must be a calendar date or YYYY-MM-DD string")
