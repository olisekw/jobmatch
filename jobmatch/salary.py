"""Salary parsing and hourly-rate derivation.

Understands the Slovak board formats ("900 - 1 000 eur/mesiac",
"od 1680 eur/mesiac", "8,50 eur/hod") and common international ones
("$70k - $90k", "70000-90000 USD/year"). Original currency is kept —
no FX conversion.
"""

import re

_CURRENCIES = [
    (r"\beur\b|€", "EUR"),
    (r"\busd\b|\$", "USD"),
    (r"\bgbp\b|£", "GBP"),
    (r"\bczk\b|kč", "CZK"),
    (r"\bchf\b", "CHF"),
    (r"\bpln\b|zł", "PLN"),
]

_PERIODS = [
    (r"hod|/\s*h\b|hour|hr\b|hodin", "hour"),
    (r"deň|den\b|/\s*d\b|day|denne", "day"),
    (r"týž|tyzd|week|/\s*wk", "week"),
    (r"mesiac|/\s*mes|month|/\s*mo\b|monat", "month"),
    (r"rok|year|/\s*yr|annum|annual|jahr", "year"),
]

_HOURS_PER = {"hour": 1, "day": 8, "week": 40, "month": 160, "year": 1920}

_NUMBER = re.compile(r"(\d[\d\s.,]*\d|\d)\s*(k\b)?", re.IGNORECASE)


def _to_number(raw, k_suffix):
    text = raw.replace("\xa0", " ")
    # "1 000" and "1.000" are thousands separators; "8,50" is a decimal comma
    text = text.replace(" ", "")
    if re.match(r"^\d{1,3}(\.\d{3})+$", text):
        text = text.replace(".", "")
    text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    if k_suffix:
        value *= 1000
    return value


def parse_salary(text):
    """→ (min, max, currency, period) — any element may be None."""
    if not text or not isinstance(text, str):
        return None, None, None, None
    lower = text.lower()

    currency = next((code for pat, code in _CURRENCIES if re.search(pat, lower)), None)
    period = next((name for pat, name in _PERIODS if re.search(pat, lower)), None)
    if currency is None and period is None:
        # No salary context at all — the numbers are probably not pay.
        return None, None, None, None

    numbers = []
    for m in _NUMBER.finditer(lower):
        value = _to_number(m.group(1), m.group(2))
        if value is not None and value >= 1:
            numbers.append(value)
    if not numbers:
        return None, None, currency, period

    if len(numbers) == 1:
        low = high = numbers[0]
    else:
        low, high = min(numbers[:2]), max(numbers[:2])

    # Guess the period when it's missing but magnitude is unambiguous
    if period is None and currency is not None:
        if high < 200:
            period = "hour"
        elif high < 20000:
            period = "month"
        else:
            period = "year"

    return low, high, currency, period


def hourly(salary_min, salary_max, period):
    """→ (hourly_min, hourly_max) or (None, None)."""
    divisor = _HOURS_PER.get(period)
    if not divisor:
        return None, None
    low = round(salary_min / divisor, 1) if salary_min else None
    high = round(salary_max / divisor, 1) if salary_max else None
    return low, high


_SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "CZK": "Kč", "CHF": "CHF", "PLN": "zł"}


def hourly_display(salary_min, salary_max, currency, period):
    """Human string like '≈ 5.6–6.3 €/h', or None."""
    low, high = hourly(salary_min, salary_max, period)
    if low is None and high is None:
        return None
    symbol = _SYMBOL.get(currency, currency or "")
    if low is not None and high is not None and low != high:
        return f"≈ {low:g}–{high:g} {symbol}/h"
    value = low if low is not None else high
    return f"≈ {value:g} {symbol}/h"
