"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/apiClient";
import type { SubredditRow } from "@/lib/types";

const STATUS_EMOJI: Record<string, string> = {
  ok: "✅",
  fetching: "⏳",
  private: "🔒",
  banned: "🚫",
  not_found: "❓",
  quarantined: "☣️",
  error: "⚠️",
};

export function SubredditSetup() {
  const [name, setName] = useState("");
  const [limit, setLimit] = useState(3000);
  const [subs, setSubs] = useState<SubredditRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ fetched: number; target: number } | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error" | "info"; text: string } | null>(null);

  async function refreshList() {
    try {
      setSubs(await api.listSubreddits());
    } catch {
      // health check elsewhere will surface connectivity issues
    }
  }

  useEffect(() => {
    // Standard fetch-on-mount pattern; state is only set after the async
    // boundary, not synchronously during the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshList();
  }, []);

  async function handleFetch() {
    if (!name.trim()) return;
    setBusy(true);
    setMessage(null);
    setProgress(null);
    try {
      const init = await api.fetchInit(name, limit);
      if (!init.jobId) {
        setMessage({
          kind: init.status === "ok" ? "success" : "info",
          text: `r/${name} — status: ${init.status}${init.statusDetail ? ` (${init.statusDetail})` : ""}`,
        });
        await refreshList();
        setBusy(false);
        return;
      }
      setProgress({ fetched: 0, target: init.target || limit });
      let done = false;
      while (!done) {
        const step = await api.fetchStep(name, init.jobId);
        setProgress({ fetched: step.fetched, target: step.target });
        done = step.done;
      }
      setMessage({ kind: "success", text: `Fetched r/${name} successfully.` });
      await refreshList();
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold mb-1">Fetch &amp; cache a subreddit&apos;s corpus, rules, and AutoModerator config</h2>
        <p className="text-sm opacity-70 mb-4">
          Corpus fetching runs in short chunks and can take a little while for large subreddits — a progress bar tracks it.
        </p>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-[220px]">
            <label className="block text-sm font-medium mb-1">Subreddit name (without r/)</label>
            <input
              className="w-full rounded border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2"
              placeholder="e.g. buildapc"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Posts to sample: {limit}</label>
            <input
              type="range"
              min={2000}
              max={5000}
              step={500}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="w-48"
            />
          </div>
          <button
            onClick={handleFetch}
            disabled={busy || !name.trim()}
            className="rounded bg-red-600 text-white px-4 py-2 font-medium disabled:opacity-50"
          >
            {busy ? "Fetching…" : "Fetch / Refresh corpus"}
          </button>
        </div>

        {progress && (
          <div className="mt-4">
            <div className="h-2 w-full rounded bg-gray-200 dark:bg-gray-800 overflow-hidden">
              <div
                className="h-full bg-red-500 transition-all"
                style={{ width: `${Math.min(100, (progress.fetched / Math.max(progress.target, 1)) * 100)}%` }}
              />
            </div>
            <p className="text-xs opacity-70 mt-1">
              {progress.fetched} / {progress.target} posts fetched…
            </p>
          </div>
        )}

        {message && (
          <div
            className={`mt-4 rounded border px-3 py-2 text-sm ${
              message.kind === "success"
                ? "border-green-300 bg-green-50 text-green-800"
                : message.kind === "error"
                  ? "border-red-300 bg-red-50 text-red-800"
                  : "border-blue-300 bg-blue-50 text-blue-800"
            }`}
          >
            {message.text}
          </div>
        )}
      </div>

      <div>
        <h3 className="text-lg font-semibold mb-3">Cached subreddits</h3>
        {subs.length === 0 && <p className="text-sm opacity-70">No subreddits cached yet. Fetch one above.</p>}
        <div className="space-y-2">
          {subs.map((s) => (
            <details key={s.name} className="rounded border border-gray-300 dark:border-gray-700 p-3">
              <summary className="cursor-pointer font-medium">
                {STATUS_EMOJI[s.status] || "⚪"} r/{s.name} — {s.num_posts} posts — fetched {s.fetched_at || "never"}
              </summary>
              <div className="mt-3 space-y-1 text-sm">
                <p>
                  <strong>Status:</strong> {s.status}
                </p>
                {s.status_detail && <p>{s.status_detail}</p>}
                <p>
                  <strong>Subscribers:</strong> {s.subscribers.toLocaleString()} &nbsp;|&nbsp;{" "}
                  <strong>NSFW:</strong> {String(s.over18)} &nbsp;|&nbsp; <strong>Quarantined:</strong> {String(s.quarantined)}
                </p>
                <p>
                  <strong>AutoModerator config:</strong>{" "}
                  {s.automod_available ? "available ✅" : "not publicly available — vocabulary-fit analysis only"}
                </p>
                {s.rules.length > 0 ? (
                  <div>
                    <strong>Rules ({s.rules.length}):</strong>
                    <ul className="list-disc list-inside">
                      {s.rules.map((r, i) => (
                        <li key={i}>
                          <strong>{r.short_name}</strong>: {r.description || r.violation_reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p>
                    <strong>Rules:</strong> none published.
                  </p>
                )}
              </div>
            </details>
          ))}
        </div>
      </div>
    </div>
  );
}
