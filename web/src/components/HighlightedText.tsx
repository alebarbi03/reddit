import type { HighlightSpan } from "@/lib/types";

const COLORS: Record<HighlightSpan["type"], string> = {
  automod: "#ef4444",
  oov: "#f97316",
  rare: "#eab308",
};

export const HIGHLIGHT_LABELS: Record<HighlightSpan["type"], string> = {
  automod: "AutoModerator rule match",
  oov: "Absent from subreddit vocabulary",
  rare: "Rare in subreddit vocabulary",
};

export function HighlightedText({ text, spans }: { text: string; spans: HighlightSpan[] }) {
  if (!text) {
    return <em className="opacity-60">(empty)</em>;
  }
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((s, i) => {
    if (s.start < cursor) return;
    if (s.start > cursor) parts.push(<span key={`t-${i}`}>{text.slice(cursor, s.start)}</span>);
    const color = COLORS[s.type];
    const title = s.rule_text ? `${s.reason} | Rule: ${s.rule_text}` : s.reason;
    parts.push(
      <span
        key={`h-${i}`}
        title={title}
        style={{
          backgroundColor: `${color}33`,
          borderBottom: `2px solid ${color}`,
          borderRadius: 2,
          padding: "0 1px",
        }}
      >
        {text.slice(s.start, s.end)}
      </span>
    );
    cursor = s.end;
  });
  if (cursor < text.length) parts.push(<span key="rest">{text.slice(cursor)}</span>);
  return <span className="whitespace-pre-wrap">{parts}</span>;
}

export function HighlightLegend() {
  return (
    <div className="mt-1 flex flex-wrap gap-3 text-xs">
      {(Object.keys(HIGHLIGHT_LABELS) as Array<HighlightSpan["type"]>).map((k) => (
        <span
          key={k}
          className="rounded px-1.5 py-0.5"
          style={{ backgroundColor: `${COLORS[k]}33`, borderBottom: `2px solid ${COLORS[k]}` }}
        >
          {HIGHLIGHT_LABELS[k]}
        </span>
      ))}
    </div>
  );
}
