import {
  initDb,
  upsertSubreddit,
  getSubreddit,
  listSubreddits,
  insertPosts,
  getPosts,
  countPosts,
  saveDraft,
  listDrafts,
  deleteDraft,
  pool,
} from "../src/lib/db";

async function main() {
  await initDb();
  console.log("schema initialized OK");

  await upsertSubreddit({
    name: "testsub",
    display_name: "testsub",
    subscribers: 123,
    over18: false,
    quarantined: false,
    status: "ok",
    status_detail: "",
    fetched_at: new Date().toISOString(),
    num_posts: 0,
    rules: [{ short_name: "Rule 1", description: "Be nice", violation_reason: "Not nice", priority: 1 }],
    automod_available: true,
    automod_raw: "title: [\"spam\"]\naction: remove",
    automod_keywords: [{ pattern: "spam", field: "title", action: "remove", context: "title: [spam]", kind: "explicit" }],
  });
  const sub = await getSubreddit("testsub");
  console.log("upsert+get subreddit:", sub?.name, sub?.status, sub?.rules.length);

  const inserted = await insertPosts("testsub", [
    { id: "p1", subreddit: "testsub", title: "Hello world", selftext: "body1", flair: "", created_utc: 0, score: 1, embedding: [0.1, 0.2, 0.3] },
    { id: "p2", subreddit: "testsub", title: "Second post", selftext: "body2", flair: "", created_utc: 0, score: 2, embedding: null },
  ]);
  console.log("inserted posts:", inserted);
  const count = await countPosts("testsub");
  console.log("post count:", count);
  const posts = await getPosts("testsub");
  console.log("posts:", posts.map((p) => ({ id: p.id, hasEmbedding: !!p.embedding })));

  const listed = await listSubreddits();
  console.log("listed subreddits:", listed.length);

  const draft = await saveDraft("My title", "My body", "demo");
  console.log("saved draft id:", draft.id);
  const drafts = await listDrafts();
  console.log("drafts count:", drafts.length);
  await deleteDraft(draft.id);
  console.log("deleted draft, remaining:", (await listDrafts()).length);

  // cleanup test subreddit
  await pool.query("DELETE FROM subreddits WHERE name = $1", ["testsub"]);
  console.log("cleaned up testsub");

  await pool.end();
  console.log("ALL DB SMOKE TESTS PASSED");
}

main().catch((e) => {
  console.error("SMOKE TEST FAILED", e);
  process.exit(1);
});
