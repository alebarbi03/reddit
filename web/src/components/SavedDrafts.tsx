"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/apiClient";
import type { DraftRow } from "@/lib/types";

export function SavedDrafts({ onLoad }: { onLoad: (title: string, body: string) => void }) {
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [loadedMsg, setLoadedMsg] = useState<string | null>(null);

  async function refresh() {
    setDrafts(await api.listDrafts());
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, []);

  async function handleDelete(id: number) {
    await api.deleteDraft(id);
    await refresh();
  }

  function handleLoad(d: DraftRow) {
    onLoad(d.title, d.body);
    setLoadedMsg(`Loaded "${d.name || d.title || "untitled"}" — switch to the Draft Checker tab.`);
  }

  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Saved drafts</h2>
      {loadedMsg && <div className="rounded border border-green-300 bg-green-50 text-green-800 px-3 py-2 text-sm mb-4">{loadedMsg}</div>}
      {drafts.length === 0 && <p className="text-sm opacity-70">No saved drafts yet. Save one from the Draft Checker tab.</p>}
      <div className="space-y-2">
        {drafts.map((d) => (
          <details key={d.id} className="rounded border border-gray-300 dark:border-gray-700 p-3">
            <summary className="cursor-pointer font-medium">
              {d.name || d.title.slice(0, 60) || "(untitled)"} — saved {d.created_at}
            </summary>
            <div className="mt-3 space-y-2 text-sm">
              <p>
                <strong>Title:</strong> {d.title}
              </p>
              <p>
                <strong>Body:</strong> {d.body}
              </p>
              <div className="flex gap-2">
                <button onClick={() => handleLoad(d)} className="rounded border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-sm">
                  Load into Draft Checker
                </button>
                <button
                  onClick={() => handleDelete(d.id)}
                  className="rounded border border-red-300 text-red-700 px-3 py-1.5 text-sm"
                >
                  Delete
                </button>
              </div>
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
