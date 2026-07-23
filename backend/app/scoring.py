"""Combines explicit AutoModerator/rule keyword hits with statistical
vocabulary-outlier and semantic-similarity signals into a single risk score
and a highlighted, explained draft.

The scoring formula below is a transparent heuristic, not a calibrated
model: explicit rule/AutoModerator hits dominate the score (and always
force risk_level to "high"), vocabulary outliers contribute next, and
topical/semantic drift contributes least. Tune the weights in
`check_draft` if your judgment differs.
"""

import re
from dataclasses import dataclass
from typing import Any, Optional

from . import fingerprint as fp_mod

FIELD_SKIP_PREFIXES = ("domain", "url", "flair", "author")


def _field_scope(field: str) -> str:
    """Maps an AutoModerator field name (e.g. 'title+body (includes, regex)')
    to which part(s) of a text draft it applies to."""
    f = field.lower().strip()
    if f.startswith("title+body") or f.startswith("full_text"):
        return "both"
    if f.startswith("title"):
        return "title"
    if f.startswith(("body", "selftext")):
        return "body"
    if any(f.startswith(p) for p in FIELD_SKIP_PREFIXES):
        return "skip"
    return "both"  # unrecognized modifier: be conservative, check everywhere


def _match_pattern(pattern: str, field: str, text: str) -> list[tuple[int, int, str]]:
    """Returns (start, end, matched_text) for every occurrence of `pattern`
    in `text`, honoring 'regex' / 'word' modifiers in the field name and
    otherwise falling back to a plain case-insensitive substring match."""
    f = field.lower()
    matches: list[tuple[int, int, str]] = []

    if "regex" in f:
        try:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                matches.append((m.start(), m.end(), m.group(0)))
            return matches
        except re.error:
            pass  # invalid regex in the config; fall through to literal match

    if "word" in f:
        try:
            for m in re.finditer(r"\b" + re.escape(pattern) + r"\b", text, re.IGNORECASE):
                matches.append((m.start(), m.end(), m.group(0)))
            return matches
        except re.error:
            return matches

    lower_text, lower_pat = text.lower(), pattern.lower()
    if not lower_pat:
        return matches
    start = 0
    while True:
        idx = lower_text.find(lower_pat, start)
        if idx == -1:
            break
        matches.append((idx, idx + len(pattern), text[idx : idx + len(pattern)]))
        start = idx + max(len(pattern), 1)
    return matches


@dataclass
class AutomodHitInternal:
    matched_text: str
    field: str
    scope: str  # "title" | "body"
    start: int
    end: int
    pattern: str
    action: Optional[str]
    context: str
    confidence: str  # "explicit" | "heuristic"


def find_automod_hits(title: str, body: str, keywords: list[dict[str, Any]]) -> list[AutomodHitInternal]:
    hits: list[AutomodHitInternal] = []
    for kw in keywords:
        pattern = kw.get("pattern", "")
        field = kw.get("field", "")
        if not pattern:
            continue
        scope = _field_scope(field)
        if scope == "skip":
            continue
        targets = []
        if scope in ("title", "both"):
            targets.append(("title", title))
        if scope in ("body", "both"):
            targets.append(("body", body))
        for scope_name, text in targets:
            if not text:
                continue
            for start, end, matched in _match_pattern(pattern, field, text):
                hits.append(
                    AutomodHitInternal(
                        matched_text=matched,
                        field=field,
                        scope=scope_name,
                        start=start,
                        end=end,
                        pattern=pattern,
                        action=kw.get("action"),
                        context=kw.get("context", ""),
                        confidence=kw.get("kind", "explicit"),
                    )
                )
    return hits


def _merge_spans(
    automod_hits: list[AutomodHitInternal], verdicts: list[fp_mod.TermVerdict]
) -> list[dict[str, Any]]:
    """Resolves overlapping flags for the same field into a non-overlapping
    set, preferring AutoModerator hits, then OOV terms, then rare terms."""
    events: list[dict[str, Any]] = []
    for h in automod_hits:
        events.append(
            {
                "start": h.start,
                "end": h.end,
                "text": h.matched_text,
                "type": "automod",
                "priority": 3,
                "reason": f"Matches an AutoModerator trigger ({h.field}).",
                "rule_text": h.context,
            }
        )
    for v in verdicts:
        if v.status == "normal":
            continue
        priority = 2 if v.status == "oov" else 1
        if v.status == "oov":
            reason = "This word/phrase never appears in this subreddit's sampled posts."
        else:
            reason = f"This word/phrase is rare in this subreddit (rarer than {v.percentile:.0f}% of its vocabulary)."
        events.append(
            {
                "start": v.start,
                "end": v.end,
                "text": v.phrase,
                "type": v.status,
                "priority": priority,
                "reason": reason,
                "rule_text": None,
            }
        )

    accepted: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for e in sorted(events, key=lambda e: (-e["priority"], -(e["end"] - e["start"]))):
        if any(not (e["end"] <= s or e["start"] >= en) for s, en in occupied):
            continue
        occupied.append((e["start"], e["end"]))
        accepted.append(e)
    accepted.sort(key=lambda e: e["start"])
    return accepted


