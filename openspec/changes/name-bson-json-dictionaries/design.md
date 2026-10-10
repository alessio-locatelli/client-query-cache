# Design

## Context

See [proposal.md](proposal.md) for motivation and the delta spec for the contract. The following facts shape the approach:

- `tests/` and `benchmarks/` contain about 620 `dict[str, Any]` and 210 `dict[str, object]` annotations. About 520 of them are document type arguments of PyMongo clients and collections or of the library's cached collections and managers.
- Every `dict[str, Any]` in `src/` is a keyword-argument bundle unpacked into a PyMongo call, so the library has no document annotations to convert.
- Annotating `dict[str, Any]` documents with object values causes two kinds of mypy errors. Literals passed to insert methods are inferred as narrower dictionaries such as `dict[str, str]`, which dict invariance rejects. Values read from documents need narrowing before use.
- `adopt-annotated-types` provides the private alias module `client_query_cache._types`, which every consumer imports at runtime, and the `AGENTS.md` rule that restricts `cast(...)` to code that runs a few times per application lifetime.

## Goals / Non-Goals

**Goals:** Distinguish documents from option dictionaries by name, and extend mypy's value checking to the document sites that currently use `Any`.

**Non-Goals:** No document-shape guarantees. The aliases name a role: `JsonDict` admits values that `json.dumps` cannot serialize, and `BsonDict` admits values that BSON cannot encode.

## Decisions

### Alias definitions

`_types` gains `BsonValue = object`, `BsonDict = dict[str, BsonValue]`, and `JsonDict = dict[str, object]`.

- `Any` values would keep every current site compiling, but would also remove checking from the sites already typed `dict[str, object]`. Rejected.
- Precise recursive unions of BSON or JSON value types would add shape guarantees. However, PyMongo's own signatures accept and return `Mapping[str, Any]`, so every boundary would need narrowing or casts, and dict invariance would reject most literals unless each one is annotated. That cost is out of proportion to test and benchmark code. Rejected.
- Defining the aliases in `tests/` or `benchmarks/` would keep them out of the wheel, but one tree would then import its types from the other. Keeping a single alias module costs three definition lines in the wheel and nothing at runtime. Rejected.

No research is needed.

### Classification

- BSON: document type arguments of clients, collections, cached collections, managers, cursors, codec options, and change streams; documents that are inserted, read, or expected; query filters, projections, and pipeline stages; server command replies and index specifications; and change events.
- JSON: objects that are passed to `json.dumps` or decoded by `json.loads`, including benchmark reports and registered configurations.
- Unchanged: keyword-argument bundles and their `cast(...)` targets, `**`-unpacked dictionaries, captured call arguments, option dictionaries including collations and registered client options, read-only `Mapping` parameters such as decoded JSON schemas, OpenTelemetry attribute dictionaries, and inter-process messages. Inter-process messages include the shared-cache `Message` aliases, BSON frames and canonical wire nodes, the wire-tag registry, and the `Payload` aliases that also type pipe messages: in `benchmarks/stream_cost/multiprocess_run.py`, in the shared-cache window, worker, and diagnostics modules, and in `tests/shared_cache/conftest.py`.

The test-local `Document = dict[str, Any]` aliases in `tests/cursor_fixtures.py` and `tests/test_bound_sessions.py` and the `Document` alias in the shared-cache worker are replaced by `BsonDict`, so one document alias remains. Local `Payload` aliases that type only JSON objects are replaced by `JsonDict`.

### Narrowing

Annotating a literal with `BsonDict` resolves the invariance errors. Value access is narrowed with `assert isinstance(...)` in tests. Benchmarks and benchmark tests narrow nothing inside a timed region: a document read there is annotated with a `TypedDict` that states the fields the region reads, which costs no runtime work. Outside timed regions, `cast(...)` follows the `AGENTS.md` rule, and conversions the code already performed, such as `int()`, stay.

## Risks / Trade-offs

- [The diff touches most test files and conflicts with active branches] → Commit `tests/` and `benchmarks/` separately.
- [Narrowing assertions add lines to tests] → They also fail loudly when a document holds an unexpected type. Accepted.
