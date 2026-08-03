"""Builds ready-to-publish LinkedIn posts, 5 companies per post.

LinkedIn strips markdown, collapses long posts behind a "…see more" fold after
roughly the first 200 characters, and caps a post at 3,000. So: plain text with
unicode bullets, the hook in line one, and length-aware trimming rather than a
hard cut mid-word.
"""

import re
from typing import Iterator, Optional

from .models import NOT_DISCLOSED, Round

HASHTAGS = "#VentureCapital #Startups #EuropeanTech #Funding #TechEU"
SOURCE_LINE = "Source: Tech.eu Funding Explorer (funding.tech.eu)"

_MAX_DESCRIPTION = 180


def chunk(rounds: list[Round], per_post: int = 5, max_posts: int = 3, include_partial: bool = True) -> list[list[Round]]:
    """Splits rounds into per-post groups."""
    if per_post < 1:
        per_post = 1
    groups = [rounds[i : i + per_post] for i in range(0, len(rounds), per_post)]
    if groups and not include_partial and len(groups[-1]) < per_post:
        groups = groups[:-1]
    return groups[:max_posts] if max_posts else groups


def _describe(r: Round) -> str:
    """One clause on what the company does, trimmed to a readable length."""
    text = (r.description or "").strip()
    if not text:
        text = f"{r.sector} company" if r.sector else "Details not disclosed"
    text = re.sub(r"\s+", " ", text)
    if len(text) > _MAX_DESCRIPTION:
        cut = text[:_MAX_DESCRIPTION].rsplit(" ", 1)[0].rstrip(",.;:")
        text = cut + "…"
    return text if text.endswith((".", "…", "!", "?")) else text + "."


def _headline(r: Round) -> str:
    parts = [r.amount_display]
    if r.stage:
        parts.append(r.stage if not r.stage.lower().startswith("series") else r.stage.title())
    return " ".join(p for p in parts if p)


def _entry(index: int, r: Round, description_limit: Optional[int] = None) -> str:
    description = _describe(r)
    if description_limit and len(description) > description_limit:
        description = description[:description_limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    lead = r.lead_investor if r.lead_investor and r.lead_investor != NOT_DISCLOSED else NOT_DISCLOSED
    return (
        f"{index}. {r.company} — {_headline(r)}\n"
        f"   What they do: {description}\n"
        f"   Lead investor: {lead}"
    )


def _hook(group: list[Round]) -> str:
    """First line — the only part most people read before the fold."""
    from .models import format_amount

    total = sum(r.amount_eur or 0 for r in group)
    count = len(group)

    if count == 1:
        company = group[0].company
        if total > 0:
            return f"{company} just raised {format_amount(total)}. Here's what they do — and who backed them."
        return f"{company} just raised a new round. Here's what they do — and who backed them."
    if total > 0:
        return (
            f"{count} European startups raised {format_amount(total)} between them. "
            "Here's who — and who backed them."
        )
    return f"{count} European funding rounds worth knowing about this morning."


def build_post(group: list[Round], max_chars: int = 2900, part: Optional[tuple[int, int]] = None) -> str:
    """Renders one publish-ready post."""
    header = _hook(group)
    if part and part[1] > 1:
        header += f" ({part[0]}/{part[1]})"

    def render(description_limit: Optional[int]) -> str:
        entries = [_entry(i, r, description_limit) for i, r in enumerate(group, start=1)]
        return "\n\n".join([header, *entries, SOURCE_LINE, HASHTAGS])

    post = render(None)
    # Trim descriptions progressively rather than truncating the post, so the
    # lead investor line of the last company never gets cut off.
    for limit in (150, 120, 90, 70, 50):
        if len(post) <= max_chars:
            break
        post = render(limit)
    if len(post) > max_chars:
        post = post[: max_chars - 1].rsplit("\n", 1)[0]
    return post


def build_posts(
    rounds: list[Round],
    per_post: int = 5,
    max_posts: int = 3,
    include_partial: bool = True,
    max_chars: int = 2900,
) -> list[str]:
    groups = chunk(rounds, per_post, max_posts, include_partial)
    total = len(groups)
    return [
        build_post(group, max_chars=max_chars, part=(i, total))
        for i, group in enumerate(groups, start=1)
    ]


def iter_posts(rounds: list[Round], **kwargs) -> Iterator[str]:
    yield from build_posts(rounds, **kwargs)
