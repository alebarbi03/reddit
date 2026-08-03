"""Tests for post construction: 5 per post, all four fields, within LinkedIn's cap."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.linkedin import build_post, build_posts, chunk
from app.models import NOT_DISCLOSED, Round


def make_rounds(n: int, description: str = "Builds software for European enterprises.") -> list[Round]:
    return [
        Round(
            company=f"Company {i}",
            amount_eur=(i + 1) * 1_000_000,
            description=description,
            lead_investor=f"Investor {i}",
            stage="Series A",
            announced_on="2026-08-03",
        )
        for i in range(n)
    ]


def test_five_companies_per_post():
    groups = chunk(make_rounds(12), per_post=5, max_posts=3)
    assert [len(g) for g in groups] == [5, 5, 2]


def test_partial_group_can_be_dropped():
    groups = chunk(make_rounds(12), per_post=5, max_posts=3, include_partial=False)
    assert [len(g) for g in groups] == [5, 5]


def test_max_posts_caps_output():
    assert len(build_posts(make_rounds(40), per_post=5, max_posts=3)) == 3


def test_post_contains_all_four_fields_per_company():
    post = build_post(make_rounds(5))
    for i in range(5):
        assert f"Company {i}" in post
        assert f"Investor {i}" in post
    assert post.count("What they do:") == 5
    assert post.count("Lead investor:") == 5
    assert "€1M" in post  # amount rendered


def test_post_is_numbered_and_sourced():
    post = build_post(make_rounds(5))
    assert post.startswith("5 European startups raised")
    for n in range(1, 6):
        assert f"\n{n}. " in "\n" + post
    assert "funding.tech.eu" in post
    assert "#VentureCapital" in post


def test_undisclosed_lead_is_stated_not_blank():
    r = Round(company="Quiet Co", amount_eur=1_000_000, description="Does things.")
    post = build_post([r])
    assert f"Lead investor: {NOT_DISCLOSED}" in post


def test_single_company_post_reads_naturally():
    post = build_post([Round(company="Kestrel Mobility", amount_eur=3_000_000, description="Fleet routing.")])
    assert post.startswith("Kestrel Mobility just raised €3M.")
    assert "startups" not in post.splitlines()[0]


def test_missing_description_falls_back_to_sector():
    r = Round(company="Terse Co", amount_eur=1_000_000, sector="Fintech")
    assert "What they do: Fintech company." in build_post([r])


def test_long_descriptions_are_trimmed_to_fit_the_character_cap():
    rounds = make_rounds(5, description="A very long description. " * 100)
    post = build_post(rounds, max_chars=2900)
    assert len(post) <= 2900
    # Trimming must not cost us the fields the brief is about.
    assert post.count("Lead investor:") == 5
    assert post.count("What they do:") == 5


def test_multi_post_runs_are_part_numbered():
    posts = build_posts(make_rounds(10), per_post=5, max_posts=3)
    assert len(posts) == 2
    assert "(1/2)" in posts[0]
    assert "(2/2)" in posts[1]


def test_single_post_has_no_part_suffix():
    posts = build_posts(make_rounds(5), per_post=5, max_posts=3)
    assert "(1/1)" not in posts[0]


def test_hook_totals_the_round_sizes():
    posts = build_posts(make_rounds(5), per_post=5)
    # 1+2+3+4+5 = 15M
    assert "€15M" in posts[0].splitlines()[0]
