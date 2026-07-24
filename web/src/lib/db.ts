import { Pool } from "pg";
import type {
  AutomodKeyword,
  DraftRow,
  FetchJobRow,
  FetchJobStatus,
  PostRow,
  RedditRule,
  SubredditRow,
  SubredditStatus,
} from "./types";

// A single pooled connection per server process (reused across warm serverless
// invocations); Postgres needs SSL for most hosted providers (Neon/Vercel Postgres).
//
// The connection string is validated lazily (on first actual query), not at
// module load time: Next.js imports route modules during the build's "collect
// page data" step, and an eager throw here would fail the entire build if
// DATABASE_URL isn't set yet at build time, even though it only needs to be
// set at runtime.
const globalForPg = globalThis as unknown as { pgPool?: Pool };

function createPool(): Pool {
  const connectionString = process.env.DATABASE_URL || process.env.POSTGRES_URL;
  if (!connectionString) {
    throw new Error(
      "DATABASE_URL (or POSTGRES_URL) is not set. Provision a Postgres database " +
        "(e.g. Vercel Postgres / Neon) and set the connection string in your env vars."
    );
  }
  return new Pool({
    connectionString,
    ssl: connectionString.includes("localhost") || connectionString.includes("127.0.0.1")
      ? false
      : { rejectUnauthorized: false },
    max: 5,
  });
}

function getPool(): Pool {
  if (!globalForPg.pgPool) {
    globalForPg.pgPool = createPool();
  }
  return globalForPg.pgPool;
}

export const pool = new Proxy({} as Pool, {
  get(_target, prop) {
    const real = getPool();
    const value = Reflect.get(real, prop, real);
    return typeof value === "function" ? value.bind(real) : value;
  },
});

const SCHEMA = `
CREATE TABLE IF NOT EXISTS subreddits (
  name TEXT PRIMARY KEY,
  display_name TEXT,
  subscribers INTEGER DEFAULT 0,
  over18 BOOLEAN DEFAULT FALSE,
  quarantined BOOLEAN DEFAULT FALSE,
  status TEXT NOT NULL,
  status_detail TEXT,
  fetched_at TIMESTAMPTZ,
  num_posts INTEGER DEFAULT 0,
  rules_json JSONB DEFAULT '[]',
  automod_available BOOLEAN DEFAULT FALSE,
  automod_raw TEXT,
  automod_keywords_json JSONB DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS posts (
  id TEXT NOT NULL,
  subreddit TEXT NOT NULL REFERENCES subreddits(name) ON DELETE CASCADE,
  title TEXT DEFAULT '',
  selftext TEXT DEFAULT '',
  flair TEXT DEFAULT '',
  created_utc DOUBLE PRECISION DEFAULT 0,
  score INTEGER DEFAULT 0,
  embedding REAL[],
  PRIMARY KEY (subreddit, id)
);
CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON posts(subreddit);

CREATE TABLE IF NOT EXISTS drafts (
  id SERIAL PRIMARY KEY,
  name TEXT,
  title TEXT DEFAULT '',
  body TEXT DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fetch_jobs (
  id TEXT PRIMARY KEY,
  subreddit TEXT NOT NULL,
  target_limit INTEGER NOT NULL,
  status TEXT NOT NULL,
  status_detail TEXT,
  listing_index INTEGER NOT NULL DEFAULT 0,
  listing_after TEXT,
  fetched_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
`;

let initialized = false;

export async function initDb(): Promise<void> {
  if (initialized) return;
  await pool.query(SCHEMA);
  initialized = true;
}

function rowToSubreddit(row: Record<string, unknown>): SubredditRow {
  return {
    name: row.name as string,
    display_name: (row.display_name as string) || (row.name as string),
    subscribers: (row.subscribers as number) || 0,
    over18: Boolean(row.over18),
    quarantined: Boolean(row.quarantined),
    status: row.status as SubredditStatus,
    status_detail: (row.status_detail as string) || "",
    fetched_at: row.fetched_at ? new Date(row.fetched_at as string).toISOString() : null,
    num_posts: (row.num_posts as number) || 0,
    rules: (row.rules_json as RedditRule[]) || [],
    automod_available: Boolean(row.automod_available),
  };
}

export interface UpsertSubredditInput {
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
  automod_raw: string | null;
  automod_keywords: AutomodKeyword[];
}

export async function upsertSubreddit(input: UpsertSubredditInput): Promise<void> {
  await pool.query(
    `INSERT INTO subreddits (
      name, display_name, subscribers, over18, quarantined,
      status, status_detail, fetched_at, num_posts,
      rules_json, automod_available, automod_raw, automod_keywords_json
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
    ON CONFLICT (name) DO UPDATE SET
      display_name = EXCLUDED.display_name,
      subscribers = EXCLUDED.subscribers,
      over18 = EXCLUDED.over18,
      quarantined = EXCLUDED.quarantined,
      status = EXCLUDED.status,
      status_detail = EXCLUDED.status_detail,
      fetched_at = EXCLUDED.fetched_at,
      num_posts = EXCLUDED.num_posts,
      rules_json = EXCLUDED.rules_json,
      automod_available = EXCLUDED.automod_available,
      automod_raw = EXCLUDED.automod_raw,
      automod_keywords_json = EXCLUDED.automod_keywords_json`,
    [
      input.name,
      input.display_name,
      input.subscribers,
      input.over18,
      input.quarantined,
      input.status,
      input.status_detail,
      input.fetched_at,
      input.num_posts,
      JSON.stringify(input.rules),
      input.automod_available,
      input.automod_raw,
      JSON.stringify(input.automod_keywords),
    ]
  );
}

