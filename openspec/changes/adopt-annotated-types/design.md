# Design

## Context

See [proposal.md](proposal.md) for motivation and the two delta specs for the contracts. The following facts shape the approach:

- Most of the roughly 210 trailing comments state ranges, emptiness, or lengths. They are concentrated in the `benchmarks/stream_cost` data models and `tests/stress/helpers.py`, with a few in `src/` fields and parameters. Other comments record override rationales, test-value choices required by the `test-value-conventions` spec, or behavior. Those comments are not type prose.
- Ruff selects `ALL`, including flake8-type-checking. With the Python 3.14 target, Ruff moves an import used only in annotations, including dataclass fields, under `TYPE_CHECKING`, unless the module is listed in `lint.flake8-type-checking.exempt-modules`, whose default is `["typing"]`.
- `typing.get_type_hints` resolves the fields of every public dataclass (`CacheCoreConfig`, `CacheSnapshot`, `BypassReasonCount`, `StreamCostSnapshot`, `StreamHealthSnapshot`). It does not resolve public method signatures such as `CacheManager.__init__`, because their parameter types are imported under `TYPE_CHECKING`.
- The documentation build runs `scripts/` with `uv run --only-group docs`, so the project and its dependencies are not installed there.
- `annotated-types` 0.8.0 is already locked as a transitive development dependency and ships `py.typed`. Hypothesis's `from_type` resolves PEP 695 aliases that carry its metadata into bounded strategies, and strict mypy accepts a generic alias whose type parameter is bound to `Sized`.

## Goals / Non-Goals

**Goals:** Make the convention mechanical enough to apply file by file, and keep public dataclass annotations as introspectable as they are today.

**Non-Goals:** No runtime enforcement: a runtime type checker would add call overhead on read paths, and the existing explicit checks already validate caller input. Closed value sets such as stream phases are not converted to `Literal`. The runnable examples are standalone user-facing scripts and must not import private modules.

## Decisions

### Alias module

All aliases live in a private module at `src/client_query_cache/_types.py`. It is the only module that imports `annotated_types`, and it contains no comments, per the project's no-code-prose rule. The rationale for each alias lives in this file.

| Alias                                | Definition                             | Use for                                                         |
| ------------------------------------ | -------------------------------------- | --------------------------------------------------------------- |
| `PositiveInt`, `PositiveFloat`       | `Gt(0)`                                | counts, sizes, durations, limits, one-based ranks               |
| `NonNegativeInt`, `NonNegativeFloat` | `Ge(0)`                                | counters and timestamps that can be zero, zero-based indexes    |
| `Probability`                        | `Interval(ge=0, le=1)`                 | p-values                                                        |
| `ExclusiveProbability`               | `Interval(gt=0, lt=1)`                 | tail probabilities and confidence levels                        |
| `MaxAwaitTimeMs`                     | `Interval(ge=1, le=MAX_AWAIT_TIME_MS)` | the public stream await-time parameter                          |
| `NonEmptyStr`                        | `MinLen(1)`                            | identifiers and names, where one character is valid             |
| `Text`                               | `MinLen(2)`                            | human-readable messages, rationales, and descriptions           |
| `NonEmpty[T: Sized]`                 | `MinLen(1)`                            | nonempty collections, for example `NonEmpty[list[PositiveInt]]` |

Notes on the alias set:

- `Text` serves two purposes. Its minimum length distinguishes prose from single-character strings. It also marks a parameter as one string rather than an iterable of strings. With metadata-only annotations, mypy still accepts `"abc"` where `Iterable[Text]` is expected, so the second purpose serves readers and Hypothesis rather than static checking.
- Integer aliases state the static type `int` and a range. The exact built-in-integer rule of the `validate-cache-numeric-configuration` change, which rejects booleans and integer subclasses, is not expressible as metadata and stays a validation rule.
- `MaxAwaitTimeMs` imports the existing bound constant, so the limit has one source.

Alternatives considered:

- A public `client_query_cache.types` module would let users import these aliases. However, it would commit the project to alias names as API without any user need. Rejected.
- Per-tree alias modules would duplicate definitions. Rejected under DRY.
- An unshipped repository-level module cannot be imported by library code. Rejected.
- `NewType` ranges were considered. They would require a wrapping call at every construction site, including hot paths, and would carry no machine-readable bounds. Rejected.
- `annotated_types.Doc` metadata could hold sentinel meanings. It would move prose into annotations without making that prose checkable. Rejected.

No research is needed: the tool behavior listed under Context settles this decision.

### Runtime imports and the dependency

