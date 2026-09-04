## Context

The composed recovery seam, cache core, and change-stream manager provide the prerequisites for user-visible cached reads. The API is deliberately narrower than transparent interception of all PyMongo methods.

## Goals / Non-Goals

**Goals:** Provide equivalent sync/async reads, identity-aware aliases, safe generic result caching, and raw escape hatches.

**Non-Goals:** This change does not cache writes, change sessions, or admit partially consumed cursor data.

## Decisions

- Wrap supplied PyMongo collections; expose raw collections for unsupported operations.
- Treat `_id` and declared simple/compound unique keys as document aliases. Cache other fully materialized results behind database generations so writes conservatively invalidate membership and ordering.
- Force eligible cache-admitted reads to primary plus majority. If the caller selected a secondary or non-majority read profile on the wrapped collection or operation, bypass both cache lookup and admission and preserve the caller's PyMongo read options.
- Admit `find`/aggregate only after complete materialization and capacity validation. Sync and asyncio share behavioral tests but use native driver APIs.

## Risks / Trade-offs

- [Generic result invalidation is broad] → Database-generation invalidation favors correctness over hit rate.
- [Materialization uses local memory] → Apply cache-core entry limits and never admit partial or oversize results.

## Migration Plan

Implement sync identity reads first, add bounded generic reads, then establish asyncio parity and ownership/error tests against independent raw writers.
