"""Core data types for the Tech.eu funding agent.

A `Round` is the normalised shape everything else in the agent speaks: the
scrapers produce them, the store de-duplicates them, and the digest and
LinkedIn writers consume them.
"""

import hashlib
import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

NOT_DISCLOSED = "Not disclosed"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


@dataclass
class Round:
    company: str
    amount_eur: Optional[float] = None
    amount_display: str = ""
    description: str = ""
    lead_investor: str = NOT_DISCLOSED
    other_investors: list[str] = field(default_factory=list)
    stage: str = ""
    sector: str = ""
    announced_on: str = ""  # ISO date (YYYY-MM-DD) when known
    source_url: str = ""
    source: str = "explorer"  # "explorer" | "rss"

    def __post_init__(self) -> None:
        self.company = (self.company or "").strip()
        self.description = (self.description or "").strip()
        self.lead_investor = (self.lead_investor or "").strip() or NOT_DISCLOSED
        if not self.amount_display:
            self.amount_display = format_amount(self.amount_eur)

    @property
    def key(self) -> str:
        """Stable identity for de-duplication across runs.

        Deliberately excludes the description and investor list: those get
        enriched or reworded upstream, and a reworded blurb must not make a
        round look new the next morning.
        """
        bucket = ""
        if self.amount_eur:
            # Round to 2 significant-ish figures so €15,000,000 and
            # €15.1M (currency-converted differently) collapse together.
            bucket = f"{self.amount_eur:.3g}"
        raw = f"{_slug(self.company)}|{bucket}|{self.announced_on[:7]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def has_content(self) -> bool:
        """Whether this row carries enough to be worth showing a human."""
        return bool(self.company) and (
            self.amount_eur is not None or bool(self.description)
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        return d


def format_amount(amount_eur: Optional[float]) -> str:
    """Renders a EUR amount the way a funding headline would."""
    if not amount_eur or amount_eur <= 0:
        return "Undisclosed amount"
    if amount_eur >= 1_000_000_000:
        value = amount_eur / 1_000_000_000
        suffix = "B"
    elif amount_eur >= 1_000_000:
        value = amount_eur / 1_000_000
        suffix = "M"
    elif amount_eur >= 1_000:
        value = amount_eur / 1_000
        suffix = "K"
    else:
        return f"€{amount_eur:,.0f}"
    # Half-up, so €1.25B reads as €1.3B rather than float-rounding down.
    quantized = Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    text = f"{quantized}".rstrip("0").rstrip(".")
    return f"€{text}{suffix}"


_MULTIPLIERS = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
}

_AMOUNT_RE = re.compile(
    r"(?P<currency>[€$£]|eur|usd|gbp)?\s*"
    r"(?P<number>\d[\d,.\s]*\d|\d)\s*"
    r"(?P<suffix>k|m|mn|bn|b|thousand|million|billion)?",
    re.IGNORECASE,
)

# Rough, stable-enough conversions for display ranking only. The explorer
# publishes EUR-normalised figures, so these only bite on RSS-sourced rows.
_FX_TO_EUR = {"€": 1.0, "eur": 1.0, "$": 0.92, "usd": 0.92, "£": 1.17, "gbp": 1.17}


def parse_amount(value: Any, currency: Optional[str] = None) -> Optional[float]:
    """Best-effort conversion of an amount into a EUR float.

    Accepts raw numbers (15000000), formatted strings ("€15M", "1,500,000"),
    and dicts such as {"value": 15, "unit": "M", "currency": "EUR"}.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
        return _to_eur(amount, currency) if amount > 0 else None
    if isinstance(value, dict):
        inner = None
        for k in ("amount", "value", "raised", "total", "eur", "amount_eur"):
            if k in value:
                inner = value[k]
                break
        cur = value.get("currency") or value.get("currency_code") or currency
        unit = value.get("unit") or value.get("scale")
        parsed = parse_amount(inner, cur)
        if parsed is not None and unit:
            parsed *= _MULTIPLIERS.get(str(unit).strip().lower(), 1)
        return parsed
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    match = _AMOUNT_RE.search(text)
    if not match:
        return None
    number = match.group("number").replace(" ", "").replace(",", "")
    # "1.500.000" is thousands-separated, "1.5" is decimal.
    if number.count(".") > 1 or re.search(r"\.\d{3}$", number):
        number = number.replace(".", "")
    try:
        amount = float(number)
    except ValueError:
        return None
    suffix = (match.group("suffix") or "").lower()
    if suffix:
        amount *= _MULTIPLIERS.get(suffix, 1)
    cur = (match.group("currency") or currency or "€").lower()
    return _to_eur(amount, cur) if amount > 0 else None


def _to_eur(amount: float, currency: Optional[str]) -> float:
    if not currency:
        return amount
    return amount * _FX_TO_EUR.get(str(currency).strip().lower(), 1.0)
