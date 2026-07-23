"""Smoke tests for reddit_client.py parsing logic that don't require live
Reddit credentials (network calls are mocked / not exercised here).

Run with: python -m pytest backend/tests -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reddit_client import normalize_subreddit_name, parse_automod_keywords


def test_normalize_subreddit_name():
    assert normalize_subreddit_name("r/Python") == "python"
    assert normalize_subreddit_name("/r/Python/") == "python"
    assert normalize_subreddit_name("  Python  ") == "python"
    assert normalize_subreddit_name("python") == "python"


def test_parse_automod_keywords_basic_yaml():
    raw = """
type: submission
title+body (includes, regex):
    - "buy now"
    - "discount code"
    - "\\\\bfree\\\\s+crypto\\\\b"
action: remove
action_reason: "spam keywords"
---
type: submission
domain:
    - "spam-site.com"
action: remove
"""
    items = parse_automod_keywords(raw)
    patterns = {i["pattern"] for i in items}
    assert "buy now" in patterns
    assert "discount code" in patterns
    assert "spam-site.com" in patterns
    assert all(i["kind"] == "explicit" for i in items)


def test_parse_automod_keywords_malformed_falls_back_to_heuristic():
    raw = 'this is not: valid: yaml: at: all: "sketchy phrase" more garbage "another one"'
    items = parse_automod_keywords(raw)
    patterns = {i["pattern"] for i in items}
    assert "sketchy phrase" in patterns or "another one" in patterns
    assert all(i["kind"] == "heuristic" for i in items)


def test_parse_automod_keywords_empty():
    assert parse_automod_keywords(None) == []
    assert parse_automod_keywords("") == []


def test_parse_automod_keywords_dedupes():
    raw = """
title (includes):
    - "duplicate"
    - "duplicate"
action: remove
"""
    items = parse_automod_keywords(raw)
    patterns = [i["pattern"] for i in items]
    assert patterns.count("duplicate") == 1


if __name__ == "__main__":
    test_normalize_subreddit_name()
    test_parse_automod_keywords_basic_yaml()
    test_parse_automod_keywords_malformed_falls_back_to_heuristic()
    test_parse_automod_keywords_empty()
    test_parse_automod_keywords_dedupes()
    print("All reddit_client smoke tests passed.")
