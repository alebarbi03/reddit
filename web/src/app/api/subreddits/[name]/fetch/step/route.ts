import {
  countPosts,
  getFetchJob,
  initDb,
  insertPosts,
  updateFetchJob,
  upsertSubreddit,
  deleteFetchJob,
  getSubredditInternal,
} from "@/lib/db";
import { invalidateFingerprint } from "@/lib/fingerprintCache";
import { embedTexts } from "@/lib/embeddings";
import { runFetchStep } from "@/lib/fetchJobRunner";
import { fetchListingPage, normalizeSubredditName, POST_LISTINGS } from "@/lib/reddit";
import type { AutomodKeyword, PostRow, RedditRule } from "@/lib/types";

export const dynamic = "force-dynamic";
export const maxDuration = 55;

// How many Reddit listing pages (up to 100 posts each) to pull per step call,
// so each serverless invocation stays comfortably under typical platform
// timeouts (including Vercel's Hobby-tier default). The client polls this
// endpoint repeatedly until { done: true }.
const PAGES_PER_STEP = 3;

export async function POST(_req: Request, ctx: RouteContext<"/api/subreddits/[name]/fetch/step">) {
  await initDb();
  const { name: rawName } = await ctx.params;
  const name = normalizeSubredditName(rawName);

  const body = await _req.json().catch(() => ({}));
  const jobId = body?.jobId as string | undefined;
  if (!jobId) return Response.json({ detail: "jobId is required" }, { status: 400 });

  const job = await getFetchJob(jobId);
  if (!job) return Response.json({ detail: "Fetch job not found (may have already finished)." }, { status: 404 });

  if (job.status !== "running") {
    const count = await countPosts(name);
    return Response.json({ done: true, fetched: count, target: job.target_limit });
  }

  const result = await runFetchStep(
    { listingIndex: job.listing_index, listingAfter: job.listing_after },
    job.target_limit,
    {
      listings: POST_LISTINGS,
      fetchPage: (spec, after) => fetchListingPage(name, spec, after),
      embed: embedTexts,
      insertPosts: async (rows) => {
        const postRows: PostRow[] = rows.map((r) => ({
          id: r.id,
          subreddit: name,
          title: r.title,
          selftext: r.selftext,
          flair: r.flair,
          created_utc: r.created_utc,
          score: r.score,
          embedding: r.embedding,
        }));
        await insertPosts(name, postRows);
      },
      getCount: () => countPosts(name),
      maxPagesPerStep: PAGES_PER_STEP,
    }
  );

  if (result.done) {
    const internal = await getSubredditInternal(name);
    await upsertSubreddit({
      name,
      display_name: (internal?.display_name as string) || name,
      subscribers: (internal?.subscribers as number) || 0,
      over18: Boolean(internal?.over18),
      quarantined: Boolean(internal?.quarantined),
      status: "ok",
      status_detail: result.fetchedCount > 0 ? "" : "Fetched successfully but no posts were found (empty corpus).",
      fetched_at: new Date().toISOString(),
      num_posts: result.fetchedCount,
      rules: (internal?.rules_json as RedditRule[]) || [],
      automod_available: Boolean(internal?.automod_available),
      automod_raw: (internal?.automod_raw as string) || null,
      automod_keywords: (internal?.automod_keywords_json as AutomodKeyword[]) || [],
    });
    invalidateFingerprint(name);
    await deleteFetchJob(jobId);
    return Response.json({ done: true, fetched: result.fetchedCount, target: job.target_limit });
  }

  await updateFetchJob(jobId, {
    listing_index: result.listingIndex,
    listing_after: result.listingAfter,
    fetched_count: result.fetchedCount,
  });
  return Response.json({
    done: false,
    fetched: result.fetchedCount,
    target: job.target_limit,
    listingIndex: result.listingIndex,
  });
}
