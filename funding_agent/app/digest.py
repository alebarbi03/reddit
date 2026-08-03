"""The morning brief: the four fields, for the terminal and for a Markdown file."""

from datetime import date
from typing import Optional

from .models import NOT_DISCLOSED, Round, format_amount


def _line(r: Round) -> tuple[str, str, str, str]:
    stage = f" ({r.stage})" if r.stage else ""
    return (
        r.company,
        f"{r.amount_display}{stage}",
        r.description or (f"{r.sector} company" if r.sector else "—"),
        r.lead_investor or NOT_DISCLOSED,
    )


def render_terminal(rounds: list[Round], when: Optional[date] = None) -> str:
    when = when or date.today()
    if not rounds:
        return f"Tech.eu funding brief — {when:%a %d %b %Y}\n\nNo new rounds since the last run."

    total = sum(r.amount_eur or 0 for r in rounds)
    out = [
        f"Tech.eu funding brief — {when:%a %d %b %Y}",
        f"{len(rounds)} new round{'s' if len(rounds) != 1 else ''} · {format_amount(total)} disclosed",
        "",
    ]
    for i, r in enumerate(rounds, start=1):
        company, amount, what, lead = _line(r)
        out.append(f"{i}. {company} — {amount}")
        out.append(f"   What they do : {_wrap(what)}")
        out.append(f"   Lead investor: {lead}")
        if r.source_url:
            out.append(f"   Source       : {r.source_url}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _wrap(text: str, width: int = 88, indent: str = " " * 18) -> str:
    import textwrap

    wrapped = textwrap.wrap(text, width=width)
    return f"\n{indent}".join(wrapped) if wrapped else "—"


def render_markdown(rounds: list[Round], posts: list[str], when: Optional[date] = None) -> str:
    when = when or date.today()
    total = sum(r.amount_eur or 0 for r in rounds)
    out = [
        f"# Tech.eu funding brief — {when:%A %d %B %Y}",
        "",
        f"**{len(rounds)} new round{'s' if len(rounds) != 1 else ''}** · {format_amount(total)} disclosed · "
        "source: [Tech.eu Funding Explorer](https://funding.tech.eu/)",
        "",
        "| # | Company | Raised | What they do | Lead investor |",
        "|---|---------|--------|--------------|---------------|",
    ]
    for i, r in enumerate(rounds, start=1):
        company, amount, what, lead = _line(r)
        if r.source_url:
            company = f"[{company}]({r.source_url})"
        out.append(f"| {i} | {company} | {amount} | {_escape(what)} | {_escape(lead)} |")

    if posts:
        out += ["", "## LinkedIn posts", ""]
        for i, post in enumerate(posts, start=1):
            out += [
                f"### Post {i} ({len(post)} characters)",
                "",
                "```text",
                post,
                "```",
                "",
            ]
    return "\n".join(out).rstrip() + "\n"


def _escape(text: str) -> str:
    return (text or "—").replace("|", "\\|").replace("\n", " ")
