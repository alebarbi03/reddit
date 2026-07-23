import { initDb, listDrafts, saveDraft } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  await initDb();
  return Response.json(await listDrafts());
}

export async function POST(req: Request) {
  await initDb();
  const body = await req.json().catch(() => ({}));
  const draft = await saveDraft(body?.title || "", body?.body || "", body?.name || null);
  return Response.json(draft);
}
