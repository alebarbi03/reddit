import { initDb, upsertSubreddit, insertPosts, deletePostsForSubreddit } from "../src/lib/db";
import { parseAutomodKeywords } from "../src/lib/reddit";
import type { PostRow } from "../src/lib/types";

async function main() {
  await initDb();

  const automodRaw = `
title+body (includes):
    - "discount code"
    - "buy now"
action: remove
action_reason: "spam/affiliate"
`;
  const keywords = await parseAutomodKeywords(automodRaw);

  await upsertSubreddit({
    name: "buildapc",
    display_name: "buildapc",
    subscribers: 1000000,
    over18: false,
    quarantined: false,
    status: "ok",
    status_detail: "",
    fetched_at: new Date().toISOString(),
    num_posts: 7,
    rules: [{ short_name: "No buy/sell", description: "No buying, selling or trading.", violation_reason: "Buy/sell post", priority: 1 }],
    automod_available: true,
    automod_raw: automodRaw,
    automod_keywords: keywords,
  });

  await deletePostsForSubreddit("buildapc");

  const posts: PostRow[] = [
    ["Best budget GPU for 1440p gaming", "Looking for a graphics card recommendation under 400 dollars for 1440p gaming."],
    ["PSU wattage question", "How many watts do I need for a mid range build with one graphics card?"],
    ["RAM upgrade advice", "Is 32GB overkill for gaming and streaming at the same time?"],
    ["Case airflow help", "My CPU temps are high, need better case airflow and fan placement."],
    ["Motherboard compatibility", "Does this motherboard support DDR5 RAM and PCIe 5.0 graphics card slots?"],
    ["SSD vs NVMe for gaming", "Should I get an NVMe drive or is SATA SSD fine for my gaming build?"],
    ["Cheap prebuilt gaming PC", "What is a good prebuilt gaming PC under 800 dollars with a graphics card?"],
  ].map(([title, selftext], i) => ({
    id: `p${i}`,
    subreddit: "buildapc",
    title,
    selftext,
    flair: "",
    created_utc: 0,
    score: 1,
    embedding: null,
  }));

  const inserted = await insertPosts("buildapc", posts);
  console.log("seeded r/buildapc with", inserted, "posts");
  process.exit(0);
}

main();
