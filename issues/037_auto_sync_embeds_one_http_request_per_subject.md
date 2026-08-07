# Auto-Sync Embeds One HTTP Request Per Subject Instead of Batching

## Status: OPEN

The vector auto-sync write path issues **one embeddings API request per
subject**, 8 at a time, when the provider already supports batching 100 texts
into a single request. Writing an entity graph therefore produces one HTTP round
trip per entity, frame, slot and edge covered by the vector index.

## Symptom

A burst of single-item embedding calls during any KG write, visible in the app
log as 8-15 responses landing within a few hundred milliseconds, interleaved
with event-loop stall warnings:

```
01:29:12.159 httpx  HTTP Request: POST https://api.openai.com/v1/embeddings "HTTP/1.1 200 OK"
01:29:12.187 vitalgraph.utils.event_loop_monitor  ⚠️ EVENT LOOP STALL: blocked for 224ms
                                                  (expected sleep 50ms, actual 274ms) [stall #188]
01:29:12.260 httpx  HTTP Request: POST https://api.openai.com/v1/embeddings "HTTP/1.1 200 OK"
01:29:12.358 httpx  HTTP Request: POST https://api.openai.com/v1/embeddings "HTTP/1.1 200 OK"
01:29:12.398 httpx  HTTP Request: POST https://api.openai.com/v1/embeddings "HTTP/1.1 200 OK"
01:29:12.405 httpx  HTTP Request: POST https://api.openai.com/v1/embeddings "HTTP/1.1 200 OK"
...
```

Observed while bulk-loading the 100-file lead dataset through the REST API.

## Root cause

`vitalgraph/vectorization/auto_sync.py`, `_sync_vectors_for_subjects`
(`_VECTOR_CONCURRENCY = 8` at line 53):

```python
# Phase 3: Concurrent embedding with bounded parallelism
sem = asyncio.Semaphore(_VECTOR_CONCURRENCY)
embeddings: List[Optional[List[float]]] = [None] * len(to_embed)

async def _embed(idx: int, text: str):
    async with sem:
        try:
            embeddings[idx] = await provider.vectorize_text(text)   # ← one text
        except Exception as e:
            logger.warning(...)

await asyncio.gather(*[
    _embed(i, text) for i, (_, text) in enumerate(to_embed)
])
```

and `OpenAIProvider.vectorize_text` sends exactly one item:

```python
async def vectorize_text(self, text: str) -> List[float]:
    response = await self._client.embeddings.create(
        input=[text], model=self._model_name_str, dimensions=self._dim)
    return response.data[0].embedding
```

So `len(to_embed)` requests are issued, 8 concurrently — which is precisely the
burst pattern above.

## The batching already exists and is already configured

The same provider has a batching method, and the provider is constructed with a
batch size of 100 (confirmed in the log):

```
vitalgraph.vectorization.openai_provider - __init__ - INFO -
  OpenAIProvider initialized: model=text-embedding-3-small, dims=1536, batch_size=100
```

```python
async def vectorize_texts(self, texts: List[str]) -> List[List[float]]:
    """Handles batching internally if len(texts) > batch_size."""
    for i in range(0, len(texts), self._batch_size):     # DEFAULT_BATCH_SIZE = 100
        response = await self._client.embeddings.create(
            input=batch, model=self._model_name_str, dimensions=self._dim)
```

Every other bulk caller already uses it:

- `entity_registry/entity_registry_vector_populator.py:250, 349`
- `agent_registry/agent_registry_vector_populator.py:165`

**Only the auto-sync write path calls the single-text method in a loop.**

## Fix

`to_embed` is already a materialized list at that point, so the whole
semaphore/gather block collapses to one call:

```python
texts = [text for _, text in to_embed]
embeddings = await provider.vectorize_texts(texts)
```

For 100 subjects that is **1 request instead of 100** (currently 13 waves of 8).
The provider chunks internally, so arbitrarily large batches stay safe.

Two behaviours to preserve when making the change:

1. **Per-item error isolation.** Today one failed embed logs a warning and
   leaves `embeddings[idx] = None`, and Phase 4 skips that subject — the rest
   still get written. A single `vectorize_texts` call fails the whole batch. If
   that matters, fall back to per-item on batch failure, or chunk and catch per
   chunk.
2. **Ordering.** `vectorize_texts` documents that results come back in input
   order, and Phase 4 zips `embeddings[i]` against `to_embed[i]`, so the
   existing index-based upsert keeps working unchanged.

## Secondary effect: event-loop stalls

The stall warnings interleaved with the bursts are consistent with this pattern:
8 concurrent HTTPS responses, each carrying a 1536-float JSON array, is a lot of
parse-and-decode work landing on the loop thread at once. Fewer, larger
responses should cut the number of wakeups substantially — though the total JSON
volume is unchanged, so this is expected to reduce rather than eliminate the
stalls. Worth re-measuring after the change rather than assuming.

## Other per-item callers

- `vitalgraph/vectorization/vector_populator.py:443` — `embedding = await
  provider.vectorize_text(text)` in the per-subject populate path. Same
  treatment applies where it is driven over a set of subjects.
- `vitalgraph/db/sparql_sql/vg_resolve.py:84` — **legitimately single-text**: it
  embeds one search string per query at query time. Leave as is.

## Reproduce

Load any multi-object entity graph through the REST API with an OpenAI-backed
vector index configured on the space, and watch the app log:

```bash
docker logs -f vitalgraph-test-app 2>&1 | grep -E "embeddings|EVENT LOOP STALL"
```

The lead dataset loader (`test_scripts/vitalgraph_client_test/test_sparql_sql_lead_dataset.py`,
100 entities / 192,810 triples) reproduces it continuously for several minutes.
