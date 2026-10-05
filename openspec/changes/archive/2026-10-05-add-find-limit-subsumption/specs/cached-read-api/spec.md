# Spec Delta

## ADDED Requirements

### Requirement: Positive find limits can reuse complete covering results

Both execution models SHALL satisfy a cache-eligible `find()` with a positive integer limit from a valid complete result whose declared limit is an equal or larger positive integer, or zero for unlimited. All other cache-relevant inputs SHALL match. The returned result SHALL be the source's prefix of at most the requested length. Boolean and negative limits SHALL NOT participate in compatible lookup.

#### Scenario: A larger limited result supplies a prefix

- **WHEN** `find(filter, sort=[("_id", 1)], limit=100)` is fully consumed and admitted, then the otherwise identical `limit=10` cursor is consumed
- **THEN** it returns the first ten source documents without issuing a MongoDB find or getMore command, in both synchronous and asyncio APIs

#### Scenario: An unlimited complete result supplies a prefix

- **WHEN** an omitted-limit or integer `limit=0` result is fully consumed and admitted, then the otherwise identical `limit=10` cursor is consumed
- **THEN** it returns at most ten documents from that result without another MongoDB read

#### Scenario: A covering result contains fewer documents than requested

- **WHEN** a complete cached `limit=100` result has three documents, or is empty, and an otherwise identical `limit=10` cursor is consumed
- **THEN** it returns those three documents or the empty result without another MongoDB read

#### Scenario: A smaller limit cannot supply a larger request

- **WHEN** only a complete `limit=10` result is cached and an otherwise identical `limit=100` cursor is consumed
- **THEN** the request executes a MongoDB find command even if the smaller result exhausted all matching documents

#### Scenario: Unlimited and negative requests retain exact lookup

- **WHEN** a request has an omitted, zero, negative, or boolean limit and no exact entry, but a different-limit result is cached
- **THEN** it does not use compatible-result lookup and retains native execution and existing exact-key behavior

#### Scenario: Negative sources are not covering entries

- **WHEN** a complete negative-limit result is cached and a positive-limit query is consumed without an exact entry
- **THEN** that single-batch source cannot supply a compatible hit

### Requirement: Find compatibility preserves all remaining query boundaries

Compatible-result lookup SHALL use the final pre-execution filter representation, projection, ordered sort, skip, collation, codec profile, namespace, and all other cache-relevant inputs. Unsupported options SHALL retain existing bypass behavior. This change SHALL NOT introduce filter equivalence, normalize other query properties, or reuse aggregation results.

#### Scenario: Another output-affecting input differs

- **WHEN** a candidate differs in filter, projection, sort, skip, collation, codec profile, collection, or database from the positive-limit request
- **THEN** it is not a compatible source, and absent another matching source the request issues a MongoDB find command

#### Scenario: An unsupported cursor option follows warming

- **WHEN** a caller requests explicit batching, a hint, comment, session, or another unsupported cursor option after warming a covering result
- **THEN** native execution and validation occur without a compatible hit or admission

#### Scenario: Chained options determine the prefix request

- **WHEN** a caller sets sort, skip, collation, or limit through native chaining before consuming a cursor
- **THEN** compatibility uses the final shape rather than the constructor shape

### Requirement: Compatible cursors preserve isolation and native lifecycle

A compatible hit SHALL use the existing native cursor subclass with its usual validation, laziness, consumption, cleanup, clone, rewind, and started-snapshot contracts. Its private buffer SHALL contain only the requested isolated prefix, and `retrieved` SHALL count that loaded prefix. Consuming the hit SHALL NOT admit a duplicate prefix entry.

#### Scenario: A caller mutates a narrower hit

- **WHEN** a caller changes a nested value returned by a compatible `limit=10` hit
- **THEN** the resident source and later narrow and source-limit hits retain their original values

#### Scenario: Prefix metadata describes a local cursor

- **WHEN** a compatible cursor loads ten documents from a hundred-document source
- **THEN** `retrieved` is ten, `cursor_id` is zero, no server address or session is created, and exhausting or closing the cursor needs no remote cleanup

#### Scenario: A started prefix is invalidated

- **WHEN** invalidation occurs after the compatible cursor starts consuming its prefix
- **THEN** that cursor retains its isolated snapshot and a subsequent execution cannot reuse the invalidated source

#### Scenario: A source cursor is only partially consumed

- **WHEN** the caller consumes ten documents from a cold `limit=100` or unlimited cursor and closes it
- **THEN** that incomplete execution supplies no compatible result to a later narrower cursor
