import { describe, expect, it } from "vitest";
import { runFetchStep } from "../fetchJobRunner";
import type { ListingSpec, RawPost } from "../reddit";

const LISTINGS: ListingSpec[] = [{ listing: "new" }, { listing: "hot" }, { listing: "rising" }];

function makePost(id: string): RawPost {
  return { id, title: `title ${id}`, selftext: "", flair: "", created_utc: 0, score: 1 };
}

/** Fake Reddit source: each listing has a fixed number of pages of 100 posts,
 * paginated via an opaque `after` cursor, mirroring the real API's shape. */
function makeFakeSource(pagesPerListing: Record<string, number>) {
  const store = new Set<string>();
  const fetchPage = async (spec: ListingSpec, after: string | null) => {
    const pageNum = after ? parseInt(after, 10) : 0;
    const totalPages = pagesPerListing[spec.listing] ?? 0;
    if (pageNum >= totalPages) return { posts: [], after: null };
    const posts = Array.from({ length: 100 }, (_, i) => makePost(`${spec.listing}-${pageNum}-${i}`));
    const nextPage = pageNum + 1;
    const nextAfter = nextPage < totalPages ? String(nextPage) : null;
    return { posts, after: nextAfter };
  };
  const insertPosts = async (rows: Array<RawPost & { embedding: number[] | null }>) => {
    for (const r of rows) store.add(r.id);
  };
  const getCount = async () => store.size;
  return { fetchPage, insertPosts, getCount, store };
}

describe("runFetchStep", () => {
  it("pulls multiple pages within the per-step budget and stays in the same listing", async () => {
    const source = makeFakeSource({ new: 5, hot: 5, rising: 5 });
    const result = await runFetchStep({ listingIndex: 0, listingAfter: null }, 10000, {
      listings: LISTINGS,
      fetchPage: source.fetchPage,
      embed: async () => null,
      insertPosts: source.insertPosts,
      getCount: source.getCount,
      maxPagesPerStep: 3,
    });
    expect(result.done).toBe(false);
    expect(result.listingIndex).toBe(0); // still within 'new' (only pulled 3 of 5 pages)
    expect(result.listingAfter).toBe("3");
    expect(result.fetchedCount).toBe(300);
  });

  it("advances to the next listing when the current one runs out mid-step", async () => {
    const source = makeFakeSource({ new: 2, hot: 5, rising: 5 });
    const result = await runFetchStep({ listingIndex: 0, listingAfter: null }, 10000, {
      listings: LISTINGS,
      fetchPage: source.fetchPage,
      embed: async () => null,
      insertPosts: source.insertPosts,
      getCount: source.getCount,
      maxPagesPerStep: 5,
    });
    // 'new' exhausts after 2 pages, then 3 more pages come from 'hot' (5 total pages pulled)
    expect(result.fetchedCount).toBe(500);
    expect(result.listingIndex).toBe(1); // now in 'hot'
    expect(result.listingAfter).toBe("3");
  });

  it("reports done once the target post count is reached", async () => {
    const source = makeFakeSource({ new: 10, hot: 10, rising: 10 });
    const result = await runFetchStep({ listingIndex: 0, listingAfter: null }, 250, {
      listings: LISTINGS,
      fetchPage: source.fetchPage,
      embed: async () => null,
      insertPosts: source.insertPosts,
      getCount: source.getCount,
      maxPagesPerStep: 10,
    });
    expect(result.done).toBe(true);
    expect(result.fetchedCount).toBeGreaterThanOrEqual(250);
  });

  it("reports done once every listing is exhausted, even under target", async () => {
    const source = makeFakeSource({ new: 1, hot: 1, rising: 1 });
    const result = await runFetchStep({ listingIndex: 0, listingAfter: null }, 10000, {
      listings: LISTINGS,
      fetchPage: source.fetchPage,
      embed: async () => null,
      insertPosts: source.insertPosts,
      getCount: source.getCount,
      maxPagesPerStep: 10,
    });
    expect(result.done).toBe(true);
    expect(result.fetchedCount).toBe(300); // 1 page x 100 posts x 3 listings
    expect(result.listingIndex).toBe(3);
  });

  it("resumes correctly from a persisted mid-listing state across multiple step calls", async () => {
    const source = makeFakeSource({ new: 6, hot: 2, rising: 1 });
    let state = { listingIndex: 0, listingAfter: null as string | null };
    let done = false;
    let steps = 0;
    while (!done && steps < 20) {
      const result = await runFetchStep(state, 10000, {
        listings: LISTINGS,
        fetchPage: source.fetchPage,
        embed: async () => null,
        insertPosts: source.insertPosts,
        getCount: source.getCount,
        maxPagesPerStep: 2, // small budget forces many resumptions
      });
      state = { listingIndex: result.listingIndex, listingAfter: result.listingAfter };
      done = result.done;
      steps++;
    }
    expect(done).toBe(true);
    expect(source.store.size).toBe(900); // (6+2+1) pages x 100
    expect(steps).toBeGreaterThan(1); // confirms it actually took multiple steps
  });

  it("skips a listing whose first page comes back empty", async () => {
    const source = makeFakeSource({ new: 0, hot: 2, rising: 0 });
    const result = await runFetchStep({ listingIndex: 0, listingAfter: null }, 10000, {
      listings: LISTINGS,
      fetchPage: source.fetchPage,
      embed: async () => null,
      insertPosts: source.insertPosts,
      getCount: source.getCount,
      maxPagesPerStep: 10,
    });
    expect(result.done).toBe(true);
    expect(result.fetchedCount).toBe(200);
  });
});
