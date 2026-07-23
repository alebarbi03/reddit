import { embedOne } from "../src/lib/embeddings";

async function main() {
  const start1 = Date.now();
  const r1 = await embedOne("hello world");
  console.log("call1:", r1 === null ? "null (degraded gracefully)" : `vector len ${r1.length}`, `took ${Date.now() - start1}ms`);

  const start2 = Date.now();
  const r2 = await embedOne("hello world again");
  console.log("call2:", r2 === null ? "null (degraded gracefully)" : `vector len ${r2.length}`, `took ${Date.now() - start2}ms`);
}

main();
