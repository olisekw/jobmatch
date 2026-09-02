"""Where a job is, as a country rather than as a line of board text.

Boards write location free-hand: "bratislava", "praha (hlavní město praha)",
"anywhere", "usa only", "emea". None of that filters, and none of it answers
the question a person actually puts to a list of jobs — *is this somewhere I
can work?* This turns that text, plus the board it came from, into one short
code that is stored on the row (`jobs.country`) at scan time, so the Jobs page
can filter on a column instead of on a LIKE over prose.

Codes are ISO 3166-1 alpha-2 with a few deliberate additions, because the
remote boards frequently name a region and no country exists to hold it:
`ANY` (worldwide), `EU`, `NA`, `LATAM`, `APAC`. `label()` is the only thing
that turns a code into words, so the chip on a card and the filter dropdown
cannot word the same place two ways.

Three rules keep the guessing honest:

- **Order is specific → general.** A country name beats a city, a city beats a
  region, and "anywhere" is only reached when nothing more precise matched.
- **The board is the fallback, not the first answer.** profesia.sk and
  kariera.sk only ever list Slovak jobs, so an unrecognised town on one of them
  is Slovakia — but "praha" on profesia is still Czechia.
- **A posting hiring in five places names five places.** "LATAM, Europe, USA,
  Canada, APAC" is one string and five answers, so `codes()` returns all of
  them (stored packed in `jobs.countries`) and `primary()` picks the one the
  card prints (`jobs.country`). Reachability is a question about the set —
  first-match-wins made that posting `US`, and unreachable for a European.

Derivation is display-shaped but stored, so a fix here reaches old rows only
through `jobmatch.backfill` (which fills `country IS NULL`) — the same deal
`posted_at` and the salary columns have.
"""

import re
import unicodedata

# ── Labels ───────────────────────────────────────────────────

LABELS = {
    "ANY": "Worldwide",
    "EU": "Europe",
    "NA": "North America",
    "LATAM": "Latin America",
    "APAC": "Asia-Pacific",
    "SK": "Slovakia",
    "CZ": "Czechia",
    "AT": "Austria",
    "HU": "Hungary",
    "PL": "Poland",
    "DE": "Germany",
    "UK": "United Kingdom",
    "IE": "Ireland",
    "NL": "Netherlands",
    "BE": "Belgium",
    "FR": "France",
    "ES": "Spain",
    "PT": "Portugal",
    "IT": "Italy",
    "CH": "Switzerland",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "FI": "Finland",
    "EE": "Estonia",
    "LV": "Latvia",
    "LT": "Lithuania",
    "RO": "Romania",
    "BG": "Bulgaria",
    "HR": "Croatia",
    "SI": "Slovenia",
    "RS": "Serbia",
    "UA": "Ukraine",
    "GR": "Greece",
    "TR": "Turkey",
    "US": "United States",
    "CA": "Canada",
    "MX": "Mexico",
    "BR": "Brazil",
    "AR": "Argentina",
    "AU": "Australia",
    "NZ": "New Zealand",
    "IN": "India",
    "SG": "Singapore",
    "JP": "Japan",
    "PH": "Philippines",
    "ZA": "South Africa",
    "AE": "United Arab Emirates",
    "IL": "Israel",
}

# Codes that are not a country. The UI groups them first in the filter, because
# "Worldwide" is the most useful thing in the list and alphabetical would bury
# it between Ukraine and the United States.
REGIONS = ("ANY", "EU", "NA", "LATAM", "APAC")

# Which countries a region contains — the other half of `REGIONS`, and the only
# thing that lets "I can work in the EU" answer a question about a job placed in
# Germany. `ANY` is deliberately absent: a job hiring worldwide is reachable by
# everybody, which is a rule in `reachable_codes()` rather than a membership
# list, and nothing is "inside" worldwide.
#
# Two judgement calls, both made to match how the boards use the words rather
# than how a lawyer would:
#
# - `EU` is labelled "Europe" and matched from "europe|eu|emea|cee", so it holds
#   geographic Europe — the UK, Switzerland, Serbia and Ukraine included. It is
#   a ranking heuristic, not a work-permit checker.
# - `NA` is the US and Canada, because that is what a remote board means by
#   "North America" (a hiring pool, not a continent). Mexico sits in `LATAM`,
#   which is where the boards that list it put it.
#
# ZA, AE and IL are in no region on purpose: they are only ever reachable by
# somebody who named them.
REGION_MEMBERS = {
    "EU": {"SK", "CZ", "AT", "HU", "PL", "DE", "UK", "IE", "NL", "BE", "FR", "ES",
           "PT", "IT", "CH", "SE", "NO", "DK", "FI", "EE", "LV", "LT", "RO", "BG",
           "HR", "SI", "RS", "UA", "GR", "TR"},
    "NA": {"US", "CA"},
    "LATAM": {"MX", "BR", "AR"},
    "APAC": {"AU", "NZ", "IN", "SG", "JP", "PH"},
}


