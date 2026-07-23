import { describe, expect, it } from "vitest";
import { normalizeSubredditName, parseAutomodKeywords } from "../reddit";

describe("normalizeSubredditName", () => {
  it("strips r/ prefixes and normalizes case/whitespace", () => {
    expect(normalizeSubredditName("r/Python")).toBe("python");
    expect(normalizeSubredditName("/r/Python/")).toBe("python");
    expect(normalizeSubredditName("  Python  ")).toBe("python");
    expect(normalizeSubredditName("python")).toBe("python");
  });
});

describe("parseAutomodKeywords", () => {
  it("parses standard AutoMod YAML with modifier-in-key syntax", async () => {
    const raw = `
type: submission
title+body (includes, regex):
    - "buy now"
    - "discount code"
action: remove
action_reason: "spam keywords"
---
type: submission
domain:
    - "spam-site.com"
action: remove
`;
    const items = await parseAutomodKeywords(raw);
    const patterns = items.map((i) => i.pattern);
    expect(patterns).toContain("buy now");
    expect(patterns).toContain("discount code");
    expect(patterns).toContain("spam-site.com");
    expect(items.every((i) => i.kind === "explicit")).toBe(true);
  });

  it("falls back to heuristic extraction for malformed YAML", async () => {
    const raw = 'this is not: valid: yaml: at: all: "sketchy phrase" more garbage "another one"';
    const items = await parseAutomodKeywords(raw);
    const patterns = items.map((i) => i.pattern);
    expect(patterns.includes("sketchy phrase") || patterns.includes("another one")).toBe(true);
    expect(items.every((i) => i.kind === "heuristic")).toBe(true);
  });

  it("returns empty for null/empty input", async () => {
    expect(await parseAutomodKeywords(null)).toEqual([]);
    expect(await parseAutomodKeywords("")).toEqual([]);
  });

  it("dedupes repeated patterns within the same field", async () => {
    const raw = `
title (includes):
    - "duplicate"
    - "duplicate"
action: remove
`;
    const items = await parseAutomodKeywords(raw);
    const count = items.filter((i) => i.pattern === "duplicate").length;
    expect(count).toBe(1);
  });
});
