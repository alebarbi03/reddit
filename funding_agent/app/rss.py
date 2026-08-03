"""Fallback source: the tech.eu article feed.

Funding coverage on tech.eu follows a predictable headline grammar
("Acme raises €15M Series A led by Foo Ventures"), which is enough to recover
the four fields the digest needs when the Explorer itself can't be parsed.
It also enriches Explorer rows that arrive without a description.
"""

import logging
import re
from typing import Optional
from xml.etree import ElementTree

from .extract import _parse_date
from .models import NOT_DISCLOSED, Round, parse_amount

logger = logging.getLogger("fundingagent.rss")

# "raises", "secures", "lands", "closes", "bags", "picks up", "nets"
_RAISE_VERBS = r"(?:raises|raised|secures|secured|lands|landed|closes|closed|bags|nets|picks\s+up|scores|snaps\s+up)"

_HEADLINE_RE = re.compile(
    rf"^(?P<company>.{{2,80}}?)\s+{_RAISE_VERBS}\s+(?P<amount>[€$£]\s?[\d.,]+\s*(?:k|m|mn|bn|b|million|billion)?)",
    re.IGNORECASE,
)
# An investor name is a run of capitalised tokens ("Index Ventures", "b2venture",
# "Kima Ventures & Angels"). Bounding the match to that run stops it from
# swallowing the rest of the sentence when no punctuation follows the name.
_LED_BY_RE = re.compile(
    r"\bled\s+by\s+(?P<lead>[A-Z0-9][\w&.'’-]*"
    r"(?:\s+(?:[A-Z0-9][\w&.'’-]*|de|van|von|del|della|la|of|and|&)){0,5})"
)
_LEAD_TRAILING_RE = re.compile(r"\s+(?:and|with|to|in|at|of|&)$", re.IGNORECASE)
_STAGE_RE = re.compile(
    r"\b(pre-seed|preseed|seed|series\s+[a-h]|growth|bridge|angel|debt|grant|ipo|"
    r"private\s+placement|extension)\b",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#8217;", "'")
        .replace("&#8220;", '"')
        .replace("&#8221;", '"')
        .replace("&hellip;", "...")
    )
    return re.sub(r"\s+", " ", text).strip()


def parse_feed(xml_text: str) -> list[Round]:
    """Extracts funding rounds from an RSS/Atom document."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        logger.warning("could not parse feed: %s", exc)
        return []

    rounds: list[Round] = []
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in items:
        title = _clean(_text(item, ("title", "{http://www.w3.org/2005/Atom}title")))
        if not title:
            continue
        body = _clean(
            _text(
                item,
                (
                    "description",
                    "{http://purl.org/rss/1.0/modules/content/}encoded",
                    "{http://www.w3.org/2005/Atom}summary",
                ),
            )
        )
        round_ = round_from_headline(title, body)
        if round_:
            round_.announced_on = _parse_date(
                _text(item, ("pubDate", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"))
            )
            round_.source_url = _text(item, ("link",)) or _link_attr(item)
            rounds.append(round_)
    return rounds


def _text(item, tags: tuple[str, ...]) -> str:
    for tag in tags:
        node = item.find(tag)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def _link_attr(item) -> str:
    node = item.find("{http://www.w3.org/2005/Atom}link")
    return node.get("href", "") if node is not None else ""


def round_from_headline(title: str, body: str = "") -> Optional[Round]:
    """Parses "X raises €YM ... led by Z" into a Round, or None if not funding news."""
    match = _HEADLINE_RE.match(title)
    if not match:
        return None

    company = match.group("company").strip(" -–—:,")
    # Headlines sometimes prefix a country or vertical: "Berlin-based Acme".
    company = re.sub(
        r"^(?:[\w-]+-based|exclusive|breaking|updated)\s*[:,]?\s*", "", company, flags=re.IGNORECASE
    ).strip()
    if not company:
        return None

    amount = parse_amount(match.group("amount"))
    # Search the headline before the body: the headline names the lead without
    # the surrounding prose that a body sentence would trail into.
    lead = _find_lead(title) or _find_lead(body)
    stage_match = _STAGE_RE.search(f"{title} {body}")

    return Round(
        company=company,
        amount_eur=amount,
        description=_describe(body, company),
        lead_investor=lead or NOT_DISCLOSED,
        stage=stage_match.group(0).title() if stage_match else "",
        source="rss",
    )


def _find_lead(text: str) -> str:
    """Pulls the investor name out of a "led by X" phrase."""
    if not text:
        return ""
    match = _LED_BY_RE.search(text)
    if not match:
        return ""
    return _LEAD_TRAILING_RE.sub("", _clean(match.group("lead"))).strip(" ,.;:-")


def _describe(body: str, company: str) -> str:
    """Picks the sentence from an article blurb that explains what the company does."""
    if not body:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", body)
    for sentence in sentences:
        if re.search(r"\b(is|are|builds?|makes?|develops?|offers?|provides?|helps?|platform|software|enables?)\b", sentence, re.IGNORECASE):
            if len(sentence) > 30:
                return sentence.strip()
    return sentences[0].strip() if sentences else ""


def fetch_feed(url: str, timeout: int = 30) -> list[Round]:
    try:
        import requests

        from .fetcher import USER_AGENT

        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        return parse_feed(response.text)
    except Exception as exc:  # noqa: BLE001 - fallback source, never fatal
        logger.warning("RSS fetch failed (%s): %s", url, exc)
        return []


def enrich(rounds: list[Round], feed_rounds: list[Round]) -> list[Round]:
    """Fills gaps in Explorer rows using same-company rows from the feed."""
    by_company = {re.sub(r"[^a-z0-9]+", "", r.company.lower()): r for r in feed_rounds}
    for r in rounds:
        match = by_company.get(re.sub(r"[^a-z0-9]+", "", r.company.lower()))
        if not match:
            continue
        if not r.description and match.description:
            r.description = match.description
        if r.lead_investor == NOT_DISCLOSED and match.lead_investor != NOT_DISCLOSED:
            r.lead_investor = match.lead_investor
        if not r.stage and match.stage:
            r.stage = match.stage
        if not r.source_url and match.source_url:
            r.source_url = match.source_url
    return rounds