def default_regions(home):
    """Where somebody living in `home` can presumably work, absent an answer.

    Their own country plus whatever region contains it — so a user in
    Bratislava starts at Slovakia + Europe and one in Toronto at Canada +
    North America, rather than at Europe for everybody. `None` in gives an
    empty set out, which is what keeps the location component *unknown* for a
    user who has told us nothing (an empty bar reads as a zero; a hatched one
    does not).
    """
    if not home or home not in LABELS:
        return set()
    return {home} | {r for r, members in REGION_MEMBERS.items() if home in members}


def reachable_codes(allowed):
    """Expand "where I can work" into every `jobs.country` value that satisfies it.

    One derivation, read by the scorer, the Jobs filter and (through the score)
    the digest, so the three cannot disagree about what is reachable. Expansion
    runs both ways, because a preference and a posting name places at different
    zoom levels:

    - a region in the preference covers the countries inside it (`EU` → `DE`);
    - a country in the preference is covered by a posting addressed to its whole
      region (`SK` → a job placed `EU`);
    - `ANY` on the *job* is reachable by everyone — a board hiring worldwide
      hires here too — while `ANY` in the *preference* is the rare user who
      really can work anywhere, and says so.

    An empty preference expands to an empty set, which callers read as "unknown"
    rather than as "nowhere".
    """
    allowed = {code for code in (allowed or ()) if code in LABELS}
    if not allowed:
        return set()
    if "ANY" in allowed:
        return set(LABELS)
    codes = {"ANY"} | allowed
    for code in allowed:
        codes |= REGION_MEMBERS.get(code, set())
    codes |= {r for r, members in REGION_MEMBERS.items() if allowed & members}
    return codes


def covering_region(codes):
    """The one region every code in `codes` sits inside, or None.

    The mirror image of `reachable_codes`: that one asks "which postings can
    this person take?", this one asks "what is the smallest thing I can ask a
    *board* for and still get everything these people can take?". It is what
    lets the shared crawl narrow its request instead of scraping a planet and
    throwing most of it away.

    None is the answer whenever narrowing would be a lie — an empty set (nobody
    we can place), `ANY` (somebody who really can work anywhere), a country in
    no region at all (ZA, AE, IL), or two regions at once. The caller reads
    None as "ask for everything", which is what every board did before this
    existed, so an instance that cannot be narrowed loses nothing.
    """
    codes = {code for code in (codes or ()) if code in LABELS}
    if not codes or "ANY" in codes:
        return None
    for region, members in REGION_MEMBERS.items():
        if all(code == region or code in members for code in codes):
            return region
    return None


def label(code):
    """The readable name of a stored code, or "" for a row we could not place."""
    if not code:
        return ""
    return LABELS.get(code, code)


# ── The lookup tables ────────────────────────────────────────
#
# Written as plain alternations rather than one big dict comprehension so the
# Slovak and Czech spellings sit next to the English ones and a missing town is
# obvious. Matched against de-accented text, so "kosice" is enough for "Košice".

_COUNTRIES = [
    ("SK", r"slovak|slovensko|slovenska republika"),
    ("CZ", r"czech|czechia|cesko|ceska republika"),
    ("AT", r"austria|osterreich|rakusko"),
    ("HU", r"hungary|magyarorszag|madarsko"),
    ("PL", r"poland|polska|polsko"),
    ("DE", r"germany|deutschland|nemecko"),
    ("UK", r"united kingdom|england|scotland|wales|britain|\buk\b|\bgb\b"),
    ("IE", r"ireland|\birl\b"),
    ("NL", r"netherlands|holland|nederland"),
    ("BE", r"belgium|belgie|belgique"),
    ("FR", r"france|francuzsko"),
    ("ES", r"spain|espana|spanielsko"),
    ("PT", r"portugal"),
    ("IT", r"italy|italia|taliansko"),
    ("CH", r"switzerland|schweiz|svajciarsko"),
    ("SE", r"sweden|sverige"),
    ("NO", r"norway|norge"),
    ("DK", r"denmark|danmark"),
    ("FI", r"finland|suomi"),
    ("EE", r"estonia|eesti"),
    ("LV", r"latvia|latvija"),
    ("LT", r"lithuania|lietuva"),
    ("RO", r"romania"),
    ("BG", r"bulgaria"),
    ("HR", r"croatia|hrvatska"),
    ("SI", r"slovenia|slovenija"),
    ("RS", r"serbia|srbija"),
    ("UA", r"ukraine|ukrajina"),
    ("GR", r"greece|hellas"),
    ("TR", r"turkey|turkiye"),
    # Deliberately *not* a bare "us" or "america": "contact us for details" is a
    # location some boards print, and "Latin America" belongs to LATAM below.
    ("US", r"united states|\busa\b|u\.s\.|(?:^|,\s*|\()us(?:\)|,|$)"),
    ("CA", r"canada"),
    ("MX", r"mexico"),
    ("BR", r"brazil|brasil"),
    ("AR", r"argentina"),
    ("AU", r"australia"),
    ("NZ", r"new zealand"),
    ("IN", r"\bindia\b"),
    ("SG", r"singapore"),
    ("JP", r"japan"),
    ("PH", r"philippines"),
    ("ZA", r"south africa"),
    ("AE", r"united arab emirates|\buae\b|dubai|abu dhabi"),
    ("IL", r"israel"),
]

