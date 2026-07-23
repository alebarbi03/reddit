import { buildFingerprint, type SubredditFingerprint } from "./fingerprint";
import { getPosts } from "./db";

// In-process cache of built fingerprints, keyed by subreddit name and
// invalidated whenever fetched_at changes (i.e. after a refresh). Best-effort:
// helps on warm serverless invocations, rebuilt from scratch on cold starts.
const globalForCache = globalThis as unknown as {
  subfitFpCache?: Map<string, { fetchedAt: string | null; fp: SubredditFingerprint | null }>;
};
const cache = globalForCache.subfitFpCache ?? new Map();
globalForCache.subfitFpCache = cache;

export async function getOrBuildFingerprint(
  name: string,
  fetchedAt: string | null
): Promise<SubredditFingerprint | null> {
  const cached = cache.get(name);
  if (cached && cached.fetchedAt === fetchedAt) return cached.fp;
  const posts = await getPosts(name);
  const fp = buildFingerprint(posts);
  cache.set(name, { fetchedAt, fp });
  return fp;
}

export function invalidateFingerprint(name: string): void {
  cache.delete(name);
}