def _build_concerns(
    explicit_hits: list[AutomodHitInternal],
    heuristic_hits: list[AutomodHitInternal],
    unigram_verdicts: list[fp_mod.TermVerdict],
    similarity: Optional[float],
) -> list[str]:
    concerns: list[str] = []
    seen: set[str] = set()

    for h in explicit_hits:
        if h.pattern in seen:
            continue
        seen.add(h.pattern)
        action_txt = f" (AutoModerator action: {h.action})" if h.action else ""
        snippet = h.context.splitlines()[0][:120] if h.context else ""
        concerns.append(f"'{h.matched_text}' in your {h.scope} matches an AutoModerator rule{action_txt}: {snippet}")
        if len(concerns) >= 3:
            return concerns

    for h in heuristic_hits:
        if h.pattern in seen:
            continue
        seen.add(h.pattern)
        concerns.append(
            f"'{h.matched_text}' may match a filtered keyword in this subreddit's AutoModerator "
            "config (low-confidence match; the config wasn't valid YAML)."
        )
        if len(concerns) >= 3:
            return concerns

    oov_terms = sorted({v.phrase for v in unigram_verdicts if v.status == "oov"})
    if oov_terms:
        sample = ", ".join(f"'{t}'" for t in oov_terms[:5])
        concerns.append(f"These words never appear in this subreddit's recent posts, which is unusual vocabulary here: {sample}.")
        if len(concerns) >= 3:
            return concerns

    if similarity is not None and similarity < 0.35:
        concerns.append(
            f"Your draft's overall topic doesn't closely resemble what's normally posted here (topical similarity score: {similarity:.2f})."
        )

    if not concerns:
        concerns.append("No explicit rule hits, and vocabulary/topic look consistent with this subreddit's recent posts.")
    return concerns[:3]


def check_draft(
    title: str,
    body: str,
    keywords: list[dict[str, Any]],
    fp: Optional[fp_mod.SubredditFingerprint],
) -> dict[str, Any]:
    title = title or ""
    body = body or ""

    automod_hits = find_automod_hits(title, body, keywords)
    explicit_hits = [h for h in automod_hits if h.confidence == "explicit"]
    heuristic_hits = [h for h in automod_hits if h.confidence == "heuristic"]

    term_verdicts_title: list[fp_mod.TermVerdict] = []
    term_verdicts_body: list[fp_mod.TermVerdict] = []
    similarity: Optional[float] = None

    if fp is not None:
        term_verdicts_title = fp_mod.classify_terms(fp, fp_mod.extract_candidate_spans(title))
        term_verdicts_body = fp_mod.classify_terms(fp, fp_mod.extract_candidate_spans(body))
        combined = f"{title} {body}".strip()
        similarity = fp_mod.semantic_fit(combined, fp)

    highlights: list[dict[str, Any]] = []
    for field_name, hits, verdicts in (
        ("title", [h for h in automod_hits if h.scope == "title"], term_verdicts_title),
        ("body", [h for h in automod_hits if h.scope == "body"], term_verdicts_body),
    ):
        for e in _merge_spans(hits, verdicts):
            highlights.append({**e, "field": field_name})

    automod_component = 0.0
    if explicit_hits:
        automod_component = min(100.0, 55 + 15 * (len(explicit_hits) - 1))
    elif heuristic_hits:
        automod_component = min(60.0, 25 + 10 * (len(heuristic_hits) - 1))

    unigram_verdicts = [v for v in (term_verdicts_title + term_verdicts_body) if " " not in v.phrase]
    if unigram_verdicts:
        oov_ratio = sum(1 for v in unigram_verdicts if v.status == "oov") / len(unigram_verdicts)
        rare_ratio = sum(1 for v in unigram_verdicts if v.status == "rare") / len(unigram_verdicts)
        vocab_component = min(100.0, oov_ratio * 100 + rare_ratio * 50)
    else:
        vocab_component = 0.0

    if similarity is None:
        semantic_component = 0.0
    else:
        semantic_component = max(0.0, min(100.0, (0.5 - similarity) * 200))

    if fp is None:
        overall = automod_component
    else:
        overall = 0.55 * automod_component + 0.30 * vocab_component + 0.15 * semantic_component
    overall = max(0.0, min(100.0, overall))

    if explicit_hits or overall >= 67:
        risk_level = "high"
    elif overall >= 33:
        risk_level = "medium"
    else:
        risk_level = "low"

    concerns = _build_concerns(explicit_hits, heuristic_hits, unigram_verdicts, similarity)

    return {
        "risk_score": round(overall),
        "risk_level": risk_level,
        "automod_hits": automod_hits,
        "highlights": highlights,
        "semantic_similarity": similarity,
        "top_concerns": concerns,
    }
