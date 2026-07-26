/**
 * Read-only Reddit access via plain fetch(). Never posts, comments, votes,
 * or otherwise writes to Reddit.
 *
 * Two modes, chosen automatically:
 *  - Authenticated: if REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET are set, uses
 *    OAuth2 client_credentials (the "application only" flow a script app
 *    uses for read-only access, equivalent to PRAW's read_only=True) against
 *    oauth.reddit.com. Higher rate limits.
 *  - Anonymous fallback: if no credentials are configured, falls back to
 *    Reddit's public, unauthenticated `.json` endpoints on www.reddit.com.
 *    No Reddit app/registration needed at all -- lower rate limits, but
 *    enough for personal use and testing. This is what makes the app work
 *    out of the box before you've gone through Reddit's app-creation flow.
 */
import type { AutomodKeyword, RedditRule, SubredditStatus } from "./types";

const TOKEN_URL = "https://www.reddit.com/api/v1/access_token";
const OAUTH_BASE = "https://oauth.reddit.com";
const PUBLIC_BASE = "https://www.reddit.com";

interface CachedToken {
  accessToken: string;
  expiresAt: number; // epoch ms
}

const globalForToken = globalThis as unknown as { subfitRedditToken?: CachedToken };

function hasCredentials(): boolean {
  return Boolean(process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET);
}

function getUserAgent(): string {
  return process.env.REDDIT_USER_AGENT || "subfit:draft-checker:v1.0 (anonymous public access)";
}

async function getAccessToken(): Promise<string | null> {
  if (!hasCredentials()) return null;

  const cached = globalForToken.subfitRedditToken;
  if (cached && cached.expiresAt > Date.now() + 10_000) {
    return cached.accessToken;
  }

  const clientId = process.env.REDDIT_CLIENT_ID!;
  const clientSecret = process.env.REDDIT_CLIENT_SECRET!;
  const basic = Buffer.from(`${clientId}:${clientSecret}`).toString("base64");
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": getUserAgent(),
    },
    body: "grant_type=client_credentials",
  });
  if (!res.ok) {
    // Credentials are present but rejected/expired -- fall back to anonymous
    // access rather than hard-failing every request.
    return null;
  }
  const data = (await res.json()) as { access_token: string; expires_in: number };
  globalForToken.subfitRedditToken = {
    accessToken: data.access_token,
    expiresAt: Date.now() + data.expires_in * 1000,
  };
  return data.access_token;
}

class RedditHttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function redditGet(path: string): Promise<unknown> {
  const userAgent = getUserAgent();
  const token = await getAccessToken();
  const base = token ? OAUTH_BASE : PUBLIC_BASE;
  const headers: Record<string, string> = { "User-Agent": userAgent };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${base}${path}`, { headers });
  if (!res.ok) {
    throw new RedditHttpError(res.status, await res.text().catch(() => res.statusText));
  }
  return res.json();
}

export function normalizeSubredditName(name: string): string {
  return name.trim().replace(/^\/?r\//i, "").replace(/^\/+|\/+$/g, "").toLowerCase();
}

export interface SubredditMeta {
  name: string;
  display_name: string;
  subscribers: number;
  over18: boolean;
  quarantined: boolean;
  status: SubredditStatus;
  status_detail: string;
}

export async function fetchSubredditMeta(rawName: string): Promise<SubredditMeta> {
  const name = normalizeSubredditName(rawName);
  try {
    const json = (await redditGet(`/r/${encodeURIComponent(name)}/about.json`)) as {
      data?: {
        display_name?: string;
        subscribers?: number;
        over18?: boolean;
        quarantine?: boolean;
      };
    };
    const data = json.data || {};
    if (data.quarantine) {
      return {
        name,
        display_name: data.display_name || name,
        subscribers: 0,
        over18: false,
        quarantined: true,
        status: "quarantined",
        status_detail:
          "This subreddit is quarantined. SubFit does not auto opt-in to quarantined " +
          "subreddits, so its posts/rules cannot be fetched.",
      };
    }
    return {
      name,
      display_name: data.display_name || name,
      subscribers: data.subscribers || 0,
      over18: Boolean(data.over18),
      quarantined: false,
      status: "ok",
      status_detail: "",
    };
  } catch (e) {
    if (e instanceof RedditHttpError) {
      if (e.status === 403) {
        return {
          name,
          display_name: name,
          subscribers: 0,
          over18: false,
          quarantined: false,
          status: "private",
          status_detail:
            "Subreddit is private, quarantined, or otherwise forbidden. " +
            `(Reddit response: ${e.message.slice(0, 300)})`,
        };
      }
      if (e.status === 404) {
        return {
          name,
          display_name: name,
          subscribers: 0,
          over18: false,
          quarantined: false,
          status: "not_found",
          status_detail: "Subreddit does not exist (or was banned).",
        };
      }
      return {
        name,
        display_name: name,
        subscribers: 0,
        over18: false,
        quarantined: false,
        status: "error",
        status_detail: `Reddit API error: ${e.status} ${e.message}`,
      };
    }
    throw e;
  }
}

export async function fetchRules(rawName: string): Promise<RedditRule[]> {
  const name = normalizeSubredditName(rawName);
  try {
    const json = (await redditGet(`/r/${encodeURIComponent(name)}/about/rules.json`)) as {
      rules?: Array<{
        short_name?: string;
        description?: string;
        violation_reason?: string;
        priority?: number;
      }>;
    };
    return (json.rules || []).map((r) => ({
      short_name: r.short_name || "",
      description: r.description || "",
      violation_reason: r.violation_reason || "",
      priority: typeof r.priority === "number" ? r.priority : null,
    }));
  } catch {
    return [];
  }
}

const AUTOMOD_WIKI_PAGES = ["config/automoderator", "automoderator"];

export async function fetchAutomodRaw(rawName: string): Promise<string | null> {
  const name = normalizeSubredditName(rawName);
  for (const page of AUTOMOD_WIKI_PAGES) {
    try {
      const json = (await redditGet(`/r/${encodeURIComponent(name)}/wiki/${page}.json`)) as {
        data?: { content_md?: string };
      };
      const content = json.data?.content_md;
      if (content && content.trim()) return content;
    } catch {
      continue;
    }
  }
  return null;
}

const TRIGGER_KEY_RE =
  /^(title|body|title\+body|selftext|flair_text|flair_css_class|author_flair_text|author_text|domain|url|link_flair_text|full_text)\b/i;

function collectStrings(value: unknown, field: string, out: AutomodKeyword[], action: string | null, context: string) {
  if (typeof value === "string") {
    if (value.length >= 2 && value.length <= 200) {
      out.push({ pattern: value, field, action, context, kind: "explicit" });
    }
  } else if (Array.isArray(value)) {
    for (const item of value) {
      if (typeof item === "string") {
        if (item.length >= 2 && item.length <= 200) {
          out.push({ pattern: item, field, action, context, kind: "explicit" });
        }
      } else if (item && typeof item === "object") {
        walkYaml(item as Record<string, unknown>, out, action, context);
      }
    }
  } else if (value && typeof value === "object") {
    walkYaml(value as Record<string, unknown>, out, action, context);
  }
}

function walkYaml(node: unknown, out: AutomodKeyword[], action: string | null, context: string) {
  if (Array.isArray(node)) {
    for (const item of node) walkYaml(item, out, action, context);
    return;
  }
  if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (TRIGGER_KEY_RE.test(key.trim())) {
        collectStrings(value, key, out, action, context);
      } else {
        walkYaml(value, out, action, context);
      }
    }
  }
}

export async function parseAutomodKeywords(rawText: string | null): Promise<AutomodKeyword[]> {
  if (!rawText) return [];
  const { parse } = await import("yaml");

  const out: AutomodKeyword[] = [];
  let parsedAny = false;
  const docTexts = rawText.split(/^\s*---\s*$/m);

  for (const docText of docTexts) {
    if (!docText.trim()) continue;
    let doc: unknown;
    try {
      doc = parse(docText);
    } catch {
      continue;
    }
    if (!doc || typeof doc !== "object" || Array.isArray(doc)) continue;
    parsedAny = true;

    const action = ((doc as Record<string, unknown>).action as string) ?? null;
    let context = docText.trim();
    if (context.length > 400) context = context.slice(0, 400) + "...";

    walkYaml(doc, out, action, context);
  }

  if (!parsedAny) {
    const re = /["']([^"']{3,60})["']/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(rawText)) !== null) {
      out.push({
        pattern: m[1],
        field: "unknown",
        action: null,
        context: "Extracted heuristically; AutoMod config was not valid YAML.",
        kind: "heuristic",
      });
    }
  }

  const seen = new Set<string>();
  const deduped: AutomodKeyword[] = [];
  for (const item of out) {
    const key = `${item.pattern.trim().toLowerCase()}|${item.field}`;
    if (seen.has(key) || !item.pattern.trim()) continue;
    seen.add(key);
    deduped.push(item);
  }
  return deduped;
}

export interface RawPost {
  id: string;
  title: string;
  selftext: string;
  flair: string;
  created_utc: number;
  score: number;
}

export interface ListingSpec {
  listing: "new" | "hot" | "rising" | "top";
  timeFilter?: "year" | "all";
}

export const POST_LISTINGS: ListingSpec[] = [
  { listing: "new" },
  { listing: "hot" },
  { listing: "rising" },
  { listing: "top", timeFilter: "year" },
  { listing: "top", timeFilter: "all" },
];

export interface ListingPage {
  posts: RawPost[];
  after: string | null;
}

export async function fetchListingPage(
  rawName: string,
  spec: ListingSpec,
  after: string | null
): Promise<ListingPage> {
  const name = normalizeSubredditName(rawName);
  const params = new URLSearchParams({ limit: "100" });
  if (after) params.set("after", after);
  if (spec.listing === "top" && spec.timeFilter) params.set("t", spec.timeFilter);

  try {
    const json = (await redditGet(`/r/${encodeURIComponent(name)}/${spec.listing}.json?${params}`)) as {
      data?: { children?: Array<{ data: Record<string, unknown> }>; after?: string | null };
    };
    const children = json.data?.children || [];
    const posts: RawPost[] = children.map((c) => ({
      id: String(c.data.id),
      title: (c.data.title as string) || "",
      selftext: (c.data.selftext as string) || "",
      flair: (c.data.link_flair_text as string) || "",
      created_utc: Number(c.data.created_utc) || 0,
      score: Number(c.data.score) || 0,
    }));
    return { posts, after: json.data?.after ?? null };
  } catch {
    return { posts: [], after: null };
  }
}
