"""Salary parsing, and the one number two postings can be compared by.

Understands the Slovak board formats ("900 - 1 000 eur/mesiac",
"od 1680 eur/mesiac", "8,50 eur/hod") and common international ones
("$70k - $90k", "70000-90000 USD/year").

**What a board wrote is stored exactly as it wrote it** — the amount, the
currency and the period all go into `jobs` unconverted, and `range_display`
reads them back in the board's own money. The comparison is *derived on the
way out*: `hourly_eur()`, and its SQL mirror `HOURLY_EUR_SQL`, put every
posting on one period **and** one currency, because that is the only form in
which a Czech monthly wage, a Slovak one and an annual American salary are the
same kind of number.
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

HOURS_PER = {"hour": 1, "day": 8, "week": 40, "month": 160, "year": 1920}

# How many units of a currency go where one euro would. Two questions are asked
# of this table and it is deliberately **one** table, because they are one fact:
# how big a number in this currency is. The magnitude guess below reads it to
# decide what unit an unlabelled number was quoted in; `hourly_eur()` reads it
# to put two postings on one scale. It arrived as the first of those and was
# only ever written for the currencies that needed it — which is to say the app
# has been carrying an approximate FX table under another name since jobs.cz
# brought CZK into the pool, and a second copy of it would have been a second
# opinion about the same number.
#
# ECB reference rates of 2026-08-28, cross-checked against a second provider
# (they agreed to within 0.3 %), and rounded to what the answers can tell apart.
# Refreshing them rewrites nothing: no stored column and no score reads this, so
# a rate change moves a ranking and the "≈" on a card and touches nothing else.
RATES_AS_OF = "28 Aug 2026"
COMPARISON_CURRENCY = "EUR"
EUR_RATES = {
    "EUR": 1.0,
    "USD": 1.16,
    "GBP": 0.86,
    "CZK": 24.15,
    "CHF": 0.94,
    "PLN": 4.34,
}

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

    # Guess the period when it's missing but magnitude is unambiguous.
    # The thresholds are amounts, so they only mean anything *per currency*:
    # 85 000 is an ordinary Czech monthly wage and an extraordinary euro one.
    # Reading them in euros is what made every bare "70 000 – 85 000 Kč" on
    # jobs.cz a yearly salary, and so an hourly rate twelve times too low in
    # the pay filter and the "Best pay" sort.
    #
    # This decides which *unit* a unit-less number was quoted in, and writes
    # only `salary_period`; the amount and the currency we store stay exactly
    # as the board wrote them. The `1` can only be reached by a currency
    # `_CURRENCIES` cannot produce — the tests hold that shut — and par is the
    # only neutral thing to say about a currency we know nothing about.
    if period is None and currency is not None:
        scale = EUR_RATES.get(currency, 1)
        if high < 200 * scale:
            period = "hour"
        elif high < 20000 * scale:
            period = "month"
        else:
            period = "year"

    return low, high, currency, period


def hourly_eur(salary_min, salary_max, period, currency):
    """→ (low, high) in euros an hour, or (None, None).

    One period and one currency: two postings are comparable on this number and
    on nothing else the boards give us. Either half unknown makes the whole
    answer unknown, and unknown is None rather than zero — the pay filter and
    the "Best pay" sort must read "we cannot compare this" the way they read
    "no pay quoted", never as "pays nothing". A currency with no rate is
    precisely that case: at par it would print a euro figure for a wage nobody
    quoted in euros, which is worse than declining to rank it.
    """
    divisor = HOURS_PER.get(period)
    rate = EUR_RATES.get(currency)
    if not divisor or not rate:
        return None, None
    low = round(salary_min / divisor / rate, 1) if salary_min else None
    high = round(salary_max / divisor / rate, 1) if salary_max else None
    return low, high


# `hourly_eur()` written as SQL, generated from the same two tables so the
# number a filter selects on and the number the card prints can never disagree.
# Used by the pay filter and the "Best pay" sort; NULL for a job that quotes no
# salary, no period or a currency we hold no rate for — which is what keeps
# those jobs out of a "≥ €15/h" filter instead of at the bottom of it.
_HOURLY_CASES = " ".join(
    f"WHEN '{period}' THEN {hours}.0" for period, hours in HOURS_PER.items()
)
_RATE_CASES = " ".join(
    f"WHEN '{code}' THEN {rate}" for code, rate in EUR_RATES.items()
)
HOURLY_EUR_SQL = (
    f"(COALESCE(j.salary_max, j.salary_min)"
    f" / CASE j.salary_period {_HOURLY_CASES} ELSE NULL END"
    f" / CASE j.salary_currency {_RATE_CASES} ELSE NULL END)"
)

_SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£", "CZK": "Kč", "CHF": "CHF", "PLN": "zł"}

COMPARISON_SYMBOL = _SYMBOL[COMPARISON_CURRENCY]

_PERIOD_SHORT = {"hour": "h", "day": "d", "week": "wk", "month": "mo", "year": "yr"}


def hourly_display(salary_min, salary_max, currency, period):
    """Human string like '≈ 5.6–6.3 €/h', or None.

    Always in euros, whatever the board quoted, because this is the comparable
    figure — the same one the filter and the sort read. It rides beside
    `range_display`, which keeps the board's own money, so the conversion is
    visible on the card rather than a euro sign appearing out of nowhere;
    `conversion_note` is the sentence that says what it was converted at.
    """
    low, high = hourly_eur(salary_min, salary_max, period, currency)
    if low is None and high is None:
        return None
    if low is not None and high is not None and low != high:
        return f"≈ {low:g}–{high:g} {COMPARISON_SYMBOL}/h"
    value = low if low is not None else high
    return f"≈ {value:g} {COMPARISON_SYMBOL}/h"


def conversion_note(currency):
    """Why the figure beside a non-euro range is in euros, or None.

    A rate quoted without its date is a claim to be current, which this one is
    not — it is a constant in a source file — so the date ships with it.
    """
    rate = EUR_RATES.get(currency)
    if not rate or currency == COMPARISON_CURRENCY:
        return None
    symbol = _SYMBOL.get(currency, currency)
    return (f"Converted at ≈ {rate:g} {symbol} per euro "
            f"(ECB reference rate, {RATES_AS_OF}).")


def range_display(salary_min, salary_max, currency, period):
    """The pay as a board would have written it: '1 500–2 000 €/mo', or None.

    Built from the structured columns rather than echoing the board's own
    string, so a Slovak "od 1680 eur/mesiac" and a "$70k - $90k" read the same
    way in the same list — but in the board's own currency and period, because
    this is the posting's claim about itself and not our comparison of it.
    Thousands are spaced, not comma'd — a comma is a decimal point on half the
    boards we scrape.
    """
    if salary_min is None and salary_max is None:
        return None
    symbol = _SYMBOL.get(currency, currency or "")
    unit = f"/{_PERIOD_SHORT[period]}" if period in _PERIOD_SHORT else ""
    low, high = salary_min, salary_max
    if low is not None and high is not None and low != high:
        return f"{_amount(low)}–{_amount(high)} {symbol}{unit}".strip()
    value = low if low is not None else high
    return f"{_amount(value)} {symbol}{unit}".strip()


def _amount(value):
    """A number as money: no decimals unless it is an hourly rate like 8.5."""
    if value >= 100:
        return f"{int(round(value)):,}".replace(",", " ")
    return f"{value:g}"
