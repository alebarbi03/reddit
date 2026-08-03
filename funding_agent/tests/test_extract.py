"""Tests for the round-detection heuristics.

The Explorer's exact payload shape isn't contractual, so these fixtures cover
several plausible shapes (flat fields, nested company objects, tagged investor
lists, string amounts) plus the decoys a real SPA ships alongside them.

Run with: python -m pytest funding_agent/tests -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extract import (
    best_rounds,
    dedupe,
    filter_rounds,
    rounds_from_html,
    round_from_item,
    scan_json_blobs,
    score_list,
)
from app.models import NOT_DISCLOSED, Round, format_amount, parse_amount

# A payload in the style an SPA table endpoint returns: rounds nested under a
# wrapper, alongside pagination and unrelated arrays.
EXPLORER_PAYLOAD = {
    "pageProps": {
        "filters": [{"menuItem": "Sector"}, {"menuItem": "Country"}],
        "data": {
            "rounds": [
                {
                    "company": {"name": "Aurora Robotics", "shortDescription": "Warehouse robots that pick and pack orders."},
                    "amountEur": 42000000,
                    "stage": "Series B",
                    "announcedOn": "2026-08-02",
                    "sector": "Robotics",
                    "investors": [
                        {"name": "Northzone", "isLead": True},
                        {"name": "Speedinvest", "isLead": False},
                    ],
                    "url": "/rounds/aurora-robotics",
                },
                {
                    "company": {"name": "Volt Health", "shortDescription": "AI triage for hospital emergency departments."},
                    "amountEur": 8500000,
                    "stage": "Seed",
                    "announcedOn": "2026-08-01",
                    "sector": "Healthtech",
                    "investors": [{"name": "Index Ventures", "role": "lead"}],
                },
            ],
            "pagination": {"page": 1, "total": 2},
        },
    }
}

# The same information in a flatter, differently-named shape.
FLAT_PAYLOAD = [
    {
        "company_name": "Nimbus Data",
        "amount": "€12.5M",
        "round_type": "Series A",
        "lead_investor": "Atomico",
        "description": "Data pipelines for regulated industries.",
        "date_announced": "2026-07-31",
    },
    {
        "company_name": "Kestrel Mobility",
        "amount": "€3M",
        "round_type": "Pre-Seed",
        "lead_investor": "LocalGlobe",
        "description": "Fleet routing for last-mile delivery.",
        "date_announced": "2026-07-30",
    },
]

DECOY_PAYLOAD = {
    "navigation": [{"name": "Home", "url": "/"}, {"name": "About", "url": "/about"}],
    "authors": [{"name": "A Writer", "url": "/a"}, {"name": "B Writer", "url": "/b"}],
}


def test_extracts_nested_explorer_payload():
    rounds = best_rounds(EXPLORER_PAYLOAD, "https://funding.tech.eu")
    assert len(rounds) == 2

    aurora = rounds[0]
    assert aurora.company == "Aurora Robotics"
    assert aurora.amount_eur == 42_000_000
    assert aurora.amount_display == "€42M"
    assert aurora.description == "Warehouse robots that pick and pack orders."
    assert aurora.lead_investor == "Northzone"
    assert aurora.other_investors == ["Speedinvest"]
    assert aurora.stage == "Series B"
    assert aurora.announced_on == "2026-08-02"
    assert aurora.source_url == "https://funding.tech.eu/rounds/aurora-robotics"


def test_lead_detected_from_role_field():
    rounds = best_rounds(EXPLORER_PAYLOAD)
    assert rounds[1].lead_investor == "Index Ventures"


def test_extracts_flat_payload_with_string_amounts():
    rounds = best_rounds(FLAT_PAYLOAD)
    assert [r.company for r in rounds] == ["Nimbus Data", "Kestrel Mobility"]
    assert rounds[0].amount_eur == 12_500_000
    assert rounds[0].lead_investor == "Atomico"
    assert rounds[1].amount_display == "€3M"


def test_decoy_lists_are_not_mistaken_for_rounds():
    assert best_rounds(DECOY_PAYLOAD) == []
    assert score_list(DECOY_PAYLOAD["navigation"]) == 0.0


def test_rounds_win_over_decoys_in_the_same_document():
    combined = {"nav": DECOY_PAYLOAD["navigation"], "results": FLAT_PAYLOAD}
    rounds = best_rounds(combined)
    assert {r.company for r in rounds} == {"Nimbus Data", "Kestrel Mobility"}


def test_unlabelled_investor_list_treats_first_as_lead():
    item = {
        "name": "Solaris Grid",
        "amount_eur": 5_000_000,
        "investors": ["Cherry Ventures", "Angel Collective"],
    }
    r = round_from_item(item)
    assert r.lead_investor == "Cherry Ventures"
    assert r.other_investors == ["Angel Collective"]


def test_inline_lead_marker_in_string_investors():
    r = round_from_item({"name": "Foo", "amount": "€1M", "investors": ["Bar Capital (lead)", "Baz Angels"]})
    assert r.lead_investor == "Bar Capital"
    assert r.other_investors == ["Baz Angels"]


def test_missing_investors_falls_back_to_not_disclosed():
    r = round_from_item({"name": "Quiet Co", "amount_eur": 2_000_000})
    assert r.lead_investor == NOT_DISCLOSED


def test_epoch_millisecond_dates():
    r = round_from_item({"name": "Epoch Co", "amount_eur": 1_000_000, "announcedAt": 1754179200000})
    assert r.announced_on.startswith("2025-")


def test_rounds_from_embedded_html_json():
    html = (
        "<html><body><script id='__NEXT_DATA__' type='application/json'>"
        + json.dumps(EXPLORER_PAYLOAD)
        + "</script></body></html>"
    )
    rounds = rounds_from_html(html)
    assert {r.company for r in rounds} == {"Aurora Robotics", "Volt Health"}


def test_rounds_from_escaped_rsc_flight_chunk():
    escaped = json.dumps(json.dumps(FLAT_PAYLOAD))
    html = f'<script>self.__next_f.push([1,{escaped}])</script>'
    rounds = rounds_from_html(html)
    assert {r.company for r in rounds} == {"Nimbus Data", "Kestrel Mobility"}


def test_scan_json_blobs_finds_embedded_values():
    blobs = list(scan_json_blobs('junk {"a": 1} more [{"b": 2}] tail'))
    assert {"a": 1} in blobs
    assert [{"b": 2}] in blobs


def test_filter_by_amount_and_recency():
    from datetime import date

    rounds = [
        Round(company="Big", amount_eur=50_000_000, announced_on="2026-08-02"),
        Round(company="Small", amount_eur=100_000, announced_on="2026-08-02"),
        Round(company="Stale", amount_eur=20_000_000, announced_on="2026-01-01"),
        Round(company="Undated", amount_eur=9_000_000),
    ]
    kept = filter_rounds(rounds, lookback_days=3, min_amount_eur=1_000_000, today=date(2026, 8, 3))
    names = [r.company for r in kept]
    assert "Big" in names
    assert "Undated" in names  # no date is a parsing gap, not evidence of staleness
    assert "Small" not in names
    assert "Stale" not in names


def test_dedupe_merges_detail_across_sources():
    sparse = Round(company="Aurora Robotics", amount_eur=42_000_000, announced_on="2026-08-02")
    rich = Round(
        company="Aurora Robotics",
        amount_eur=42_000_000,
        announced_on="2026-08-02",
        description="Warehouse robots.",
        lead_investor="Northzone",
    )
    merged = dedupe([sparse, rich])
    assert len(merged) == 1
    assert merged[0].description == "Warehouse robots."
    assert merged[0].lead_investor == "Northzone"


def test_parse_amount_variants():
    assert parse_amount(15_000_000) == 15_000_000
    assert parse_amount("€15M") == 15_000_000
    assert parse_amount("15,000,000") == 15_000_000
    assert parse_amount("1.500.000") == 1_500_000
    assert parse_amount("€1.2bn") == 1_200_000_000
    assert parse_amount({"value": 20, "unit": "M", "currency": "EUR"}) == 20_000_000
    assert parse_amount("undisclosed") is None
    assert parse_amount(None) is None


def test_format_amount():
    assert format_amount(42_000_000) == "€42M"
    assert format_amount(1_250_000_000) == "€1.3B"
    assert format_amount(800_000) == "€800K"
    assert format_amount(None) == "Undisclosed amount"
