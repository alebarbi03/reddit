"""Tests for the RSS fallback parser and the de-duplication store."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import NOT_DISCLOSED, Round
from app.rss import enrich, parse_feed, round_from_headline
from app.store import Store

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Aurora Robotics raises &#8364;42M Series B led by Northzone</title>
    <link>https://tech.eu/2026/08/02/aurora-robotics/</link>
    <pubDate>Sun, 02 Aug 2026 09:00:00 +0000</pubDate>
    <description>&lt;p&gt;Aurora Robotics builds warehouse robots that pick and pack orders for grocery retailers.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Volt Health secures &#8364;8.5M seed round led by Index Ventures</title>
    <link>https://tech.eu/2026/08/01/volt-health/</link>
    <pubDate>Sat, 01 Aug 2026 08:00:00 +0000</pubDate>
    <description>Volt Health provides AI triage software for hospital emergency departments.</description>
  </item>
  <item>
    <title>Five predictions for European tech in 2027</title>
    <link>https://tech.eu/2026/08/01/predictions/</link>
    <pubDate>Sat, 01 Aug 2026 07:00:00 +0000</pubDate>
    <description>An opinion piece.</description>
  </item>
</channel></rss>
"""


def test_parse_feed_extracts_only_funding_items():
    rounds = parse_feed(FEED)
    assert [r.company for r in rounds] == ["Aurora Robotics", "Volt Health"]


def test_parse_feed_fields():
    aurora = parse_feed(FEED)[0]
    assert aurora.amount_eur == 42_000_000
    assert aurora.lead_investor == "Northzone"
    assert aurora.stage == "Series B"
    assert aurora.announced_on == "2026-08-02"
    assert "warehouse robots" in aurora.description.lower()
    assert aurora.source_url == "https://tech.eu/2026/08/02/aurora-robotics/"


def test_headline_without_lead_investor():
    r = round_from_headline("Kestrel Mobility lands €3M seed")
    assert r.company == "Kestrel Mobility"
    assert r.amount_eur == 3_000_000
    assert r.lead_investor == NOT_DISCLOSED


def test_headline_strips_location_prefix():
    r = round_from_headline("Berlin-based Solaris Grid raises €5M led by Cherry Ventures")
    assert r.company == "Solaris Grid"


def test_non_funding_headline_rejected():
    assert round_from_headline("Why European VCs are cautious this year") is None


def test_enrich_fills_gaps_from_the_feed():
    explorer = [Round(company="Aurora Robotics", amount_eur=42_000_000, announced_on="2026-08-02")]
    enriched = enrich(explorer, parse_feed(FEED))
    assert "warehouse robots" in enriched[0].description.lower()
    assert enriched[0].lead_investor == "Northzone"


def test_enrich_does_not_overwrite_explorer_values():
    explorer = [
        Round(
            company="Aurora Robotics",
            amount_eur=42_000_000,
            description="Canonical description.",
            lead_investor="Someone Else",
        )
    ]
    enriched = enrich(explorer, parse_feed(FEED))
    assert enriched[0].description == "Canonical description."
    assert enriched[0].lead_investor == "Someone Else"


def _store() -> Store:
    tmp = tempfile.mkdtemp()
    return Store(Path(tmp) / "test.db")


def test_store_reports_each_round_once():
    store = _store()
    rounds = [
        Round(company="Aurora Robotics", amount_eur=42_000_000, announced_on="2026-08-02"),
        Round(company="Volt Health", amount_eur=8_500_000, announced_on="2026-08-01"),
    ]
    assert len(store.new_rounds(rounds)) == 2
    store.record(rounds)
    assert store.new_rounds(rounds) == []


def test_store_still_surfaces_genuinely_new_rounds():
    store = _store()
    store.record([Round(company="Aurora Robotics", amount_eur=42_000_000, announced_on="2026-08-02")])
    incoming = [
        Round(company="Aurora Robotics", amount_eur=42_000_000, announced_on="2026-08-02"),
        Round(company="Nimbus Data", amount_eur=12_500_000, announced_on="2026-08-03"),
    ]
    assert [r.company for r in store.new_rounds(incoming)] == ["Nimbus Data"]


def test_reworded_description_does_not_resurface_a_round():
    store = _store()
    store.record([Round(company="Aurora Robotics", amount_eur=42_000_000, announced_on="2026-08-02")])
    reworded = [
        Round(
            company="Aurora robotics",  # different casing, enriched blurb
            amount_eur=42_000_000,
            announced_on="2026-08-02",
            description="Now with a description.",
        )
    ]
    assert store.new_rounds(reworded) == []


def test_run_log():
    store = _store()
    store.log_run(found=20, new_rounds=5, posts=1, source="explorer")
    runs = store.recent_runs()
    assert runs[0]["found"] == 20 and runs[0]["posts"] == 1