Every consumer in `src/`, `tests/`, and `benchmarks/` imports aliases at runtime. `ruff.toml` sets `exempt-modules = ["typing", "client_query_cache._types"]`, with a rationale comment in the development-environment override format, so that flake8-type-checking does not move these imports under `TYPE_CHECKING`. As a result, public dataclass annotations keep resolving at runtime, as the `type-annotations` delta requires. Package import now loads `annotated_types`. This is a one-time cost of a few milliseconds next to the PyMongo-dominated package import; task 4.1 records the measurement. Because the shipped package imports it at runtime, `annotated-types>=0.8.0` is a published runtime dependency. The floor is the version the suite exercises, and following existing policy it has no upper bound.

`scripts/` does not import library aliases, because the docs build runs it without the project installed.

- Type-checking-only imports with a development-only dependency would avoid the import cost. However, `get_type_hints` on the public configuration and snapshot dataclasses would raise `NameError`. That breaks tools that introspect dataclass fields, for example configuration loaders, and prevents the property tests from deriving strategies from real annotations. Rejected.
- Runtime imports only in modules that define public dataclasses would save nothing, because package import already loads `_types` through them, and two import rules would replace one. Rejected.
- Ruff's `runtime-evaluated-decorators = ["dataclasses.dataclass"]` would also reclassify every existing `TYPE_CHECKING` import used in any dataclass annotation as a runtime import. Rejected.
- A lower, untested floor would need a minimum-version lane like `pymongo-min`. That is disproportionate for a few stable metadata classes. Not pursued.

No research is needed.

### Property tests

The property tests resolve `CacheCoreConfig` and `LagCaptureWindowConfig` field annotations with `typing.get_type_hints` and pass each resolved annotation to `st.from_type`. As a result, a field that switches to a wider alias fails the test. Hypothesis draws built-in integers only, so these tests do not cover the exact-type rule, which the boundary tests of `validate-cache-numeric-configuration` cover. The `max_await_time_ms` parameter is not derivable this way, because the manager signatures do not resolve at runtime. Its existing parametrized boundary tests remain, and its annotation relies on review.

A separate parametrized test calls `get_type_hints(..., include_extras=True)` on every dataclass exported by `client_query_cache` and `client_query_cache.asynchronous`.

No research is needed.

### Classifying prose

Each comment clause is handled by the first rule that applies:

1. A clause that states sign, bounds, emptiness, or length becomes the alias and is deleted, for example "Positive window count" or "Nonempty execution models".
2. A clause that only says a bare value can be zero, negative, signed, or empty, or that explains why a collection starts empty, is deleted, for example "Can be empty" or "Filled by repetitions".
3. A clause that states meaning is kept, for example "Zero denotes unlimited" or "None means unavailable". An index base is not kept as meaning when the range already implies it: "Zero-based block index" becomes `NonNegativeInt`.

If a comment has no clause left, it is removed.

### Public interfaces

`CacheCoreConfig` budgets and the lag-window counts use the ranges that `__post_init__` enforces, and the manager `max_await_time_ms` parameters use `MaxAwaitTimeMs`. Snapshot counters and byte totals use `NonNegativeInt`, and the configured budgets that snapshots echo use `PositiveInt`. Lag-window floats stay bare, because they include an unmeasured clock offset between hosts that can make them zero or negative. Internal code without type prose is converted only where it receives a public value directly. A repository-wide sweep of bare `int` would add churn and little clarity.

### Narrowing

If a changed annotation requires narrowing, tests prefer `assert isinstance(...)`, which is checked at runtime. `cast(...)` is a runtime function call, so it is allowed only where it runs once or a few times per application lifetime, such as configuration loading or report assembly. It is banned on hot paths, including cached-read paths and benchmark measurement loops.

### Local alias cleanup

`scripts/build_versioned_docs.py` defines a `Text = str` that admits empty strings and conflicts with the shared name. Its uses, including the importing test, become bare `str`, and `Table` loses its emptiness comment.

### Guidance location

A single bullet in the `AGENTS.md` development guidelines points to the alias module and states the bare-annotation convention, because coding rules for contributors and agents live there. Public guides and Context7 rules are unaffected, because the public static types do not change.

## Risks / Trade-offs

- [Internal annotations drift from actual ranges] → The property tests cover only the configuration dataclasses. Internal aliases rely on review, as their comments do today.
- [Package import loads one more module] → The cost is one-time and off every read path. Task 4.1 measures it before acceptance.
- [The mechanical diff conflicts with active branches] → Commit per tree. The active `validate-cache-numeric-configuration` change edits the same constructors: its exact-integer checks stay explicit, and these annotations only state ranges, so whichever change lands later rebases without changing semantics.
- [Users see private alias names when hovering over public signatures] → The static type is identical to `int`. Accepted.
