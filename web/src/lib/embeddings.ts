/**
 * Optional local semantic embeddings via transformers.js (ONNX runtime in
 * Node, no Python/torch needed) — no external LLM API calls. Mirrors the
 * local Python app's sentence-transformers usage (same model family,
 * all-MiniLM-L6-v2) but degrades gracefully: if the model can't be loaded
 * (offline, blocked network, function-size constraints on some deploy
 * targets), callers just get `null` back and the app falls back to
 * rule/vocabulary-only scoring, exactly like the local version.
 */
export const EMBEDDING_MODEL_ID = "Xenova/all-MiniLM-L6-v2";

type FeatureExtractionPipeline = (
  texts: string[],
  options: { pooling: "mean"; normalize: boolean }
) => Promise<{ tolist(): number[][] }>;

let pipelinePromise: Promise<FeatureExtractionPipeline> | null = null;
let loadFailed = false;

export class EmbedderUnavailable extends Error {}

async function getPipeline(): Promise<FeatureExtractionPipeline> {
  if (loadFailed) {
    // Don't retry a slow network call (model download) on every single
    // request once we know it fails in this process; the next cold start
    // will try again.
    throw new EmbedderUnavailable("embedding model failed to load earlier in this process.");
  }
  if (!pipelinePromise) {
    pipelinePromise = (async () => {
      const { pipeline } = await import("@huggingface/transformers");
      return (await pipeline("feature-extraction", EMBEDDING_MODEL_ID)) as unknown as FeatureExtractionPipeline;
    })().catch((err) => {
      loadFailed = true;
      pipelinePromise = null;
      throw err;
    });
  }
  return pipelinePromise;
}

/** Returns one embedding vector per input text, or null if the embedding
 * model is unavailable in this environment. Never throws. */
export async function embedTexts(texts: string[]): Promise<number[][] | null> {
  if (texts.length === 0) return [];
  try {
    const extractor = await getPipeline();
    const output = await extractor(texts, { pooling: "mean", normalize: true });
    return output.tolist();
  } catch {
    return null;
  }
}

export async function embedOne(text: string): Promise<number[] | null> {
  const result = await embedTexts([text]);
  return result ? result[0] : null;
}
