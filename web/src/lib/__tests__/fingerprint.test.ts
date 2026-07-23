import { describe, expect, it } from "vitest";
import { buildFingerprint, classifyTerms, extractCandidateSpans, semanticFit } from "../fingerprint";
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

describe("buildFingerprint + classifyTerms", () => {
  it("returns null for tiny corpora", () => {
    expect(buildFingerprint([post("a", "b")])).toBeNull();
  });

  it("flags completely off-topic drafts as OOV", () => {
    const fp = buildFingerprint(CORPUS)!;
    expect(fp).not.toBeNull();
    const draft = "Check out my crypto pump and dump discount code, buy now before it moons!";
    const spans = extractCandidateSpans(draft);
    const verdicts = classifyTerms(fp, spans);
    // every unigram should be OOV against a PC-building corpus
    const unigramVerdicts = verdicts.filter((v) => !v.phrase.includes(" "));
    expect(unigramVerdicts.every((v) => v.status === "oov")).toBe(true);
  });

  it("recognizes on-topic vocabulary as in-corpus", () => {
    const fp = buildFingerprint(CORPUS)!;
    const draft = "Need a graphics card recommendation for gaming, what RAM should I pair with it?";
    const spans = extractCandidateSpans(draft);
    const verdicts = classifyTerms(fp, spans);
    const graphicsVerdict = verdicts.find((v) => v.phrase === "graphics");
    const cardVerdict = verdicts.find((v) => v.phrase === "card");
    const gamingVerdict = verdicts.find((v) => v.phrase === "gaming");
    expect(graphicsVerdict?.status).not.toBe("oov");
    expect(cardVerdict?.status).not.toBe("oov");
    expect(gamingVerdict?.status).not.toBe("oov");
  });

  it("does not flag common English stopwords as OOV", () => {
    const draft = "Need help picking a GPU for and with the build";
    const spans = extractCandidateSpans(draft);
    // stopwords like 'for', 'and', 'with', 'the' should never appear as unigram candidates at all
    const stopwordPhrases = spans.filter((s) => ["for", "and", "with", "the"].includes(s.phrase.toLowerCase()));
    expect(stopwordPhrases.length).toBe(0);
  });
});

describe("extractCandidateSpans", () => {
  it("extracts unigrams and adjacent bigrams with correct offsets", () => {
    const text = "Great discount code inside!";
    const spans = extractCandidateSpans(text);
    const discountSpan = spans.find((s) => s.phrase === "discount code");
    expect(discountSpan).toBeDefined();
    expect(text.slice(discountSpan!.start, discountSpan!.end)).toBe("discount code");
  });
});

describe("semanticFit", () => {
  it("scores on-topic drafts higher than off-topic ones", () => {
    const gamingVec = [1, 0, 0];
    const cookingVec = [0, 1, 0];
    const posts: PostRow[] = CORPUS.map((p, i) => ({ ...p, embedding: [1 + i * 0.001, 0.01, 0] }));
    const fp = buildFingerprint(posts)!;
    const onTopic = semanticFit(gamingVec, fp);
    const offTopic = semanticFit(cookingVec, fp);
    expect(onTopic).not.toBeNull();
    expect(offTopic).not.toBeNull();
    expect(onTopic!).toBeGreaterThan(offTopic!);
  });

  it("returns null when there are no corpus embeddings", () => {
    const fp = buildFingerprint(CORPUS)!;
    expect(semanticFit([1, 0, 0], fp)).toBeNull();
  });
});
