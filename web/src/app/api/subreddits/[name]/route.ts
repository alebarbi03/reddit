import { getSubreddit, initDb } from "@/lib/db";
import { normalizeSubredditName } from "@/lib/reddit";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: RouteContext<"/api/subreddits/[name]">) {
  await initDb();
  const { name: rawName } = await ctx.params;
  const name = normalizeSubredditName(rawName);
  const row = await getSubreddit(name);
  if (!row) {
    return Response.json(
      { detail: "Subreddit not cached yet. POST /api/subreddits/{name}/fetch/init first." },
      { status: 404 }
    );
  }
  return Response.json(row);
}
