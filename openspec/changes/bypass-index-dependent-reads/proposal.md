# Proposal

## Why

The cached views route MongoDB Search and Vector Search aggregations through a majority-read-concern miss, which the server rejects, so these reads fail through the cache while succeeding through PyMongo. Geospatial proximity reads and `$$USER_ROLES` can be admitted and then keep returning results that index or role changes have made stale, because neither change produces a collection write. `find_one` and `find` projections can also freeze `$rand`, `$function`, `$$NOW`, `$$CLUSTER_TIME` and `$$USER_ROLES` values, because projection classification checks only `$meta`.

## What Changes

- Execute MongoDB Search, Vector Search and search-index listing pipelines natively, with the caller's read concern and without cache lookup or admission.
- Bypass cache admission for geospatial proximity reads in aggregations and in `find_one`, `find`, `count_documents` and `distinct` filters.
- Bypass cache admission for reads that reference `$$USER_ROLES`.
- Bypass cache admission for `find_one` and `find` projections that use `$rand` or `$function`, or that reference `$$NOW` or `$$CLUSTER_TIME`.
- Record the existing `$text` exclusion as a requirement scenario; behavior is unchanged.
- Document these bypasses in the public bypass conditions and Context7 rules.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: search-backed aggregations execute natively; index- and role-dependent reads and variable projections bypass admission.

## Impact

`_core/read_validation.py` and its unit tests, the sync and async facade bypass tests, the bypass-conditions reference, the cached-reads guide, Context7 rules and the changelog. Bypasses report the existing `unsafe_pipeline`, `unsafe_filter` and `unsafe_projection` reasons; public types and metrics are unchanged. Applications lose caching only for the listed constructs.
