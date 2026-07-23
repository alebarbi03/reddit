/**
 * Pure state-machine for chunked corpus fetching: pulls a bounded number of
 * listing pages per call so a single serverless invocation never has to
 * fetch an entire 3,000-5,000 post corpus in one shot (which could exceed
 * platform execution time limits). The caller (the fetch/step API route)
 * repeatedly invokes this until `done` is true. Dependencies are injected
 * so this can be unit-tested without live Reddit or a database.
 */
import type { ListingSpec, RawPost } from "./reddit";

export interface JobState {
  listingIndex: number;
  listingAfter: string | null;
}

export interface RunStepDeps {
  listings: ListingSpec[];
  fetchPage: (spec: ListingSpec, after: string | null) => Promise<{ posts: RawPost[]; after: string | null }>;
  embed: (texts: string[]) => Promise<number[][] | null>;
  insertPosts: (rows: Array<RawPost & { embedding: number[] | null }>) => Promise<void>;
  getCount: () => Promise<number>;
  maxPagesPerStep: number;
}

export interface RunStepResult extends JobState {
  done: boolean;
  fetchedCount: number;
}

export async function runFetchStep(job: JobState, targetLimit: number, deps: RunStepDeps): Promise<RunStepResult> {
  let { listingIndex, listingAfter } = job;
  let count = await deps.getCount();
  let pages = 0;

  while (pages < deps.maxPagesPerStep && listingIndex < deps.listings.length && count < targetLimit) {
    const spec = deps.listings[listingIndex];
    const page = await deps.fetchPage(spec, listingAfter);
    pages++;

    if (page.posts.length > 0) {
      const texts = page.posts.map((p) => `${p.title} ${p.selftext}`.trim());
      const embeddings = await deps.embed(texts);
      await deps.insertPosts(
        page.posts.map((p, i) => ({ ...p, embedding: embeddings ? embeddings[i] : null }))
      );
      count = await deps.getCount();
    }

    if (!page.after || page.posts.length === 0) {
      listingIndex++;
      listingAfter = null;
    } else {
      listingAfter = page.after;
    }
  }

  const done = listingIndex >= deps.listings.length || count >= targetLimit;
  return { listingIndex, listingAfter, done, fetchedCount: count };
}
