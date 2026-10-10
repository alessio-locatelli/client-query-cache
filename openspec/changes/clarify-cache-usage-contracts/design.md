# Design

## Context

See [proposal.md](proposal.md). This change fulfills `public-library-documentation` rather than introducing behavior; its metadata skips deltas. The detailed API method section, cached-read guide, asyncio tutorial, and Context7 already distinguish immediate `find()` cursors from awaited `aggregate()`. The error table already restricts `UnsupportedCacheRequestError` to explicit low-level misuse. The contradictory summaries are therefore corrections, not open API decisions.

## Goals / Non-Goals

Give each detailed contract one canonical guide and use links elsewhere. Avoid new generators, user-visible internal state diagrams, promises of bounded staleness, and a general documentation rewrite.

## Decisions

Use the API's cached-read section for one method table covering all six reads: synchronous return, async invocation, and execution timing. Link the introduction to it. The four single-result methods are awaited; `find()` returns immediately and executes on consumption; awaited `aggregate()` executes its initial command before returning a cursor. Keep the existing cursor paragraphs for consumption, errors and admission; the table does not duplicate the detailed eligibility catalogue.

Keep the API error table canonical and replace deployment's incorrect exception examples with a short distinction and link. Include native cursor-only bypasses and unchanged PyMongo exceptions. Generated documentation would require an extra structured source or parsing tool with no benefit for two summaries; manual concise references are sufficient. There are no unknowns requiring research.

Keep the README's value-led heading and tiny usage example. Replace the absolute "Built for production" label with concrete test and regression-check evidence; present coverage as a project policy, not operational proof. Keep asynchronous invalidation visible and link consistency guidance. A technical slogan as the heading adds jargon while the existing caveat already establishes the model, so a heading replacement is unnecessary.

The tiny README example writes its document through the PyMongo collection before reading it twice. Against a fresh database the unseeded example only records `missing_collection` bypasses, so it never shows the repeated read it describes. An idempotent upsert into the quick-start tutorials' dedicated `client_query_cache_tutorial.items` collection keeps the example rerunnable, cannot modify application data in a generic namespace, and shows the write/read handle split. Printing counters and explaining stream startup stay in the quick-start tutorials and monitoring guide: the read that starts a database stream waits for it, so a sequential example's first read is a miss rather than a startup bypass.

The API ownership section should retain supported lifecycle and the warning that manually sharing a core between coordinators is unsupported. Move the internal availability-flag explanation to `docs/development/architecture.md`, linking its repository source for advanced readers. Removing the warning would conceal a real misuse boundary; keeping the full internal explanation burdens ordinary callers. No additional research is necessary.

At the entry to the example catalogue, distinguish demonstrations from recommendations: authorization policies and Celery task state can lag invalidation. Link the existing py-abac warning and add a short Celery caveat where its task-polling behavior is introduced. A future catalogue application can be promoted when it exists; this change must not publish a dead link to planned content.

## Risks / Trade-offs

- Successful query delivery can be mistaken for admission. Add one plain-language pointer from the cached-read guide to complete-consumption and bypass rules, without recopying them.
- Rewriting unrelated correct guidance increases drift. Leave majority-read-concern explanation, existing read-after-write example, capacity estimate, OTel example and rollback instructions intact.
- Other active changes may edit the same guides. Reconcile against their implemented contracts at apply time rather than copying their planned wording now.
