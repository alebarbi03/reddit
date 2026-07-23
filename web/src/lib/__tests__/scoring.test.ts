import { describe, expect, it } from "vitest";
import { buildFingerprint } from "../fingerprint";
import { parseAutomodKeywords } from "../reddit";
import { checkDraft } from "../scoring";
import type { PostRow } from "../types";

function post(title: string, selftext: string): PostRow {
  return { id: title, subreddit: "test", title, selftext, flair: "", created_utc: 0, score: 1, embedding: null };
}

const CORPUS: PostRow[] = [
  post("Best budget GPU for 1440p gaming", "Looking for a graphics card recommendation under 400 dollars for 1440p gaming."),
  post("PSU wattage question", "How many watts do I need for a mid range build with one graphics card?"),
  post("RAM upgrade advice", "Is 32GB overkill for gaming and streaming at the same time?"),
  post("Case airflow help", "My CPU temps are high, need better case airflow and fan placement."),
  post("Motherboard compatibility", "Does this motherboard support DDR5 RAM and PCIe 5.0 graphics card slots?"),
  post("SSD vs NVMe for gaming", "Should I get an NVMe drive or is SATA SSD fine for my gaming build?"),
  post("Cheap prebuilt gaming PC", "What is a good prebuilt gaming PC under 800 dollars with a graphics card?"),
];

const AUTOMOD_RAW = `
title+body (includes):
    - "discount code"
    - "buy now"
action: remove
action_reason: "spam/affiliate links"
`;

describe("checkDraft", () => {
  it("scores a clean, on-topic draft as low risk", async () => {
    const fp = buildFingerprint(CORPUS)!;
    const keywords = await parseAutomodKeywords(AUTOMOD_RAW);
    const result = checkDraft("Need help picking a GPU", "Looking for a graphics card for gaming under $400.", keywords, fp, null);
    expect(result.riskLevel).toBe("low");
    expect(result.automodHits.length).toBe(0);
  });

  it("forces high risk on an explicit AutoModerator hit", async () => {
    const fp = buildFingerprint(CORPUS)!;
    const keywords = await parseAutomodKeywords(AUTOMOD_RAW);
    const result = checkDraft(
      "Great discount code inside!",
      "Buy now and get a discount code for premium stuff.",
      keywords,
      fp,
      null
    );
    expect(result.riskLevel).toBe("high");
    expect(result.riskScore).toBeGreaterThan(60);
    expect(result.automodHits.some((h) => h.matchedText.toLowerCase() === "discount code")).toBe(true);
    expect(result.automodHits.some((h) => h.action === "remove")).toBe(true);
    expect(result.topConcerns[0]).toContain("discount code");
  });

  it("flags off-topic vocabulary with OOV highlights", async () => {
    const fp = buildFingerprint(CORPUS)!;
    const result = checkDraft(
      "My favorite pasta recipe",
      "Today I made a delicious carbonara with pancetta and pecorino.",
      [],
      fp,
      null
    );
    expect(result.automodHits.length).toBe(0);
    const oovHighlights = result.highlights.filter((h) => h.type === "oov");
    expect(oovHighlights.length).toBeGreaterThan(0);
  });

  it("degrades gracefully with no fingerprint (subreddit not fetched) and no keywords", () => {
    const result = checkDraft("hello", "world", [], null, null);
    expect(result.riskLevel).toBe("low");
    expect(result.riskScore).toBe(0);
    expect(result.semanticSimilarity).toBeNull();
  });

  it("produces non-overlapping highlight spans", async () => {
    const fp = buildFingerprint(CORPUS)!;
    const keywords = await parseAutomodKeywords(AUTOMOD_RAW);
    const result = checkDraft("discount code discount code", "buy now buy now", keywords, fp, null);
    const byField: Record<string, Array<[number, number]>> = { title: [], body: [] };
    for (const h of result.highlights) byField[h.field].push([h.start, h.end]);
    for (const spans of Object.values(byField)) {
      const sorted = [...spans].sort((a, b) => a[0] - b[0]);
      for (let i = 1; i < sorted.length; i++) {
        expect(sorted[i][0]).toBeGreaterThanOrEqual(sorted[i - 1][1]);
      }
    }
  });
});
