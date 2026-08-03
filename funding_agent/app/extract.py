"""Turns whatever JSON the Funding Explorer serves into `Round` objects.

The Explorer is a single-page app, so its data arrives as JSON — either from
XHR/fetch calls the page makes, or embedded in the HTML (`__NEXT_DATA__`,
`<script type="application/json">`, RSC flight chunks). We don't hard-code an
API shape: instead we walk the JSON, find the list that most looks like a list
of funding rounds, and map its fields by name. That survives the field renames
and endpoint moves that a scraper pinned to fixed selectors would not.

If the site ever changes beyond what the heuristics recognise, `agent discover`
dumps the captured payloads so the mapping can be pinned by hand.
"""

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Iterator, Optional

from .models import NOT_DISCLOSED, Round, parse_amount

# Field-name candidates, most specific first. Keys are matched after
# normalisation (lowercased, non-alphanumerics stripped), so "company_name",
# "companyName" and "Company Name" all collapse to "companyname".
COMPANY_KEYS = (
    "companyname", "startupname", "organizationname", "orgname",
    "company", "startup", "organization", "org", "name", "title",
)
AMOUNT_KEYS = (
    "amounteur", "amounteuro", "euramount", "amountineur", "raisedeur",
    "amountraised", "roundamount", "fundingamount", "dealsize", "roundsize",
    "amount", "raised", "funding", "size", "value", "total",
)
CURRENCY_KEYS = ("currency", "currencycode", "amountcurrency")
DESCRIPTION_KEYS = (
    "shortdescription", "companydescription", "description", "tagline",
    "summary", "excerpt", "about", "blurb", "onelinerdescription", "oneliner",
    "whattheydo", "pitch",
)
LEAD_KEYS = (
    "leadinvestor", "leadinvestors", "leadinvestorname", "lead", "leadname",
    "leadinvestornames", "roundlead",
)
INVESTOR_KEYS = (
    "investors", "investorname", "investornames", "participants",
    "participatinginvestors", "coinvestors", "backers", "investor",
)
DATE_KEYS = (
    "announcedon", "announcedat", "announcementdate", "dateannounced",
    "rounddate", "fundingdate", "publishedat", "publishdate", "date",
    "createdat", "updatedat",
)
STAGE_KEYS = ("stage", "roundtype", "roundstage", "round", "series", "type", "fundingstage")
SECTOR_KEYS = ("sector", "industry", "industries", "category", "categories", "vertical", "verticals", "tags")
URL_KEYS = ("sourceurl", "articleurl", "permalink", "url", "link", "website", "slug")

# Keys whose presence means "this list is not funding rounds" (nav menus,
# analytics configs and image sets otherwise score surprisingly well).
NEGATIVE_KEYS = ("menuitem", "navlabel", "srcset", "breakpoint", "translationkey")

_LEAD_TRUTHY = ("islead", "lead", "isleadinvestor", "leadflag")


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).lower())


def _index(item: dict) -> dict[str, Any]:
    """Flattens one record into normalised-key -> value.

    Nested objects contribute both a prefixed key and (when not already taken)
    a bare one, so `{"company": {"name": ..., "description": ...}}` exposes
    `companyname` and `description` alike.
    """
    flat: dict[str, Any] = {}
    nested: dict[str, Any] = {}
    for key, value in item.items():
        nkey = normalize_key(key)
        if nkey and nkey not in flat:
            flat[nkey] = value
        if isinstance(value, dict):
            for inner_key, inner_value in value.items():
                nested_key = nkey + normalize_key(inner_key)
                if nested_key not in nested:
                    nested[nested_key] = inner_value
                bare = normalize_key(inner_key)
                if bare and bare not in nested:
                    nested[bare] = inner_value
    for key, value in nested.items():
        flat.setdefault(key, value)
    return flat


