# Design

## Context

See [proposal.md](proposal.md) for motivation and the two delta specs for the contracts. The following facts shape the approach:

- Most of the roughly 210 trailing comments state ranges, emptiness, or lengths. They are concentrated in the `benchmarks/stream_cost` data models and `tests/stress/helpers.py`, with a few in `src/` fields and parameters. Other comments record override rationales, test-value choices required by the `test-value-conventions` spec, or behavior. Those comments are not type prose.
- The repository has about 620 `dict[str, Any]` and 210 `dict[str, object]` annotations. Every `dict[str, Any]` in `src/` is a keyword-argument bundle unpacked into a PyMongo call. BSON documents and JSON objects occur in `tests/` and `benchmarks/`.
- Ruff selects `ALL`, including flake8-type-checking. With the Python 3.14 target, Ruff requires an alias used only in annotations, including dataclass fields, to be imported under `TYPE_CHECKING`.
- covdefaults measures every module under the source tree. A library module that no test imports at runtime is reported as uncovered.
- The documentation build runs `scripts/` with `uv run --only-group docs`, so the project and its dependencies are not installed there.
- `annotated-types` 0.8.0 is already locked as a transitive development dependency and ships `py.typed`. Hypothesis's `from_type` resolves PEP 695 aliases that carry its metadata into bounded strategies, and strict mypy accepts a generic alias whose type parameter is bound to `Sized`.

## Goals / Non-Goals

**Goals:** Make the repository-wide convention mechanical enough to apply file by file, keep mypy's checking strength at least as strong as it is today, and add no runtime cost to production imports.

**Non-Goals:** No runtime enforcement: a runtime type checker would add call overhead on read paths, and the existing explicit checks already validate caller input. Read-only `Mapping[str, Any]` parameters that mirror PyMongo signatures keep their annotations, because narrowing their values would add `isinstance` work to filter traversal on read paths. Closed value sets such as stream phases are not converted to `Literal`. The runnable examples are standalone user-facing scripts and must not import private modules.

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
| `BsonValue`, `BsonDict`              | `object`, `dict[str, BsonValue]`       | BSON documents                                                  |
| `JsonDict`                           | `dict[str, object]`                    | JSON objects                                                    |

Notes on the alias set:

- `Text` serves two purposes. Its minimum length distinguishes prose from single-character strings. It also marks a parameter as one string rather than an iterable of strings. With metadata-only annotations, mypy still accepts `"abc"` where `Iterable[Text]` is expected, so the second purpose serves readers and Hypothesis rather than static checking.
- `BsonValue` and `JsonDict` use `object` values rather than `Any`, so mypy keeps checking value use; `Any` would silently disable checks at the roughly 210 sites already typed `dict[str, object]`. Converting `dict[str, Any]` document sites surfaces errors of two kinds: dict invariance at insert sites and unnarrowed value access. Annotating document literals with `BsonDict` fixes the first group. Narrowing at the access site fixes the second: tests prefer `assert isinstance(...)`, which is checked at runtime, over `cast`.
- `MaxAwaitTimeMs` imports the existing bound constant, so the limit has one source.

Alternatives considered:

- A public `client_query_cache.types` module would let users import these aliases. However, it would commit the project to alias names as API without any user need. Rejected.
- Per-tree alias modules would duplicate definitions. Rejected under DRY.
- An unshipped repository-level module cannot be imported by library code. Rejected.
- The chosen module ships the BSON and JSON aliases even though only tests and benchmarks use them. This costs a few definition lines in the wheel and nothing at runtime. Accepted.
- `NewType` ranges were considered. They would require a wrapping call at every construction site, including hot paths, and would carry no machine-readable bounds. Rejected.
- `annotated_types.Doc` metadata could hold sentinel meanings. It would move prose into annotations without making that prose checkable. Rejected.

No research is needed: the tool behavior listed under Context settles this decision.

### Import discipline and the dependency

Library and script modules import aliases only under `TYPE_CHECKING`, and Ruff enforces this for uses in annotations only. As a result, a production `import client_query_cache` does not load `_types` or `annotated_types`, and the docs build can run `scripts/` without the project installed.

`_types` itself imports `annotated_types` at runtime, so that alias values resolve for Hypothesis and any tool that evaluates them. This makes `annotated-types>=0.8.0` a published runtime dependency. The floor is the version the suite exercises, and following existing policy it has no upper bound.

- A development-only dependency would leave alias evaluation raising `NameError`, which breaks `from_type`. Rejected.
- Importing `annotated_types` in each consuming module would add its import cost to every production import. Rejected.
- A lower, untested floor would need a minimum-version lane like `pymongo-min`. That is disproportionate for a few stable metadata classes. Not pursued.

No research is needed.

### Coverage through the property test

The property tests required by the `property-based-testing` delta import aliases at runtime for `st.from_type`. This executes `_types` in the test run and ties the public annotations to their validators. The tests draw from the aliases rather than calling `st.builds` on the configuration classes. Those classes import their aliases under `TYPE_CHECKING`, so their field annotations cannot be resolved at runtime. As a consequence, the test cannot detect a field that switches to a different alias. Review covers that case.

- Omitting `_types.py` from coverage would hide drift and need an override rationale. Rejected.
- An artificial runtime import in library code would contradict the import discipline above. Rejected.

No research is needed.

### Classifying prose

Each comment clause is handled by the first rule that applies:

1. A clause that states sign, bounds, emptiness, or length becomes the alias and is deleted, for example "Positive window count" or "Nonempty execution models".
2. A clause that only says a bare value can be zero, negative, signed, or empty, or that explains why a collection starts empty, is deleted, for example "Can be empty" or "Filled by repetitions".
3. A clause that states meaning is kept, for example "Zero denotes unlimited" or "None means unavailable". An index base is not kept as meaning when the range already implies it: "Zero-based block index" becomes `NonNegativeInt`.

If a comment has no clause left, it is removed.

### Public interfaces

`CacheCoreConfig` budgets and the lag-window counts use the ranges that `__post_init__` enforces, and the manager `max_await_time_ms` parameters use `MaxAwaitTimeMs`. Snapshot counters and byte totals use `NonNegativeInt`, and the configured budgets that snapshots echo use `PositiveInt`. Lag-window floats stay bare, because they include an unmeasured clock offset between hosts that can make them zero or negative. Internal code without type prose is converted only where it receives a public value directly. A repository-wide sweep of bare `int` would add churn and little clarity.

### Local alias cleanup

`scripts/build_versioned_docs.py` defines a `Text = str` that admits empty strings and conflicts with the shared name. Its uses, including the importing test, become bare `str`, and `Table` loses its emptiness comment. Test-local `Document = dict[str, Any]` aliases that denote BSON documents are replaced by `BsonDict`, so there is one document alias.

### Guidance location

A single bullet in the `AGENTS.md` development guidelines points to the alias module and states the bare-annotation convention, because coding rules for contributors and agents live there. Public guides and Context7 rules are unaffected, because the public static types do not change.

## Risks / Trade-offs

- [Internal annotations drift from actual ranges] → The property test covers only public configuration. Internal aliases rely on review, as their comments do today.
- [A large mechanical diff conflicts with active branches] → Commit per tree. The active `validate-cache-numeric-configuration` change edits the same constructors: its exact-integer checks stay explicit, and these annotations only state ranges, so whichever change lands later rebases without changing semantics.
- [Users see private alias names when hovering over public signatures] → The static type is identical to `int`. Accepted.
- [Narrowing adds assertions to tests and benchmarks] → These are off the library's read paths. Accepted.