# Towns, for the two Slovak boards (which write a town and no country) and the
# handful of neighbouring cities that turn up on them.
_CITIES = [
    ("SK", r"bratislav|kosic|zilin|nitr|presov|trnav|trencin|banska bystric|\bmartin\b|"
           r"poprad|zvolen|michalovc|prievidz|humenn|spisska nova ves|komarn|levic|"
           r"piestan|ruzomberok|liptovsky mikulas|dubnic|senec|pezinok|malack|"
           r"topolcan|nove zamky|bardejov|trebisov|roznav|dolny kubin|cadc|puchov"),
    ("CZ", r"prah|prague|brno|ostrav|plzen|olomouc|liberec|hradec kralove|pardubic|"
           r"ceske budejovic"),
    ("AT", r"\bwien\b|vienna|\bgraz\b|\blinz\b|salzburg"),
    ("HU", r"budapest"),
    ("PL", r"warsaw|warszawa|krakow|wroclaw|poznan|gdansk"),
    ("DE", r"berlin|munich|munchen|hamburg|frankfurt|cologne|koln|stuttgart|dusseldorf"),
    ("UK", r"london|manchester|edinburgh|glasgow|bristol|birmingham"),
]

_REGIONS = [
    ("EU", r"europe|\beu\b|emea|\bcee\b|european union|eurozone"),
    # "northern america" is Remotive's spelling of it, and matched nothing.
    ("NA", r"north(?:ern)? america|\bnorth-america\b"),
    ("LATAM", r"latin america|latam|south america"),
    ("APAC", r"apac|asia[- ]pacific|\basia\b|oceania"),
]

# Nothing narrower than "somewhere with an internet connection".
_ANYWHERE = r"anywhere|worldwide|world wide|\bglobal|fully remote|remote only|" \
            r"^remote$|work from home|home office|\bwfh\b|distributed"

# What a board is *about*, used only when its text placed nothing. The Slovak
# boards and the Czech one never list a foreign job; the remote boards list
# every country there is, so they get no default and stay unplaced rather
# than guessing.
SOURCE_DEFAULT = {"profesia": "SK", "kariera": "SK", "jobscz": "CZ"}

_TABLES = [_COUNTRIES, _CITIES, _REGIONS]
_COMPILED = [[(code, re.compile(pattern)) for code, pattern in table] for table in _TABLES]
_ANYWHERE_RE = re.compile(_ANYWHERE)


def fold(text):
    """Lowercase, de-accented, single-spaced — the shape the tables are in.

    Boards mix "Košice", "KOSICE" and "Košice - okres Košice I" freely, and a
    NBSP is as common as a space in scraped markup.
    """
    if not text or not isinstance(text, str):
        return ""
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def codes(source, location):
    """→ every place a row names, most specific first; `()` when nothing places it.

    A remote board's location field is a *list* as often as it is a place:
    Remotive writes "LATAM, Europe, USA, Canada, APAC" and "Americas, Europe,
    Israel", and one column cannot hold five answers. First-match-wins stored
    those two as `US` and `IL` — both then unreachable for a European, though
    both say Europe out loud, which costs exactly the jobs a European remote
    search exists to find. So the full answer is a set (`jobs.countries`) and
    the single code (`jobs.country`) is only the one a card prints.

    Order is the tables' order, specific → general, so `codes[0]` is still the
    most precise thing the text said and `primary()` can lean on that.

    `source` is the adapter name (`jobs.source`); `location` the board's text.
    """
    text = fold(location)
    found = []
    if text:
        for table in _COMPILED:
            for code, pattern in table:
                if code not in found and pattern.search(text):
                    found.append(code)
        # "Anywhere" is what a row means when it named nothing narrower — a
        # posting that says "Anywhere in Europe" is a European posting, not a
        # worldwide one, and that is the whole of the specific → general rule.
        if not found and _ANYWHERE_RE.search(text):
            found.append("ANY")
    if not found and SOURCE_DEFAULT.get(source):
        found.append(SOURCE_DEFAULT[source])
    return tuple(found)


