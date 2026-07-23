/**
 * Combines explicit AutoModerator/rule keyword hits with statistical
 * vocabulary-outlier and semantic-similarity signals into a single risk
 * score and a highlighted, explained draft.
 *
 * The scoring formula is a transparent heuristic, not a calibrated model:
 * explicit rule/AutoModerator hits dominate the score (and always force
 * risk_level to "high"), vocabulary outliers contribute next, and
 * topical/semantic drift contributes least.
 */
import * as fp from "./fingerprint";
import type { AutomodKeyword } from "./types";

const FIELD_SKIP_PREFIXES = ["domain", "url", "flair", "author"];

function fieldScope(field: string): "title" | "body" | "both" | "skip" {
  const f = field.toLowerCase().trim();
  if (f.startsWith("title+body") || f.startsWith("full_text")) return "both";
  if (f.startsWith("title")) return "title";
  if (f.startsWith("body") || f.startsWith("selftext")) return "body";
  if (FIELD_SKIP_PREFIXES.some((p) => f.startsWith(p))) return "skip";
  return "both";
}

interface Match {
  start: number;
  end: number;
  matchedText: string;
}

function matchPattern(pattern: string, field: string, text: string): Match[] {
  const f = field.toLowerCase();
  const matches: Match[] = [];

  if (f.includes("regex")) {
    try {
      const re = new RegExp(pattern, "gi");
      let m: RegExpExecArray | null;
      while ((m = re.exec(text)) !== null) {
        matches.push({ start: m.index, end: m.index + m[0].length, matchedText: m[0] });
        if (m[0].length === 0) re.lastIndex++;
      }
      return matches;
    } catch {
      // invalid regex in the config; fall through to literal match
    }
  }

  if (f.includes("word")) {
    try {
      const re = new RegExp(`\\b${escapeRegExp(pattern)}\\b`, "gi");
      let m: RegExpExecArray | null;
      while ((m = re.exec(text)) !== null) {
        matches.push({ start: m.index, end: m.index + m[0].length, matchedText: m[0] });
      }
      return matches;
    } catch {
      return matches;
    }
  }

  const lowerText = text.toLowerCase();
  const lowerPat = pattern.toLowerCase();
  if (!lowerPat) return matches;
  let start = 0;
  while (true) {
    const idx = lowerText.indexOf(lowerPat, start);
    if (idx === -1) break;
    matches.push({ start: idx, end: idx + pattern.length, matchedText: text.slice(idx, idx + pattern.length) });
    start = idx + Math.max(pattern.length, 1);
  }
  return matches;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export interface AutomodHitInternal {
  matchedText: string;
  field: string;
  scope: "title" | "body";
  start: number;
  end: number;
  pattern: string;
  action: string | null;
  context: string;
  confidence: "explicit" | "heuristic";
}

export function findAutomodHits(title: string, body: string, keywords: AutomodKeyword[]): AutomodHitInternal[] {
  const hits: AutomodHitInternal[] = [];
  for (const kw of keywords) {
    const pattern = kw.pattern || "";
    const field = kw.field || "";
    if (!pattern) continue;
    const scope = fieldScope(field);
    if (scope === "skip") continue;

    const targets: Array<["title" | "body", string]> = [];
    if (scope === "title" || scope === "both") targets.push(["title", title]);
    if (scope === "body" || scope === "both") targets.push(["body", body]);

    for (const [scopeName, text] of targets) {
      if (!text) continue;
      for (const { start, end, matchedText } of matchPattern(pattern, field, text)) {
        hits.push({
          matchedText,
          field,
          scope: scopeName,
          start,
          end,
          pattern,
          action: kw.action,
          context: kw.context || "",
          confidence: kw.kind,
        });
      }
    }
  }
  return hits;
}

interface SpanEvent {
  start: number;
  end: number;
  text: string;
  type: "automod" | "oov" | "rare";
  priority: number;
  reason: string;
  ruleText: string | null;
}

function mergeSpans(automodHits: AutomodHitInternal[], verdicts: fp.TermVerdict[]): SpanEvent[] {
  const events: SpanEvent[] = [];
  for (const h of automodHits) {
    events.push({
      start: h.start,
      end: h.end,
      text: h.matchedText,
      type: "automod",
      priority: 3,
      reason: `Matches an AutoModerator trigger (${h.field}).`,
      ruleText: h.context,
    });
  }
  for (const v of verdicts) {
    if (v.status === "normal") continue;
    const priority = v.status === "oov" ? 2 : 1;
    const reason =
      v.status === "oov"
        ? "This word/phrase never appears in this subreddit's sampled posts."
        : `This word/phrase is rare in this subreddit (rarer than ${v.percentile!.toFixed(0)}% of its vocabulary).`;
    events.push({ start: v.start, end: v.end, text: v.phrase, type: v.status, priority, reason, ruleText: null });
  }

  const occupied: Array<[number, number]> = [];
  const accepted: SpanEvent[] = [];
  const ordered = [...events].sort((a, b) => b.priority - a.priority || b.end - b.start - (a.end - a.start));
  for (const e of ordered) {
    const overlaps = occupied.some(([s, en]) => !(e.end <= s || e.start >= en));
    if (overlaps) continue;
    occupied.push([e.start, e.end]);
    accepted.push(e);
  }
  accepted.sort((a, b) => a.start - b.start);
  return accepted;
}

function buildConcerns(
  explicitHits: AutomodHitInternal[],
  heuristicHits: AutomodHitInternal[],
  unigramVerdicts: fp.TermVerdict[],
  similarity: number | null
): string[] {
  const concerns: string[] = [];
  const seen = new Set<string>();

  for (const h of explicitHits) {
    if (seen.has(h.pattern)) continue;
    seen.add(h.pattern);
    const actionTxt = h.action ? ` (AutoModerator action: ${h.action})` : "";
    const snippet = h.context ? h.context.split("\n")[0].slice(0, 120) : "";
    concerns.push(`'${h.matchedText}' in your ${h.scope} matches an AutoModerator rule${actionTxt}: ${snippet}`);
    if (concerns.length >= 3) return concerns;
  }

  for (const h of heuristicHits) {
    if (seen.has(h.pattern)) continue;
    seen.add(h.pattern);
    concerns.push(
      `'${h.matchedText}' may match a filtered keyword in this subreddit's AutoModerator config ` +
        "(low-confidence match; the config wasn't valid YAML)."
    );
    if (concerns.length >= 3) return concerns;
  }

  const oovTerms = [...new Set(unigramVerdicts.filter((v) => v.status === "oov").map((v) => v.phrase))].sort();
  if (oovTerms.length > 0) {
    const sample = oovTerms.slice(0, 5).map((t) => `'${t}'`).join(", ");
    concerns.push(`These words never appear in this subreddit's recent posts, which is unusual vocabulary here: ${sample}.`);
    if (concerns.length >= 3) return concerns;
  }

  if (similarity !== null && similarity < 0.35) {
    concerns.push(
      `Your draft's overall topic doesn't closely resemble what's normally posted here (topical similarity score: ${similarity.toFixed(2)}).`
    );
  }

  if (concerns.length === 0) {
    concerns.push("No explicit rule hits, and vocabulary/topic look consistent with this subreddit's recent posts.");
  }
  return concerns.slice(0, 3);
}

export interface CheckOutcome {
  riskScore: number;
  riskLevel: "low" | "medium" | "high";
  automodHits: AutomodHitInternal[];
  highlights: Array<{
    text: string;
    start: number;
    end: number;
    field: "title" | "body";
    type: "automod" | "oov" | "rare";
    reason: string;
    rule_text: string | null;
  }>;
  semanticSimilarity: number | null;
  topConcerns: string[];
}

export function checkDraft(
  title: string,
  body: string,
  keywords: AutomodKeyword[],
  fingerprint: fp.SubredditFingerprint | null,
  draftEmbedding: number[] | null
): CheckOutcome {
  title = title || "";
  body = body || "";

  const automodHits = findAutomodHits(title, body, keywords);
  const explicitHits = automodHits.filter((h) => h.confidence === "explicit");
  const heuristicHits = automodHits.filter((h) => h.confidence === "heuristic");

  let termVerdictsTitle: fp.TermVerdict[] = [];
  let termVerdictsBody: fp.TermVerdict[] = [];
  let similarity: number | null = null;

  if (fingerprint) {
    termVerdictsTitle = fp.classifyTerms(fingerprint, fp.extractCandidateSpans(title));
    termVerdictsBody = fp.classifyTerms(fingerprint, fp.extractCandidateSpans(body));
    similarity = fp.semanticFit(draftEmbedding, fingerprint);
  }

  const highlights: CheckOutcome["highlights"] = [];
  for (const [fieldName, hits, verdicts] of [
    ["title", automodHits.filter((h) => h.scope === "title"), termVerdictsTitle],
    ["body", automodHits.filter((h) => h.scope === "body"), termVerdictsBody],
  ] as const) {
    for (const e of mergeSpans(hits, verdicts)) {
      highlights.push({
        text: e.text,
        start: e.start,
        end: e.end,
        field: fieldName,
        type: e.type,
        reason: e.reason,
        rule_text: e.ruleText,
      });
    }
  }

  let automodComponent = 0;
  if (explicitHits.length > 0) {
    automodComponent = Math.min(100, 55 + 15 * (explicitHits.length - 1));
  } else if (heuristicHits.length > 0) {
    automodComponent = Math.min(60, 25 + 10 * (heuristicHits.length - 1));
  }

  const unigramVerdicts = [...termVerdictsTitle, ...termVerdictsBody].filter((v) => !v.phrase.includes(" "));
  let vocabComponent = 0;
  if (unigramVerdicts.length > 0) {
    const oovRatio = unigramVerdicts.filter((v) => v.status === "oov").length / unigramVerdicts.length;
    const rareRatio = unigramVerdicts.filter((v) => v.status === "rare").length / unigramVerdicts.length;
    vocabComponent = Math.min(100, oovRatio * 100 + rareRatio * 50);
  }

  const semanticComponent = similarity === null ? 0 : Math.max(0, Math.min(100, (0.5 - similarity) * 200));

  let overall: number;
  if (!fingerprint) {
    overall = automodComponent;
  } else {
    overall = 0.55 * automodComponent + 0.3 * vocabComponent + 0.15 * semanticComponent;
  }
  overall = Math.max(0, Math.min(100, overall));

  let riskLevel: "low" | "medium" | "high";
  if (explicitHits.length > 0 || overall >= 67) riskLevel = "high";
  else if (overall >= 33) riskLevel = "medium";
  else riskLevel = "low";

  const topConcerns = buildConcerns(explicitHits, heuristicHits, unigramVerdicts, similarity);

  return {
    riskScore: Math.round(overall),
    riskLevel,
    automodHits,
    highlights,
    semanticSimilarity: similarity,
    topConcerns,
  };
}