export async function getSubreddit(name: string): Promise<SubredditRow | null> {
  const res = await pool.query("SELECT * FROM subreddits WHERE name = $1", [name.toLowerCase()]);
  return res.rows[0] ? rowToSubreddit(res.rows[0]) : null;
}

export async function getSubredditInternal(name: string): Promise<Record<string, unknown> | null> {
  const res = await pool.query("SELECT * FROM subreddits WHERE name = $1", [name.toLowerCase()]);
  return res.rows[0] || null;
}

export async function listSubreddits(): Promise<SubredditRow[]> {
  const res = await pool.query("SELECT * FROM subreddits ORDER BY fetched_at DESC NULLS LAST");
  return res.rows.map(rowToSubreddit);
}

export async function deletePostsForSubreddit(name: string): Promise<void> {
  await pool.query("DELETE FROM posts WHERE subreddit = $1", [name.toLowerCase()]);
}

export async function insertPosts(subreddit: string, posts: PostRow[]): Promise<number> {
  if (posts.length === 0) return 0;
  subreddit = subreddit.toLowerCase();
  let inserted = 0;
  // Use a single multi-row INSERT ... ON CONFLICT DO NOTHING for speed.
  const values: unknown[] = [];
  const placeholders: string[] = [];
  posts.forEach((p, i) => {
    const base = i * 7;
    placeholders.push(
      `($${base + 1},$${base + 2},$${base + 3},$${base + 4},$${base + 5},$${base + 6},$${base + 7})`
    );
    values.push(p.id, subreddit, p.title, p.selftext, p.flair, p.created_utc, p.score);
  });
  const res = await pool.query(
    `INSERT INTO posts (id, subreddit, title, selftext, flair, created_utc, score)
     VALUES ${placeholders.join(",")}
     ON CONFLICT (subreddit, id) DO NOTHING`,
    values
  );
  inserted = res.rowCount || 0;

  // Store embeddings separately (nullable float arrays), matched by id.
  for (const p of posts) {
    if (p.embedding) {
      await pool.query(
        `UPDATE posts SET embedding = $1 WHERE subreddit = $2 AND id = $3`,
        [p.embedding, subreddit, p.id]
      );
    }
  }
  return inserted;
}

export async function countPosts(subreddit: string): Promise<number> {
  const res = await pool.query("SELECT COUNT(*)::int AS count FROM posts WHERE subreddit = $1", [
    subreddit.toLowerCase(),
  ]);
  return res.rows[0]?.count || 0;
}

export async function getPosts(subreddit: string): Promise<PostRow[]> {
  const res = await pool.query("SELECT * FROM posts WHERE subreddit = $1", [subreddit.toLowerCase()]);
  return res.rows.map((r) => ({
    id: r.id,
    subreddit: r.subreddit,
    title: r.title || "",
    selftext: r.selftext || "",
    flair: r.flair || "",
    created_utc: Number(r.created_utc) || 0,
    score: r.score || 0,
    embedding: r.embedding || null,
  }));
}

export async function saveDraft(title: string, body: string, name: string | null): Promise<DraftRow> {
  const res = await pool.query(
    `INSERT INTO drafts (name, title, body) VALUES ($1,$2,$3) RETURNING *`,
    [name, title, body]
  );
  const row = res.rows[0];
  return { ...row, created_at: new Date(row.created_at).toISOString() };
}

export async function listDrafts(): Promise<DraftRow[]> {
  const res = await pool.query("SELECT * FROM drafts ORDER BY created_at DESC");
  return res.rows.map((r) => ({ ...r, created_at: new Date(r.created_at).toISOString() }));
}

export async function deleteDraft(id: number): Promise<void> {
  await pool.query("DELETE FROM drafts WHERE id = $1", [id]);
}

export async function createFetchJob(
  id: string,
  subreddit: string,
  targetLimit: number
): Promise<void> {
  await pool.query(
    `INSERT INTO fetch_jobs (id, subreddit, target_limit, status, status_detail, listing_index, listing_after, fetched_count)
     VALUES ($1,$2,$3,'running',NULL,0,NULL,0)
     ON CONFLICT (id) DO NOTHING`,
    [id, subreddit.toLowerCase(), targetLimit]
  );
}

function rowToFetchJob(row: Record<string, unknown>): FetchJobRow {
  return {
    id: row.id as string,
    subreddit: row.subreddit as string,
    target_limit: row.target_limit as number,
    status: row.status as FetchJobStatus,
    status_detail: (row.status_detail as string) || null,
    listing_index: row.listing_index as number,
    listing_after: (row.listing_after as string) || null,
    fetched_count: row.fetched_count as number,
    created_at: new Date(row.created_at as string).toISOString(),
    updated_at: new Date(row.updated_at as string).toISOString(),
  };
}

export async function getFetchJob(id: string): Promise<FetchJobRow | null> {
  const res = await pool.query("SELECT * FROM fetch_jobs WHERE id = $1", [id]);
  return res.rows[0] ? rowToFetchJob(res.rows[0]) : null;
}

export async function updateFetchJob(
  id: string,
  patch: Partial<Pick<FetchJobRow, "status" | "status_detail" | "listing_index" | "listing_after" | "fetched_count">>
): Promise<void> {
  const fields = Object.keys(patch);
  if (fields.length === 0) return;
  const setClauses = fields.map((f, i) => `${f} = $${i + 2}`);
  setClauses.push("updated_at = now()");
  await pool.query(
    `UPDATE fetch_jobs SET ${setClauses.join(", ")} WHERE id = $1`,
    [id, ...fields.map((f) => (patch as Record<string, unknown>)[f])]
  );
}

export async function deleteFetchJob(id: string): Promise<void> {
  await pool.query("DELETE FROM fetch_jobs WHERE id = $1", [id]);
}
