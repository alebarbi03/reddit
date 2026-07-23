"""Read-only Reddit access via PRAW: subreddit metadata, rules, AutoModerator
config, and live post corpora. This module never posts, comments, votes, or
otherwise writes to Reddit.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import praw
import prawcore
import yaml

from .config import settings

logger = logging.getLogger("subfit.reddit")

_reddit_singleton: Optional[praw.Reddit] = None

# Listings combined (sequentially, never concurrently) to build a diverse,
# de-duplicated sample of currently-live posts without exceeding Reddit's
# per-listing cap.
POST_LISTINGS: list[tuple[str, dict[str, Any]]] = [
    ("new", {}),
    ("hot", {}),
    ("rising", {}),
    ("top", {"time_filter": "year"}),
    ("top", {"time_filter": "all"}),
]

AUTOMOD_WIKI_PAGES = ["config/automoderator", "automoderator"]

TRIGGER_KEY_RE = re.compile(
    r"^(title|body|title\+body|selftext|flair_text|flair_css_class|"
    r"author_flair_text|author_text|domain|url|link_flair_text|full_text)\b",
    re.IGNORECASE,
)


class RedditNotConfigured(RuntimeError):
    pass


def get_reddit() -> praw.Reddit:
    global _reddit_singleton
    if _reddit_singleton is None:
        if not settings.has_reddit_credentials:
            raise RedditNotConfigured(
                "Reddit API credentials are not configured. Set REDDIT_CLIENT_ID "
                "and REDDIT_CLIENT_SECRET in your .env file (see README.md)."
            )
        _reddit_singleton = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            check_for_async=False,
        )
        _reddit_singleton.read_only = True
    return _reddit_singleton


def normalize_subreddit_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"^/?r/", "", name, flags=re.IGNORECASE)
    return name.strip("/ ").lower()


@dataclass
class SubredditMeta:
    name: str
    display_name: str = ""
    subscribers: int = 0
    over18: bool = False
    quarantined: bool = False
    status: str = "error"  # ok | private | banned | quarantined | not_found | error
    status_detail: str = ""


def fetch_subreddit_meta(name: str) -> SubredditMeta:
    name = normalize_subreddit_name(name)
    reddit = get_reddit()
    try:
        sub = reddit.subreddit(name)
        _ = sub.id  # forces the /about fetch, surfaces access errors
        if getattr(sub, "quarantined", False):
            return SubredditMeta(
                name=name,
                display_name=getattr(sub, "display_name", name),
                quarantined=True,
                status="quarantined",
                status_detail=(
                    "This subreddit is quarantined. SubFit does not auto "
                    "opt-in to quarantined subreddits, so its posts/rules "
                    "cannot be fetched."
                ),
            )
        return SubredditMeta(
            name=name,
            display_name=getattr(sub, "display_name", name),
            subscribers=getattr(sub, "subscribers", 0) or 0,
            over18=bool(getattr(sub, "over18", False)),
            quarantined=False,
            status="ok",
        )
    except prawcore.exceptions.Redirect:
        return SubredditMeta(
            name=name, status="not_found",
            status_detail="Subreddit does not exist (or was banned).",
        )
    except prawcore.exceptions.NotFound:
        return SubredditMeta(
            name=name, status="not_found", status_detail="Subreddit not found."
        )
    except prawcore.exceptions.Forbidden:
        return SubredditMeta(
            name=name, status="private",
            status_detail="Subreddit is private, quarantined, or otherwise forbidden.",
        )
    except prawcore.exceptions.PrawcoreException as e:
        return SubredditMeta(name=name, status="error", status_detail=f"Reddit API error: {e}")


def fetch_rules(name: str) -> list[dict[str, Any]]:
    reddit = get_reddit()
    sub = reddit.subreddit(normalize_subreddit_name(name))
    rules: list[dict[str, Any]] = []
    try:
        for r in sub.rules:
            rules.append(
                {
                    "short_name": getattr(r, "short_name", "") or "",
                    "description": getattr(r, "description", "") or "",
                    "violation_reason": getattr(r, "violation_reason", "") or "",
                    "priority": getattr(r, "priority", None),
                }
            )
    except prawcore.exceptions.PrawcoreException as e:
        logger.warning("Could not fetch rules for r/%s: %s", name, e)
    return rules


def fetch_automod_raw(name: str) -> Optional[str]:
    """Try the public AutoModerator wiki config page(s). Returns None if
    unavailable (most subs don't expose this, or it's mod-only)."""
    reddit = get_reddit()
    sub = reddit.subreddit(normalize_subreddit_name(name))
    for page_name in AUTOMOD_WIKI_PAGES:
        try:
            page = sub.wiki[page_name]
            content = page.content_md
            if content and content.strip():
                return content
        except (prawcore.exceptions.NotFound, prawcore.exceptions.Forbidden):
            continue
        except prawcore.exceptions.PrawcoreException as e:
            logger.info("Automod wiki page %s unavailable for r/%s: %s", page_name, name, e)
            continue
    return None


def _collect_strings(value: Any, field: str, out: list[dict[str, Any]]) -> None:
    if isinstance(value, str):
        if 2 <= len(value) <= 200:
            out.append({"pattern": value, "field": field})
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                if 2 <= len(item) <= 200:
                    out.append({"pattern": item, "field": field})
            elif isinstance(item, dict):
                _walk_yaml(item, out)
    elif isinstance(value, dict):
        _walk_yaml(value, out)


def _walk_yaml(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            key_str = str(k)
            if TRIGGER_KEY_RE.match(key_str.strip()):
                _collect_strings(v, key_str, out)
            else:
                _walk_yaml(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_yaml(item, out)


def parse_automod_keywords(raw_text: Optional[str]) -> list[dict[str, Any]]:
    """Best-effort extraction of trigger keywords/phrases from an
    AutoModerator wiki config. AutoMod configs are YAML documents separated
    by `---`; we parse each document independently so one malformed rule
    doesn't blank out the rest, and fall back to a regex heuristic if the
    whole page fails to parse as YAML at all."""
    if not raw_text:
        return []

    out: list[dict[str, Any]] = []
    parsed_any = False
    doc_texts = re.split(r"^\s*---\s*$", raw_text, flags=re.MULTILINE)

    for doc_text in doc_texts:
        if not doc_text.strip():
            continue
        try:
            doc = yaml.safe_load(doc_text)
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        parsed_any = True

        action = doc.get("action")
        context = doc_text.strip()
        if len(context) > 400:
            context = context[:400] + "..."

        doc_items: list[dict[str, Any]] = []
        _walk_yaml(doc, doc_items)
        for item in doc_items:
            item["action"] = action
            item["context"] = context
            item["kind"] = "explicit"
        out.extend(doc_items)

    if not parsed_any:
        for m in re.finditer(r'["\']([^"\']{3,60})["\']', raw_text):
            out.append(
                {
                    "pattern": m.group(1),
                    "field": "unknown",
                    "action": None,
                    "context": "Extracted heuristically; AutoMod config was not valid YAML.",
                    "kind": "heuristic",
                }
            )

    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        key = (item["pattern"].strip().lower(), item.get("field", ""))
        if key in seen or not item["pattern"].strip():
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def fetch_posts(name: str, limit: int) -> list[dict[str, Any]]:
    """Sequentially pulls from multiple listings (never concurrently) to
    build a de-duplicated sample of up to `limit` currently-live posts."""
    reddit = get_reddit()
    sub = reddit.subreddit(normalize_subreddit_name(name))
    posts: dict[str, dict[str, Any]] = {}

    for listing_name, kwargs in POST_LISTINGS:
        if len(posts) >= limit:
            break
        try:
            listing_fn = getattr(sub, listing_name)
            for submission in listing_fn(limit=1000, **kwargs):
                if submission.id in posts:
                    continue
                posts[submission.id] = {
                    "id": submission.id,
                    "title": submission.title or "",
                    "selftext": getattr(submission, "selftext", "") or "",
                    "flair": submission.link_flair_text or "",
                    "created_utc": float(submission.created_utc or 0),
                    "score": int(submission.score or 0),
                }
                if len(posts) >= limit:
                    break
        except prawcore.exceptions.PrawcoreException as e:
            logger.warning("Listing '%s' failed for r/%s: %s", listing_name, name, e)
            continue

    return list(posts.values())