def _pick(flat: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in flat:
            value = flat[key]
            if value not in (None, "", [], {}):
                return value
    return None


def _as_text(value: Any) -> str:
    """Coerces a scalar / dict / list field into a display string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "title", "label", "value", "text"):
            if key in value:
                return _as_text(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_as_text(v) for v in value]
        return ", ".join(p for p in parts if p)
    return ""


def _names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        text = _as_text(value)
        return [t.strip() for t in text.split(",") if t.strip()] if text else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for entry in value:
            out.extend(_names(entry))
        return out
    return []


def _lead_from_investors(value: Any) -> tuple[str, list[str]]:
    """Splits an investor collection into (lead, others).

    Handles both `[{"name": "X", "is_lead": true}, ...]` and plain string
    lists where the lead is flagged inline, e.g. "Foo Ventures (lead)".
    """
    lead = ""
    others: list[str] = []
    entries = value if isinstance(value, (list, tuple)) else [value]
    for entry in entries:
        if isinstance(entry, dict):
            flat = _index(entry)
            name = _as_text(_pick(flat, ("name", "investorname", "title", "label")))
            if not name:
                continue
            is_lead = False
            for flag in _LEAD_TRUTHY:
                raw = flat.get(flag)
                if raw is True or (isinstance(raw, str) and raw.strip().lower() in ("true", "yes", "lead", "1")):
                    is_lead = True
                    break
            role = str(flat.get("role") or flat.get("type") or "").lower()
            if "lead" in role:
                is_lead = True
            if is_lead and not lead:
                lead = name
            else:
                others.append(name)
        else:
            for name in _names(entry):
                if re.search(r"\(\s*lead\s*\)|\blead\b", name, re.IGNORECASE) and not lead:
                    lead = re.sub(r"\(?\s*\blead\b\s*(investor)?\s*\)?", "", name, flags=re.IGNORECASE).strip(" -–,")
                else:
                    others.append(name)
    return lead, [o for o in others if o]


def _parse_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return match.group(0)
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:30].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    try:  # RFC 2822 (RSS pubDate)
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def round_from_item(item: dict, base_url: str = "") -> Optional[Round]:
    """Maps one JSON record to a Round, or None if it isn't one."""
    if not isinstance(item, dict):
        return None
    flat = _index(item)
    if any(key in flat for key in NEGATIVE_KEYS):
        return None

    company = _as_text(_pick(flat, COMPANY_KEYS))
    if not company or len(company) > 120:
        return None

    currency = _as_text(_pick(flat, CURRENCY_KEYS)) or None
    amount = parse_amount(_pick(flat, AMOUNT_KEYS), currency)

    lead = _as_text(_pick(flat, LEAD_KEYS))
    investors_raw = _pick(flat, INVESTOR_KEYS)
    others: list[str] = []
    if investors_raw is not None:
        found_lead, others = _lead_from_investors(investors_raw)
        if not lead:
            lead = found_lead
    if not lead and others:
        # Explorer rows often list the lead first when they don't tag it.
        lead, others = others[0], others[1:]

    url = _as_text(_pick(flat, URL_KEYS))
    if url and not url.startswith("http") and base_url:
        url = base_url.rstrip("/") + "/" + url.lstrip("/")

    return Round(
        company=company,
        amount_eur=amount,
        description=_as_text(_pick(flat, DESCRIPTION_KEYS)),
        lead_investor=lead or NOT_DISCLOSED,
        other_investors=others[:6],
        stage=_as_text(_pick(flat, STAGE_KEYS)),
        sector=_as_text(_pick(flat, SECTOR_KEYS)),
        announced_on=_parse_date(_pick(flat, DATE_KEYS)),
        source_url=url,
    )


def score_list(items: list) -> float:
    """How much a list looks like a list of funding rounds.

    Rewards records that pair a company name with money and/or investors —
    the combination that distinguishes rounds from every other array an SPA
    ships (nav items, authors, tag clouds).
    """
    records = [i for i in items if isinstance(i, dict)]
    if len(records) < 2:
        return 0.0
    sample = records[:40]
    named = money = investors = dated = described = 0
    for item in sample:
        flat = _index(item)
        if any(key in flat for key in NEGATIVE_KEYS):
            return 0.0
        if _as_text(_pick(flat, COMPANY_KEYS)):
            named += 1
        if parse_amount(_pick(flat, AMOUNT_KEYS)) is not None:
            money += 1
        if _pick(flat, LEAD_KEYS) or _pick(flat, INVESTOR_KEYS):
            investors += 1
        if _pick(flat, DATE_KEYS):
            dated += 1
        if _as_text(_pick(flat, DESCRIPTION_KEYS)):
            described += 1

    total = len(sample)
    name_ratio = named / total
    if name_ratio < 0.5:
        return 0.0
    money_ratio = money / total
    investor_ratio = investors / total
    if money_ratio < 0.3 and investor_ratio < 0.3:
        return 0.0

    quality = (
        name_ratio
        + 1.5 * money_ratio
        + 1.5 * investor_ratio
        + 0.5 * (dated / total)
        + 0.5 * (described / total)
    )
    # Mild preference for longer lists: a 50-row table beats a 3-row teaser.
    return quality * (1 + min(len(records), 200) / 200)


def iter_lists(node: Any, depth: int = 0) -> Iterator[list]:
    if depth > 12:
        return
    if isinstance(node, list):
        if any(isinstance(i, dict) for i in node):
            yield node
        for item in node[:200]:
            yield from iter_lists(item, depth + 1)
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_lists(value, depth + 1)


def best_rounds(payload: Any, base_url: str = "") -> list[Round]:
    """Finds the most round-like list in a payload and maps it."""
    best: list[Round] = []
    best_score = 0.0
    for candidate in iter_lists(payload):
        score = score_list(candidate)
        if score <= best_score:
            continue
        rounds = [r for r in (round_from_item(i, base_url) for i in candidate if isinstance(i, dict)) if r and r.has_content]
        if rounds:
            best, best_score = rounds, score
    return best


def scan_json_blobs(text: str, limit: int = 400) -> Iterator[Any]:
    """Yields JSON values embedded in an HTML/JS document.

    Next.js RSC payloads arrive as escaped strings inside `self.__next_f.push`
    calls rather than as clean script tags, so a plain tag-parse misses them.
    Scanning for decodable JSON at every `[{` / `{"` boundary catches both.
    """
    decoder = json.JSONDecoder()
    found = 0
    for match in re.finditer(r'[\[{](?=\s*[\[{"])', text):
        if found >= limit:
            return
        start = match.start()
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, (dict, list)) and value:
            found += 1
            yield value


