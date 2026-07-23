import { getPosts, getSubredditInternal, initDb } from "@/lib/db";
import { getOrBuildFingerprint } from "@/lib/fingerprintCache";
import { embedOne } from "@/lib/embeddings";
import { normalizeSubredditName } from "@/lib/reddit";
import { checkDraft } from "@/lib/scoring";
import type { AutomodKeyword, RedditRule, SubredditCheckResult, SubredditStatus } from "@/lib/types";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function POST(req: Request) {
  await initDb();
  const body = await req.json().catch(() => null);
  if (!body || !Array.isArray(body.subreddits)) {
    return Response.json({ detail: "Body must include a 'subreddits' array." }, { status: 400 });
  }

  const title = (body.title as string) || "";
  const draftBody = (body.body as string) || "";
  const subreddits = body.subreddits as string[];

  const draftEmbedding = await embedOne(`${title} ${draftBody}`.trim());

  const results: SubredditCheckResult[] = [];

  for (const rawName of subreddits) {
    const name = normalizeSubredditName(rawName);
    const row = await getSubredditInternal(name);

    if (!row) {
      results.push({
        subreddit: name,
        status: "not_fetched",
        status_detail: "No cached corpus for this subreddit yet. Fetch it first in Subreddit Setup.",
        risk_score: 0,
        risk_level: "unknown",
        automod_available: false,
        automod_hits: [],
        highlights: [],
        semantic_similarity: null,
        top_concerns: ["Corpus not fetched yet — fetch this subreddit before checking."],
        corpus_size: 0,
        corpus_fetched_at: null,
        rules: [],
      });
      continue;
    }

    const status = row.status as SubredditStatus;
    if (status !== "ok") {
      results.push({
        subreddit: name,
        status,
        status_detail: (row.status_detail as string) || "",
        risk_score: 0,
        risk_level: "unknown",
        automod_available: false,
        automod_hits: [],
        highlights: [],
        semantic_similarity: null,
        top_concerns: [(row.status_detail as string) || "Subreddit is inaccessible."],
        corpus_size: 0,
        corpus_fetched_at: row.fetched_at ? new Date(row.fetched_at as string).toISOString() : null,
        rules: [],
      });
      continue;
    }

    const fetchedAt = row.fetched_at ? new Date(row.fetched_at as string).toISOString() : null;
    const posts = await getPosts(name);
    const fp = await getOrBuildFingerprint(name, fetchedAt);
    const keywords = (row.automod_keywords_json as AutomodKeyword[]) || [];
    const rules = (row.rules_json as RedditRule[]) || [];
    const automodAvailable = Boolean(row.automod_available);

    const outcome = checkDraft(title, draftBody, keywords, fp, draftEmbedding);

    results.push({
      subreddit: name,
      status: "ok",
      status_detail: automodAvailable
        ? ""
        : "No AutoModerator keyword config is publicly available for this sub — showing vocabulary-fit analysis only.",
      risk_score: outcome.riskScore,
      risk_level: outcome.riskLevel,
      automod_available: automodAvailable,
      automod_hits: outcome.automodHits.map((h) => ({
        matched_text: h.matchedText,
        field: h.field,
        pattern: h.pattern,
        action: h.action,
        context: h.context,
        confidence: h.confidence,
      })),
      highlights: outcome.highlights,
      semantic_similarity: outcome.semanticSimilarity,
      top_concerns: outcome.topConcerns,
      corpus_size: posts.length,
      corpus_fetched_at: fetchedAt,
      rules,
    });
  }

  return Response.json({ results });
}
