"""Fetches the Funding Explorer.

Three strategies, tried in order of fidelity:

1. Playwright renders the page and we record every JSON response it fetches.
   An SPA has to get its data from somewhere, so listening to its own network
   traffic finds the rounds feed without us knowing the endpoint in advance.
2. Plain HTTP GET, scanning the returned HTML for embedded JSON (works when
   the page is server-rendered and avoids the browser dependency entirely).
3. The tech.eu RSS feed (see rss.py), used as a backstop by the caller.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import settings
from .extract import best_rounds, rounds_from_html
from .models import Round

logger = logging.getLogger("fundingagent.fetch")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Third-party noise we never want to parse or store.
_IGNORE_HOSTS = re.compile(
    r"(google-analytics|googletagmanager|doubleclick|hotjar|segment|sentry|"
    r"intercom|facebook|linkedin\.com|clarity\.ms|posthog|cookiebot)",
    re.IGNORECASE,
)


@dataclass
class Capture:
    """What one page visit produced."""

    url: str
    html: str = ""
    payloads: list[tuple[str, Any]] = field(default_factory=list)
    error: str = ""

    def summary(self) -> list[str]:
        lines = [f"page: {self.url}", f"html bytes: {len(self.html)}"]
        for endpoint, payload in self.payloads:
            lines.append(f"  json <- {endpoint} ({_shape(payload)})")
        if self.error:
            lines.append(f"  error: {self.error}")
        return lines


def _shape(payload: Any, depth: int = 0) -> str:
    if depth > 2:
        return "..."
    if isinstance(payload, list):
        return f"list[{len(payload)}] of {_shape(payload[0], depth + 1) if payload else 'empty'}"
    if isinstance(payload, dict):
        keys = list(payload.keys())[:8]
        return "{" + ", ".join(str(k) for k in keys) + ("..." if len(payload) > 8 else "") + "}"
    return type(payload).__name__


def capture_with_browser(url: str) -> Capture:
    """Renders `url` and records the JSON it fetches."""
    capture = Capture(url=url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        capture.error = "playwright not installed"
        return capture

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.headless)
            context = browser.new_context(user_agent=USER_AGENT, locale="en-GB")
            page = context.new_page()

            def on_response(response) -> None:
                try:
                    if response.status != 200 or _IGNORE_HOSTS.search(response.url):
                        return
                    ctype = (response.header_value("content-type") or "").lower()
                    if "json" not in ctype:
                        return
                    body = response.json()
                    if isinstance(body, (dict, list)) and body:
                        capture.payloads.append((response.url, body))
                except Exception:  # noqa: BLE001 - a bad response must not kill the run
                    return

            page.on("response", on_response)
            page.goto(url, timeout=settings.page_timeout_ms, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=settings.settle_ms)
            except Exception:  # noqa: BLE001 - networkidle is a nicety, not a requirement
                pass

            # Nudge lazy-loaded tables/infinite scroll into fetching more rows.
            for _ in range(max(0, settings.scroll_passes)):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(600)
            page.wait_for_timeout(settings.settle_ms)

            capture.html = page.content()
            context.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a fallback signal
        capture.error = f"{type(exc).__name__}: {exc}"
    return capture


def capture_with_http(url: str) -> Capture:
    """Plain GET, for server-rendered pages or when Playwright is unavailable."""
    capture = Capture(url=url)
    try:
        import requests

        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"},
            timeout=30,
        )
        response.raise_for_status()
        ctype = response.headers.get("content-type", "").lower()
        if "json" in ctype:
            capture.payloads.append((url, response.json()))
        else:
            capture.html = response.text
    except Exception as exc:  # noqa: BLE001
        capture.error = f"{type(exc).__name__}: {exc}"
    return capture


def rounds_from_capture(capture: Capture) -> list[Round]:
    """Best rounds found across a capture's XHR payloads and page HTML."""
    base = _origin(capture.url)
    found: list[Round] = []
    for endpoint, payload in capture.payloads:
        rounds = best_rounds(payload, base)
        if len(rounds) > len(found):
            logger.info("matched %d rounds from %s", len(rounds), endpoint)
            found = rounds
    if capture.html:
        from_html = rounds_from_html(capture.html, base)
        if len(from_html) > len(found):
            logger.info("matched %d rounds from embedded page JSON", len(from_html))
            found = from_html
    return found


def fetch_explorer(use_browser: bool = True) -> tuple[list[Round], list[Capture]]:
    """Tries each configured Explorer URL until one yields rounds."""
    captures: list[Capture] = []
    for url in settings.explorer_candidates():
        capture = capture_with_browser(url) if use_browser else capture_with_http(url)
        if capture.error and use_browser and "playwright" in capture.error:
            logger.warning("%s - falling back to plain HTTP", capture.error)
            capture = capture_with_http(url)
        captures.append(capture)

        rounds = rounds_from_capture(capture)
        if rounds:
            return rounds, captures
        logger.info("no rounds found at %s", url)
    return [], captures


def _origin(url: str) -> str:
    match = re.match(r"(https?://[^/]+)", url or "")
    return match.group(1) if match else ""


def dump_capture(capture: Capture, directory) -> list[str]:
    """Writes a capture to disk so an unrecognised payload can be inspected."""
    from pathlib import Path

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    stem = re.sub(r"[^a-z0-9]+", "-", capture.url.lower()).strip("-")[:60] or "page"

    if capture.html:
        path = directory / f"{stem}.html"
        path.write_text(capture.html, encoding="utf-8")
        written.append(str(path))
    for i, (endpoint, payload) in enumerate(capture.payloads, start=1):
        path = directory / f"{stem}-xhr-{i}.json"
        path.write_text(
            json.dumps({"endpoint": endpoint, "payload": payload}, indent=2, ensure_ascii=False)[:5_000_000],
            encoding="utf-8",
        )
        written.append(str(path))
    return written
