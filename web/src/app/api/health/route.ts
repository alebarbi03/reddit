import { initDb } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await initDb();
    return Response.json({
      status: "ok",
      reddit_configured: Boolean(process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET),
    });
  } catch (e) {
    return Response.json(
      { status: "error", detail: e instanceof Error ? e.message : String(e) },
      { status: 500 }
    );
  }
}
