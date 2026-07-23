/**
 * Builds a subreddit's 'normal vocabulary fingerprint' from a corpus of live
 * posts (TF-IDF word/phrase frequency, ported to match scikit-learn's
 * TfidfVectorizer(ngram_range=(1,2), stop_words='english', min_df=2,
 * max_df=0.9) behavior) plus optional semantic topic embeddings, and scores
 * arbitrary text against it.
 */
import { ENGLISH_STOP_WORDS } from "./stopwords";
import type { PostRow } from "./types";

const WORD_RE = /[A-Za-z][A-Za-z'-]*/g;

export interface SubredditFingerprint {
  vocab: Map<string, number>; // term -> index
  idf: number[]; // idf per index
  idfP85: number;
  numDocs: number;
  corpusEmbeddings: number[][]; // L2-normalized, one row per post with an embedding
}

function tokenizeFiltered(text: string): string[] {
  const matches = text.match(WORD_RE) || [];
  return matches.map((w) => w.toLowerCase()).filter((w) => !ENGLISH_STOP_WORDS.has(w));
}

/** Mirrors sklearn's analyzer: filter stopwords from the unigram stream
 * first, then build bigrams from adjacent *filtered* tokens (so a bigram
 * can skip over a removed stopword, matching TfidfVectorizer's behavior). */
function docTerms(text: string): Set<string> {
  const filtered = tokenizeFiltered(text);
  const terms = new Set<string>();
  for (const w of filtered) terms.add(w);
  for (let i = 0; i < filtered.length - 1; i++) {
    terms.add(`${filtered[i]} ${filtered[i + 1]}`);
  }
  return terms;
}

function percentileLinear(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  if (sorted.length === 1) return sorted[0];
  const pos = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(pos);
  const upper = Math.ceil(pos);
  const frac = pos - lower;
  return sorted[lower] + frac * (sorted[upper] - sorted[lower]);
}

export function buildFingerprint(posts: PostRow[]): SubredditFingerprint | null {
  const texts: string[] = [];
  const embeddings: number[][] = [];
  for (const p of posts) {
    const text = `${p.title || ""} ${p.selftext || ""}`.trim();
    if (!text) continue;
    texts.push(text);
    if (p.embedding && p.embedding.length > 0) embeddings.push(p.embedding);
  }
  if (texts.length < 5) return null;

  const n = texts.length;
  const df = new Map<string, number>();
  const perDocTerms = texts.map(docTerms);
  for (const terms of perDocTerms) {
    for (const term of terms) {
      df.set(term, (df.get(term) || 0) + 1);
    }
  }

  const maxDf = 0.9 * n;
  const vocab = new Map<string, number>();
  const idf: number[] = [];
  let idx = 0;
  for (const [term, count] of df.entries()) {
    if (count >= 2 && count <= maxDf) {
      vocab.set(term, idx);
      idf.push(Math.log((1 + n) / (1 + count)) + 1);
      idx++;
    }
  }

  if (vocab.size === 0) return null;

  const sortedIdf = [...idf].sort((a, b) => a - b);
  const idfP85 = percentileLinear(sortedIdf, 85);

  const corpusEmbeddings = embeddings.length > 0 ? embeddings.map(normalize) : [];

  return { vocab, idf, idfP85, numDocs: n, corpusEmbeddings };
}

function normalize(vec: number[]): number[] {
  let sumSq = 0;
  for (const v of vec) sumSq += v * v;
  const norm = Math.sqrt(sumSq);
  if (norm === 0) return vec;
  return vec.map((v) => v / norm);
}

export interface CandidateSpan {
  phrase: string;
  start: number;
  end: number;
}

/** Returns (phrase, start, end) candidates for highlighting: every
 * non-trivial word, plus contiguous (true source-text-adjacent) word pairs,
 * skipping pure-stopword phrases. */
export function extractCandidateSpans(text: string, maxNgram = 2): CandidateSpan[] {
  const tokens: { word: string; start: number; end: number }[] = [];
  const re = new RegExp(WORD_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    tokens.push({ word: m[0], start: m.index, end: m.index + m[0].length });
  }

  const spans: CandidateSpan[] = [];
  for (const t of tokens) {
    if (t.word.length < 2 || ENGLISH_STOP_WORDS.has(t.word.toLowerCase())) continue;
    spans.push({ phrase: t.word, start: t.start, end: t.end });
  }

  for (let size = 2; size <= maxNgram; size++) {
    for (let i = 0; i <= tokens.length - size; i++) {
      const group = tokens.slice(i, i + size);
      const words = group.map((g) => g.word);
      if (words.every((w) => ENGLISH_STOP_WORDS.has(w.toLowerCase()))) continue;
      let adjacent = true;
      for (let j = 0; j < group.length - 1; j++) {
        if (group[j + 1].start - group[j].end > 1) {
          adjacent = false;
          break;
        }
      }
      if (!adjacent) continue;
      spans.push({ phrase: words.join(" "), start: group[0].start, end: group[group.length - 1].end });
    }
  }

  return spans;
}

export interface TermVerdict {
  phrase: string;
  start: number;
  end: number;
  status: "oov" | "rare" | "normal";
  idf: number | null;
  percentile: number | null;
}

export function classifyTerms(fp: SubredditFingerprint, spans: CandidateSpan[]): TermVerdict[] {
  const results: TermVerdict[] = [];
  for (const { phrase, start, end } of spans) {
    const idx = fp.vocab.get(phrase.toLowerCase());
    if (idx === undefined) {
      results.push({ phrase, start, end, status: "oov", idf: null, percentile: null });
      continue;
    }
    const idfVal = fp.idf[idx];
    const percentile = (fp.idf.filter((v) => v <= idfVal).length / fp.idf.length) * 100;
    const status = idfVal >= fp.idfP85 ? "rare" : "normal";
    results.push({ phrase, start, end, status, idf: idfVal, percentile });
  }
  return results;
}

export function semanticFit(draftEmbedding: number[] | null, fp: SubredditFingerprint, topK = 20): number | null {
  if (!draftEmbedding || fp.corpusEmbeddings.length === 0) return null;
  const draftVec = normalize(draftEmbedding);
  const sims = fp.corpusEmbeddings.map((doc) => dot(doc, draftVec));
  sims.sort((a, b) => a - b);
  const k = Math.min(topK, sims.length);
  const top = sims.slice(sims.length - k);
  return top.reduce((a, b) => a + b, 0) / top.length;
}

function dot(a: number[], b: number[]): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}
