from typing import Any, Optional

from pydantic import BaseModel


class SubredditFetchRequest(BaseModel):
    limit: Optional[int] = None
    force_refresh: bool = False


class RuleOut(BaseModel):
    short_name: str
    description: str
    violation_reason: str
    priority: Optional[int] = None


class SubredditInfo(BaseModel):
    name: str
    display_name: str
    subscribers: int
    over18: bool
    quarantined: bool
    status: str
    status_detail: str
    fetched_at: Optional[str] = None
    num_posts: int
    rules: list[RuleOut]
    automod_available: bool


class DraftCheckRequest(BaseModel):
    title: str = ""
    body: str = ""
    subreddits: list[str]


class HighlightSpan(BaseModel):
    text: str
    start: int
    end: int
    field: str  # "title" | "body"
    type: str  # "automod" | "oov" | "rare"
    reason: str
    rule_text: Optional[str] = None


class AutomodHitOut(BaseModel):
    matched_text: str
    field: str
    pattern: str
    action: Optional[str] = None
    context: str
    confidence: str  # "explicit" | "heuristic"


class SubredditCheckResult(BaseModel):
    subreddit: str
    status: str
    status_detail: str
    risk_score: int
    risk_level: str
    automod_available: bool
    automod_hits: list[AutomodHitOut]
    highlights: list[HighlightSpan]
    semantic_similarity: Optional[float] = None
    top_concerns: list[str]
    corpus_size: int
    corpus_fetched_at: Optional[str] = None
    rules: list[RuleOut] = []


class DraftCheckResponse(BaseModel):
    results: list[SubredditCheckResult]


class DraftSaveRequest(BaseModel):
    name: Optional[str] = None
    title: str = ""
    body: str = ""


class DraftOut(BaseModel):
    id: int
    name: Optional[str] = None
    title: str
    body: str
    created_at: str
