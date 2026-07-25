"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/apiClient";
import { SubredditSetup } from "@/components/SubredditSetup";
import { DraftChecker } from "@/components/DraftChecker";
import { SavedDrafts } from "@/components/SavedDrafts";

type Tab = "setup" | "check" | "drafts";

export default function Home() {
  const [tab, setTab] = useState<Tab>("setup");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [health, setHealth] = useState<{ status: string; reddit_configured: boolean } | null>(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealthError(true));
  }, []);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 w-full">
      <header className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">🧭 SubFit</h1>
        <p className="text-sm opacity-70">Check a draft against a subreddit&apos;s norms before you post.</p>
      </header>

      {healthError && (
        <div className="mb-6 rounded border border-red-300 bg-red-50 text-red-800 px-3 py-2 text-sm">
          Cannot reach the backend API. Check that DATABASE_URL is configured and the server is running.
        </div>
      )}
      {health && !health.reddit_configured && (
        <div className="mb-6 rounded border border-blue-300 bg-blue-50 text-blue-900 px-3 py-2 text-sm">
          Backend connected. Using Reddit&apos;s public API anonymously (no app credentials set) — this works fine for
          light use, just with lower rate limits. Add REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET to your environment
          variables for higher limits.
        </div>
      )}
      {health && health.reddit_configured && (
        <div className="mb-6 rounded border border-green-300 bg-green-50 text-green-800 px-3 py-2 text-sm">
          Backend connected. Using authenticated Reddit API access.
        </div>
      )}

      <nav className="flex gap-1 border-b border-gray-200 dark:border-gray-800 mb-6">
        {(
          [
            ["setup", "🧭 Subreddit Setup"],
            ["check", "✅ Draft Checker"],
            ["drafts", "💾 Saved Drafts"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              tab === key ? "border-red-600 text-red-600" : "border-transparent opacity-70 hover:opacity-100"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      <main>
        {tab === "setup" && <SubredditSetup />}
        {tab === "check" && (
          <DraftChecker title={draftTitle} body={draftBody} onTitleChange={setDraftTitle} onBodyChange={setDraftBody} />
        )}
        {tab === "drafts" && (
          <SavedDrafts
            onLoad={(t, b) => {
              setDraftTitle(t);
              setDraftBody(b);
              setTab("check");
            }}
          />
        )}
      </main>
    </div>
  );
}
