import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import prawcore
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import db, fingerprint as fp_mod, reddit_client, scoring
from .config import settings
from .schemas import (
    AutomodHitOut,
    DraftCheckRequest,
    DraftCheckResponse,
    DraftOut,
    DraftSaveRequest,
    HighlightSpan,
    RuleOut,
    SubredditCheckResult,
    SubredditFetchRequest,
    SubredditInfo,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("subfit.api")

FRESHNESS_WINDOW = timedelta(hours=24)

app = FastAPI(title="SubFit API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-process cache of built fingerprints, keyed by subreddit name and
# invalidated whenever fetched_at changes (i.e. after a refresh).
_fp_cache: dict[str, tuple[str, Optional[fp_mod.SubredditFingerprint]]] = {}


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()


def _subreddit_info_from_row(row: dict) -> SubredditInfo:
    return SubredditInfo(
        name=row["name"],
        display_name=row["display_name"] or row["name"],
        subscribers=row["subscribers"] or 0,
        over18=bool(row["over18"]),
        quarantined=bool(row["quarantined"]),
        status=row["status"],
        status_detail=row["status_detail"] or "",
        fetched_at=row["fetched_at"],
        num_posts=row["num_posts"] or 0,
        rules=[RuleOut(**r) for r in db.loads(row["rules_json"], [])],
        automod_available=bool(row["automod_available"]),
    )


def _get_fingerprint(name: str, fetched_at: str) -> Optional[fp_mod.SubredditFingerprint]:
    cached = _fp_cache.get(name)
    if cached and cached[0] == fetched_at:
        return cached[1]
    posts = db.get_posts(name)
    fp = fp_mod.build_fingerprint(posts)
    _fp_cache[name] = (fetched_at, fp)
    return fp


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "reddit_configured": settings.has_reddit_credentials}


@app.post("/subreddits/{name}/fetch", response_model=SubredditInfo)
def fetch_subreddit(name: str, req: SubredditFetchRequest = SubredditFetchRequest()) -> SubredditInfo:
    name = reddit_client.normalize_subreddit_name(name)
    limit = max(50, min(req.limit or settings.subfit_default_post_limit, settings.subfit_max_post_limit))

    existing = db.get_subreddit(name)
    if existing and not req.force_refresh and existing.get("fetched_at"):
        fetched_at = datetime.fromisoformat(existing["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < FRESHNESS_WINDOW:
            return _subreddit_info_from_row(existing)

    if not settings.has_reddit_credentials:
        raise HTTPException(
            status_code=503,
            detail="Reddit API credentials are not configured. Set REDDIT_CLIENT_ID "
            "and REDDIT_CLIENT_SECRET in your .env file (see README.md) and restart the backend.",
        )

    now = datetime.now(timezone.utc).isoformat()
    meta = reddit_client.fetch_subreddit_meta(name)

    if meta.status != "ok":
        info = {
            "name": name,
            "display_name": meta.display_name or name,
            "subscribers": meta.subscribers,
            "over18": int(meta.over18),
            "quarantined": int(meta.quarantined),
            "status": meta.status,
            "status_detail": meta.status_detail,
            "fetched_at": now,
            "num_posts": 0,
            "rules_json": db.dumps([]),
            "automod_available": 0,
            "automod_raw": None,
            "automod_keywords_json": db.dumps([]),
        }
        db.upsert_subreddit(info)
        db.replace_posts(name, [])
        _fp_cache.pop(name, None)
        return _subreddit_info_from_row(db.get_subreddit(name))

    try:
        rules = reddit_client.fetch_rules(name)
        automod_raw = reddit_client.fetch_automod_raw(name)
        keywords = reddit_client.parse_automod_keywords(automod_raw)
        posts = reddit_client.fetch_posts(name, limit)

        texts = [f"{p['title']} {p['selftext']}".strip() for p in posts]
        try:
            embeddings = fp_mod.embed_texts(texts)
            for i, p in enumerate(posts):
                p["embedding"] = fp_mod.embedding_to_blob(embeddings[i])
        except Exception:
            logger.warning(
                "Embedding model unavailable; caching corpus without semantic "
                "embeddings (vocabulary/AutoModerator checks are unaffected).",
                exc_info=True,
            )
            for p in posts:
                p["embedding"] = None
    except prawcore.exceptions.PrawcoreException as e:
        logger.exception("Fetch failed for r/%s", name)
        info = {
            "name": name,
            "display_name": meta.display_name or name,
            "subscribers": meta.subscribers,
            "over18": int(meta.over18),
            "quarantined": int(meta.quarantined),
            "status": "error",
            "status_detail": f"Reddit API error while fetching posts/rules: {e}",
            "fetched_at": now,
            "num_posts": 0,
            "rules_json": db.dumps([]),
            "automod_available": 0,
            "automod_raw": None,
            "automod_keywords_json": db.dumps([]),
        }
        db.upsert_subreddit(info)
        db.replace_posts(name, [])
        _fp_cache.pop(name, None)
        return _subreddit_info_from_row(db.get_subreddit(name))

    info = {
        "name": name,
        "display_name": meta.display_name or name,
        "subscribers": meta.subscribers,
        "over18": int(meta.over18),
        "quarantined": int(meta.quarantined),
        "status": "ok",
        "status_detail": "" if posts else "Fetched successfully but no posts were found (empty corpus).",
        "fetched_at": now,
        "num_posts": len(posts),
        "rules_json": db.dumps(rules),
        "automod_available": int(bool(automod_raw)),
        "automod_raw": automod_raw,
        "automod_keywords_json": db.dumps(keywords),
    }
    db.upsert_subreddit(info)
    db.replace_posts(name, posts)
    _fp_cache.pop(name, None)
    return _subreddit_info_from_row(db.get_subreddit(name))


@app.get("/subreddits", response_model=list[SubredditInfo])
def list_subreddits() -> list[SubredditInfo]:
    return [_subreddit_info_from_row(r) for r in db.list_subreddits()]


@app.get("/subreddits/{name}", response_model=SubredditInfo)
def get_subreddit(name: str) -> SubredditInfo:
    name = reddit_client.normalize_subreddit_name(name)
    row = db.get_subreddit(name)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Subreddit not cached yet. POST /subreddits/{name}/fetch first.",
        )
    return _subreddit_info_from_row(row)


@app.post("/check", response_model=DraftCheckResponse)
def check_draft(req: DraftCheckRequest) -> DraftCheckResponse:
    results: list[SubredditCheckResult] = []

    for raw_name in req.subreddits:
        name = reddit_client.normalize_subreddit_name(raw_name)
        row = db.get_subreddit(name)

        if not row:
            results.append(
                SubredditCheckResult(
                    subreddit=name,
                    status="not_fetched",
                    status_detail="No cached corpus for this subreddit yet. Fetch it first in Subreddit Setup.",
                    risk_score=0,
                    risk_level="unknown",
                    automod_available=False,
                    automod_hits=[],
                    highlights=[],
                    semantic_similarity=None,
                    top_concerns=["Corpus not fetched yet — fetch this subreddit before checking."],
                    corpus_size=0,
                    corpus_fetched_at=None,
                    rules=[],
                )
            )
            continue

        if row["status"] != "ok":
            results.append(
                SubredditCheckResult(
                    subreddit=name,
                    status=row["status"],
                    status_detail=row["status_detail"] or "",
                    risk_score=0,
                    risk_level="unknown",
                    automod_available=False,
                    automod_hits=[],
                    highlights=[],
                    semantic_similarity=None,
                    top_concerns=[row["status_detail"] or "Subreddit is inaccessible."],
                    corpus_size=0,
                    corpus_fetched_at=row["fetched_at"],
                    rules=[],
                )
            )
            continue

        posts = db.get_posts(name)
        fp = _get_fingerprint(name, row["fetched_at"])
        keywords = db.loads(row["automod_keywords_json"], [])
        rules = db.loads(row["rules_json"], [])
        automod_available = bool(row["automod_available"])

        outcome = scoring.check_draft(req.title, req.body, keywords, fp)

        status_detail = (
            ""
            if automod_available
            else "No AutoModerator keyword config is publicly available for this sub — "
            "showing vocabulary-fit analysis only."
        )

        results.append(
            SubredditCheckResult(
                subreddit=name,
                status="ok",
                status_detail=status_detail,
                risk_score=outcome["risk_score"],
                risk_level=outcome["risk_level"],
                automod_available=automod_available,
                automod_hits=[
                    AutomodHitOut(
                        matched_text=h.matched_text,
                        field=h.field,
                        pattern=h.pattern,
                        action=h.action,
                        context=h.context,
                        confidence=h.confidence,
                    )
                    for h in outcome["automod_hits"]
                ],
                highlights=[HighlightSpan(**h) for h in outcome["highlights"]],
                semantic_similarity=outcome["semantic_similarity"],
                top_concerns=outcome["top_concerns"],
                corpus_size=len(posts),
                corpus_fetched_at=row["fetched_at"],
                rules=[RuleOut(**r) for r in rules],
            )
        )

    return DraftCheckResponse(results=results)


@app.post("/drafts", response_model=DraftOut)
def create_draft(req: DraftSaveRequest) -> DraftOut:
    draft_id = db.save_draft(req.title, req.body, req.name)
    row = next(d for d in db.list_drafts() if d["id"] == draft_id)
    return DraftOut(**row)


@app.get("/drafts", response_model=list[DraftOut])
def get_drafts() -> list[DraftOut]:
    return [DraftOut(**d) for d in db.list_drafts()]


@app.delete("/drafts/{draft_id}", status_code=204)
def remove_draft(draft_id: int) -> None:
    db.delete_draft(draft_id)
    return None
