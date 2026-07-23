import type { RiskLevel } from "@/lib/types";

const STYLES: Record<RiskLevel, string> = {
  low: "bg-green-100 text-green-800 border-green-300",
  medium: "bg-yellow-100 text-yellow-800 border-yellow-300",
  high: "bg-red-100 text-red-800 border-red-300",
  unknown: "bg-gray-100 text-gray-700 border-gray-300",
};

const DOT: Record<RiskLevel, string> = {
  low: "🟢",
  medium: "🟡",
  high: "🔴",
  unknown: "⚪",
};

export function RiskBadge({ level, score }: { level: RiskLevel; score: number }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium ${STYLES[level]}`}>
      <span>{DOT[level]}</span>
      <span>{level.toUpperCase()}</span>
      {level !== "unknown" && <span className="opacity-70">({score}/100)</span>}
    </span>
  );
}