def rounds_from_html(html: str, base_url: str = "") -> list[Round]:
    """Extracts rounds from embedded JSON in a rendered page."""
    best: list[Round] = []
    best_score = 0.0

    # Unescape RSC/JSON-in-string payloads so nested data becomes scannable.
    candidates = [html]
    if "__next_f" in html or "\\u0022" in html or '\\"' in html:
        try:
            candidates.append(html.encode().decode("unicode_escape", errors="ignore"))
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

    for text in candidates:
        for blob in scan_json_blobs(text):
            for candidate in iter_lists(blob):
                score = score_list(candidate)
                if score <= best_score:
                    continue
                rounds = [
                    r
                    for r in (round_from_item(i, base_url) for i in candidate if isinstance(i, dict))
                    if r and r.has_content
                ]
                if rounds:
                    best, best_score = rounds, score
    return best


def filter_rounds(
    rounds: list[Round],
    lookback_days: int = 0,
    min_amount_eur: float = 0.0,
    today: Optional[date] = None,
) -> list[Round]:
    """Applies recency and size filters, newest and biggest first.

    Rounds with an unparseable date are kept: a missing date is a parsing gap,
    not evidence the round is old, and dropping them would silently shrink the
    digest.
    """
    today = today or datetime.now(timezone.utc).date()
    kept: list[Round] = []
    for r in rounds:
        if min_amount_eur and (r.amount_eur or 0) < min_amount_eur:
            continue
        if lookback_days and r.announced_on:
            try:
                announced = date.fromisoformat(r.announced_on)
            except ValueError:
                kept.append(r)
                continue
            if (today - announced).days > lookback_days or announced > today:
                continue
        kept.append(r)

    kept.sort(key=lambda r: (r.announced_on or "", r.amount_eur or 0), reverse=True)
    return kept


def dedupe(rounds: list[Round]) -> list[Round]:
    """Collapses duplicates, preferring the row that carries more detail."""
    by_key: dict[str, Round] = {}
    for r in rounds:
        existing = by_key.get(r.key)
        if existing is None:
            by_key[r.key] = r
            continue
        merged = existing
        if not merged.description and r.description:
            merged.description = r.description
        if merged.lead_investor == NOT_DISCLOSED and r.lead_investor != NOT_DISCLOSED:
            merged.lead_investor = r.lead_investor
        if merged.amount_eur is None and r.amount_eur is not None:
            merged.amount_eur = r.amount_eur
            merged.amount_display = r.amount_display
        if not merged.source_url and r.source_url:
            merged.source_url = r.source_url
        if not merged.sector and r.sector:
            merged.sector = r.sector
    return list(by_key.values())
