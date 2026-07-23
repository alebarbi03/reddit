import { initDb, listSubreddits } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  await initDb();
  const subs = await listSubreddits();
  return Response.json(subs);
}
