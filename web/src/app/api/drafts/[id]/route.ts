import { deleteDraft, initDb } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function DELETE(_req: Request, ctx: RouteContext<"/api/drafts/[id]">) {
  await initDb();
  const { id } = await ctx.params;
  await deleteDraft(Number(id));
  return new Response(null, { status: 204 });
}
