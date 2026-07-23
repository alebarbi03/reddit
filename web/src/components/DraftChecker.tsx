"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/apiClient";
import type { SubredditCheckResult, SubredditRow } from "@/lib/types";
import { RiskBadge } from "./RiskBadge";
import { HighlightedText, HighlightLegend } from "./HighlightedText";

const STATUS_EMOJI: Record<string, string> = {
  not_fetched: "❔",
  private: "🔒",
  banned: "🚫",
  not_found: "❓",
  quarantined: "☣️",
  error: "⚠️",
  fetching: "⏳",
};

const RISK_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2, unknown: 3 };

export function DraftChecker({
  title,
  body,
  onTitleChange,
  onBodyChange,
}: {
  title: string;
  body: string;
  onTitleChange: (v: string) => void;
  onBodyChange: (v: string) => void;
}) {
  const [availableSubs, setAvailableSubs] = useState<SubredditRow[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<SubredditCheckResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSubreddits()
      .then((subs) => {
        setAvailableSubs(subs);
        if (subs.length > 0) setSelected([subs[0].name]);
      })
      .catch(() => {});
  }, []);

  function toggleSub(name: string) {
    setSelected((prev) => (prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]));
  }

  async function handleCheck() {
    const extraTargets = extra
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const targets = Array.from(new Set([...selected, ...extraTargets]));
    if (targets.length === 0) {
      setError("Select or type at least one subreddit to check against.");
      return;
    }
    if (!title.trim() && !body.trim()) {
      setError("Enter a draft title and/or body first.");
      return;
    }
    setError(null);
    setBusy(true);
    setResults(null);
    try {
      const res = await api.check(title, body, targets);
      const sorted = [...res.results].sort((a, b) => (RISK_ORDER[a.risk_level] ?? 4) - (RISK_ORDER[b.risk_level] ?? 4));
      setResults(sorted);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    setSaveMsg(null);
    try {
      await api.saveDraft(title, body, saveName || null);
      setSaveMsg("Draft saved.");
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Check your draft against one or more subreddits</h2>

      <div>
        <label className="block text-sm font-medium mb-1">Draft title</label>
        <input
          className="w-full rounded border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2"
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
        />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1">Draft body</label>
        <textarea
          className="w-full rounded border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2 h-40"
          value={body}
          onChange={(e) => onBodyChange(e.target.value)}
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Check against subreddit(s) (must be fetched in Subreddit Setup first)</label>
        <div className="flex flex-wrap gap-2 mb-2">
          {availableSubs.map((s) => (
            <button
              key={s.name}
              onClick={() => toggleSub(s.name)}
              className={`rounded-full px-3 py-1 text-sm border ${
                selected.includes(s.name)
                  ? "bg-red-600 text-white border-red-600"
                  : "border-gray-300 dark:border-gray-700"
              }`}
            >
              {s.name}
            </button>
          ))}
          {availableSubs.length === 0 && <span className="text-sm opacity-60">No cached subreddits yet.</span>}
        </div>
        <input
          className="w-full rounded border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2"
          placeholder="Or type other subreddit name(s), comma-separated, no r/"
          value={extra}
          onChange={(e) => setExtra(e.target.value)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <button
          onClick={handleCheck}
          disabled={busy}
          className="rounded bg-red-600 text-white px-4 py-2 font-medium disabled:opacity-50"
        >
          {busy ? "Scoring…" : "Check draft"}
        </button>
        <input
          className="rounded border border-gray-300 dark:border-gray-700 bg-transparent px-3 py-2 text-sm"
          placeholder="Name to save this draft as…"
          value={saveName}
          onChange={(e) => setSaveName(e.target.value)}
        />
        <button onClick={handleSave} className="rounded border border-gray-300 dark:border-gray-700 px-3 py-2 text-sm">
          💾 Save draft
        </button>
        {saveMsg && <span className="text-sm opacity-70">{saveMsg}</span>}
      </div>

      {error && <div className="rounded border border-red-300 bg-red-50 text-red-800 px-3 py-2 text-sm">{error}</div>}

      {results && (
        <div className="space-y-8 pt-4">
          {results.map((r) => (
            <ResultCard key={r.subreddit} result={r} title={title} body={body} />
          ))}
        </div>
      )}
    </div>
  );
}

function ResultCard({ result, title, body }: { result: SubredditCheckResult; title: string; body: string }) {
  if (result.status !== "ok") {
    return (
      <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
        <h3 className="font-semibold mb-2">
          {STATUS_EMOJI[result.status] || "⚠️"} r/{result.subreddit}
        </h3>
        <div className="rounded border border-yellow-300 bg-yellow-50 text-yellow-900 px-3 py-2 text-sm">
          {result.status_detail || `Status: ${result.status}`}
        </div>
      </div>
    );
  }

  const titleSpans = result.highlights.filter((h) => h.field === "title");
  const bodySpans = result.highlights.filter((h) => h.field === "body");

  return (
    <div className="border-t border-gray-200 dark:border-gray-800 pt-4 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="font-semibold text-lg">r/{result.subreddit}</h3>
        <RiskBadge level={result.risk_level} score={result.risk_score} />
      </div>

      {result.status_detail && (
        <div className="rounded border border-blue-300 bg-blue-50 text-blue-900 px-3 py-2 text-sm">{result.status_detail}</div>
      )}

      <p className="text-xs opacity-60">
        Corpus: {result.corpus_size} posts, fetched {result.corpus_fetched_at || "unknown"}
      </p>

      {result.top_concerns.length > 0 && (
        <div>
          <p className="font-medium text-sm mb-1">Top concerns:</p>
          <ul className="list-disc list-inside text-sm space-y-0.5">
            {result.top_concerns.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {result.automod_hits.length > 0 && (
        <details open className="rounded border border-gray-300 dark:border-gray-700 p-3">
          <summary className="cursor-pointer font-medium text-sm">
            AutoModerator rule matches ({result.automod_hits.length})
          </summary>
          <ul className="mt-2 space-y-1 text-sm">
            {result.automod_hits.map((h, i) => (
              <li key={i}>
                <strong>&apos;{h.matched_text}&apos;</strong> in <em>{h.field}</em>
                {h.action && (
                  <>
                    {" "}
                    → action: <code className="text-green-700">{h.action}</code>
                  </>
                )}
                {h.confidence !== "explicit" && <span className="opacity-60"> (low-confidence heuristic match)</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {result.rules.length > 0 && (
        <details className="rounded border border-gray-300 dark:border-gray-700 p-3">
          <summary className="cursor-pointer font-medium text-sm">Subreddit rules ({result.rules.length})</summary>
          <ul className="mt-2 space-y-1 text-sm list-disc list-inside">
            {result.rules.map((r, i) => (
              <li key={i}>
                <strong>{r.short_name}</strong>: {r.description || r.violation_reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div>
        <p className="font-medium text-sm mb-1">Highlighted draft:</p>
        <div className="rounded border border-gray-300 dark:border-gray-700 p-3 mb-2">
          <strong>Title:</strong> <HighlightedText text={title} spans={titleSpans} />
        </div>
        <div className="rounded border border-gray-300 dark:border-gray-700 p-3">
          <strong>Body:</strong> <HighlightedText text={body} spans={bodySpans} />
        </div>
        <HighlightLegend />
      </div>

      {result.semantic_similarity !== null ? (
        <p className="text-sm">
          <strong>Semantic topical fit</strong> (cosine similarity to corpus): {result.semantic_similarity.toFixed(2)}
        </p>
      ) : (
        <p className="text-xs opacity-60">Semantic similarity unavailable (embedding model not loaded / corpus has no embeddings).</p>
      )}
    </div>
  );
}
