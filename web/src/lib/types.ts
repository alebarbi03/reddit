export type SubredditStatus =
  | "ok"
  | "fetching"
  | "private"
  | "banned"
  | "not_found"
  | "quarantined"
  | "error";

export interface RedditRule {
  short_name: string;
  description: string;
  violation_reason: string;
  priority: number | null;
}

export interface AutomodKeyword {
  pattern: string;
  field: string;
  action: string | null;
  context: string;
  kind: "explicit" | "heuristic";
}

export interface SubredditRow {
  name: string;
  display_name: string;
  subscribers: number;
  over18: boolean;
  quarantined: boolean;
  status: SubredditStatus;
  status_detail: string;
  fetched_at: string | null;
  num_posts: number;
  rules: RedditRule[];
  automod_available: boolean;
}

export interface PostRow {
  id: string;
  subreddit: string;
  title: string;
  selftext: string;
  flair: string;
  created_utc: number;
  score: number;
  embedding: number[] | null;
}

export interface DraftRow {
  id: number;
  name: string | null;
  title: string;
  body: string;
  created_at: string;
}

export type FetchJobStatus = "running" | "done" | "error";

export interface FetchJobRow {
  id: string;
  subreddit: string;
  target_limit: number;
  status: FetchJobStatus;
  status_detail: string | null;
  listing_index: number;
  listing_after: string | null;
  fetched_count: number;
  created_at: string;
  updated_at: string;
}

export interface HighlightSpan {
  text: string;
  start: number;
  end: number;
  field: "title" | "body";
  type: "automod" | "oov" | "rare";
  reason: string;
  rule_text: string | null;
}

export interface AutomodHitOut {
  matched_text: string;
  field: string;
  pattern: string;
  action: string | null;
  context: string;
  confidence: "explicit" | "heuristic";
}

export type RiskLevel = "low" | "medium" | "high" | "unknown";

export interface SubredditCheckResult {
  subreddit: string;
  status: SubredditStatus | "not_fetched";
  status_detail: string;
  risk_score: number;
  risk_level: RiskLevel;
  automod_available: boolean;
  automod_hits: AutomodHitOut[];
  highlights: HighlightSpan[];
  semantic_similarity: number | null;
  top_concerns: string[];
  corpus_size: number;
  corpus_fetched_at: string | null;
  rules: RedditRule[];
}
