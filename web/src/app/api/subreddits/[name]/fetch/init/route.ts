import { v4 as uuidv4 } from "uuid";
import {
  createFetchJob,
  deletePostsForSubreddit,
  initDb,
  upsertSubreddit,
} from "@/lib/db";
import { invalidateFingerprint } from "@/lib/fingerprintCache";
import {
  fetchAutomodRaw,
  fetchRules,
  fetchSubredditMeta,
  normalizeSubredditName,
  parseAutomodKeywords,
  RedditNotConfigured,
} from "@/lib/reddit";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const DEFAULT_LIMIT = 3000;
const MAX_LIMIT = 5000;
const MIN_LIMIT = 50;

export async function POST(req: Request, ctx: RouteContext<"/api/subreddits/[name]/fetch/init">) {
  await initDb();
  const { name: rawName } = await ctx.params;
  const name = normalizeSubredditName(rawName);

  let limit = DEFAULT_LIMIT;
  try {
    const body = await req.json();
    if (typeof body?.limit === "number") limit = body.limit;
  } catch {
    // no body / invalid JSON: use default
  }
  limit = Math.max(MIN_LIMIT, Math.min(limit, MAX_LIMIT));

  let meta;
  try {
    meta = await fetchSubredditMeta(name);
  } catch (e) {
    if (e instanceof RedditNotConfigured) {
      return Response.json({ detail: e.message }, { status: 503 });
    }
    return Response.json(
      { detail: `Reddit API error: ${e instanceof Error ? e.message : String(e)}` },
      { status: 502 }
    );
  }

  const now = new Date().toISOString();

  if (meta.status !== "ok") {
    await upsertSubreddit({
      name,
      display_name: meta.display_name,
      subscribers: meta.subscribers,
      over18: meta.over18,
      quarantined: meta.quarantined,
      status: meta.status,
      status_detail: meta.status_detail,
      fetched_at: now,
      num_posts: 0,
      rules: [],
      automod_available: false,
      automod_raw: null,
      automod_keywords: [],
    });
    await deletePostsForSubreddit(name);
    invalidateFingerprint(name);
    return Response.json({ jobId: null, status: meta.status, statusDetail: meta.status_detail });
  }

  const [rules, automodRaw] = await Promise.all([fetchRules(name), fetchAutomodRaw(name)]);
  const keywords = await parseAutomodKeywords(automodRaw);

  await upsertSubreddit({
    name,
    display_name: meta.display_name,
    subscribers: meta.subscribers,
    over18: meta.over18,
    quarantined: meta.quarantined,
    status: "fetching",
    status_detail: "Fetching posts from Reddit…",
    fetched_at: null,
    num_posts: 0,
    rules,
    automod_available: Boolean(automodRaw),
    automod_raw: automodRaw,
    automod_keywords: keywords,
  });
  await deletePostsForSubreddit(name);
  invalidateFingerprint(name);

  const jobId = uuidv4();
  await createFetchJob(jobId, name, limit);

  return Response.json({ jobId, status: "fetching", target: limit });
}