def primary(found):
    """The one code a row prints, out of everything it names.

    Not simply the first one. A posting naming several regions is reachable
    from all of them, so "United States" for "LATAM, Europe, USA, Canada,
    APAC" is the narrowest true thing it could say and reads as the *only*
    one. Two cases, decided by `covering_region`:

    - the places named all sit inside one region ("Berlin, Germany — Europe"),
      so the specific one is honest and the chip says **Germany**;
    - they do not ("Americas, Europe, Israel"), so the widest of them wins and
      the chip says **Europe** — the thing the posting said out loud that the
      most readers of the list can act on.
    """
    found = [code for code in (found or ()) if code in LABELS]
    if not found:
        return None
    if len(found) == 1 or covering_region(found):
        return found[0]
    return next((code for code in found if code in REGIONS), found[0])


def country(source, location):
    """→ a code from `LABELS`, or None when nothing in the row places the job.

    The printed half of `codes()`; `jobs.countries` holds the rest.
    """
    return primary(codes(source, location))


# ── The stored set ───────────────────────────────────────────
#
# `jobs.countries` is the packed set: `|EU|US|CA|`. Delimited rather than a
# second table because every reader asks the same question of it — *does this
# row name a place I can work?* — which is a token match and never a join, and
# because a set-valued column that needs no migration to read keeps "adding a
# board = one file" true. The delimiters are on both ends so `|US|` cannot
# match inside another code.

DELIMITER = "|"

# The same column for SQL, tolerating a row written before it existed: an
# upgraded database has the column (`init_schema` adds it) and NULLs in it
# until `jobmatch.backfill` runs, and a filter that quietly hid every one of
# those rows in the meantime would be worse than the bug this fixes.
COUNTRIES_SQL = f"COALESCE(j.countries, '{DELIMITER}' || j.country || '{DELIMITER}')"


def pack(found):
    """`('EU', 'US')` → `'|EU|US|'`, the shape `jobs.countries` is stored in."""
    found = [code for code in (found or ()) if code in LABELS]
    if not found:
        return None
    return DELIMITER + DELIMITER.join(found) + DELIMITER


def unpack(packed):
    """`'|EU|US|'` → `{'EU', 'US'}`. Junk in the column is dropped, not obeyed."""
    return {code for code in (packed or "").split(DELIMITER) if code in LABELS}


def token(code):
    """The LIKE pattern matching `code` inside a packed column."""
    return f"%{DELIMITER}{code}{DELIMITER}%"


def stored_codes(packed, printed):
    """What a stored row names — the Python mirror of `COUNTRIES_SQL`.

    Falls back to the single printed code for a row from before `countries`
    existed, so scoring is right the moment the column is added rather than
    the moment somebody remembers to backfill.
    """
    return unpack(packed) or ({printed} if printed in LABELS else set())


def options(codes):
    """`[{value, label}]` for a filter dropdown, regions first then A→Z.

    Takes the codes a database actually holds rather than all of `LABELS`: a
    dropdown offering forty countries that match nothing is worse than no
    dropdown, and which boards are enabled decides what is really in there.
    """
    known = [code for code in codes if code]
    regions = [code for code in REGIONS if code in known]
    countries = sorted(
        (code for code in set(known) if code not in REGIONS), key=lambda c: label(c)
    )
    return [{"value": code, "label": label(code)} for code in regions + countries]


def work_options(pool_codes, chosen=()):
    """`[{value, label}]` for the "where I can work" picker in Settings.

    Every region, plus the countries the pool actually holds, plus anything the
    user has already picked. The regions are unconditional because they are what
    makes the answer short — "Europe" covers thirty countries and is the answer
    most people want — while offering all forty-eight countries would bury them.
    Restricting the rest to the pool costs nothing that matters: a code no job
    was ever placed in changes no score, and which boards are enabled decides
    what is really in there. Anything already chosen stays on the list, so a
    preference does not silently vanish when the pool moves.
    """
    known = {code for code in pool_codes if code in LABELS}
    known |= {code for code in chosen if code in LABELS}
    known |= set(REGIONS)
    regions = [code for code in REGIONS if code in known]
    countries = sorted((c for c in known if c not in REGIONS), key=lambda c: label(c))
    return [{"value": code, "label": label(code)} for code in regions + countries]
