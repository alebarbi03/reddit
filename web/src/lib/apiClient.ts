import type { DraftRow, SubredditCheckResult, SubredditRow } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ status: string; reddit_configured: boolean }>(r)),

  listSubreddits: () => fetch("/api/subreddits").then((r) => json<SubredditRow[]>(r)),

  getSubreddit: (name: string) => fetch(`/api/subreddits/${encodeURIComponent(name)}`).then((r) => json<SubredditRow>(r)),

  fetchInit: (name: string, limit: number) =>
    fetch(`/api/subreddits/${encodeURIComponent(name)}/fetch/init`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    }).then((r) => json<{ jobId: string | null; status: string; statusDetail?: string; target?: number }>(r)),

  fetchStep: (name: string, jobId: string) =>
    fetch(`/api/subreddits/${encodeURIComponent(name)}/fetch/step`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jobId }),
    }).then((r) => json<{ done: boolean; fetched: number; target: number }>(r)),

  check: (title: string, body: string, subreddits: string[]) =>
    fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body, subreddits }),
    }).then((r) => json<{ results: SubredditCheckResult[] }>(r)),

  listDrafts: () => fetch("/api/drafts").then((r) => json<DraftRow[]>(r)),

  saveDraft: (title: string, body: string, name: string | null) =>
    fetch("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body, name }),
    }).then((r) => json<DraftRow>(r)),

  deleteDraft: (id: number) => fetch(`/api/drafts/${id}`, { method: "DELETE" }),
};
