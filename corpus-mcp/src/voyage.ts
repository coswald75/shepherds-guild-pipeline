import type { Env } from "./types";

// Voyage embedding client. We use the asymmetric `query` input type so the
// search-time embedding matches how units were embedded at decomposition
// (input_type: "document"). Mismatched input types degrade retrieval
// significantly — leave this alone unless the ingest side changes too.
//
// Wraps fetch with AbortController so a hung Voyage response surfaces as a
// real error (with elapsed time in the message) instead of a bare client
// timeout. This was the original suspected root cause of the search hang
// before the actual culprit (missing/ignored vector index) was found.

const VOYAGE_TIMEOUT_MS = 6000;

export async function embedQuery(query: string, env: Env): Promise<number[]> {
  const start = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), VOYAGE_TIMEOUT_MS);

  try {
    const resp = await fetch("https://api.voyageai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.VOYAGE_API_KEY}`,
      },
      body: JSON.stringify({
        input: [query],
        model: env.VOYAGE_MODEL,
        output_dimension: Number(env.VOYAGE_DIMENSIONS),
        input_type: "query",
      }),
      signal: controller.signal,
    });

    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(
        `Voyage embed failed (${resp.status}) after ${Date.now() - start}ms: ${txt}`,
      );
    }
    const data = (await resp.json()) as { data: { embedding: number[] }[] };
    const embedding = data?.data?.[0]?.embedding;
    if (!Array.isArray(embedding)) {
      throw new Error(
        `Voyage returned an unexpected payload shape after ${Date.now() - start}ms`,
      );
    }
    console.log(
      `[voyage] embedded query in ${Date.now() - start}ms (${embedding.length} dims)`,
    );
    return embedding;
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      throw new Error(
        `Voyage embed timed out after ${VOYAGE_TIMEOUT_MS}ms (limit ${VOYAGE_TIMEOUT_MS / 1000}s)`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
