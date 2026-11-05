# Use cases

`client-query-cache` fits reads that many requests repeat between writes. These are often supporting data rather than the business operation itself: a destination description, a size guide, a depot address, or a job status. A hit avoids a database round trip. The application must also be able to show a preceding value while invalidation catches up, so prices, stock commitments and access decisions still need current checks. The [consistency guide](usage/consistency.md) defines that contract, and the [eligibility contract](reference/api.md#bypass-conditions) lists which reads can hit.

The scenarios below are hypothetical application designs, not accounts of production adoption. Each one shows a different decision about what to cache.

## Travel: reuse destination content across itineraries

A travel planner assembles weekend trips. One visitor searches for two adults in spring; another plans a family break in autumn. Their offers differ, but both may need the same destination introduction, airport details, and descriptions of local attractions. An editor maintains those documents in the database, and several pages reuse them: search cards, itinerary pages and saved trips.

If almost every visitor asks for a different itinerary, the complete search rarely repeats. The destination documents do repeat, whatever the dates and passenger counts. When an editor corrects a description, invalidation lets subsequent reads pick up the edit after the change event is processed.

```text
Traveller chooses dates and destination
                  |
          Assemble trip options
             /            \
   Destination content    Current offers
   Repeated cached read  Fresh supplier lookup
             \            /
              Trip overview
```

The offer itself has a different lifetime. Seat availability and the price accepted at booking need the reservation system's current checks.

## Retail: separate catalogue content from stock

A specialist outdoor shop releases a seasonal collection. Customers arrive from different campaigns, but many open the same jacket. Its material description, care instructions, photographs, and size guide change much less often than people view them. One size guide may also appear on several products.

Suppose every sale updates a stock counter inside the product document. Each sale changes that document, so even a cached read of its description loses reuse. If catalogue content and stock already have separate business lifecycles, separate documents let the content remain cached between editorial changes. Evaluate that as a data-design decision, not as a reason to restructure every catalogue for caching.

Listings involve another tradeoff. A fixed collection page such as “rainwear, first page, sorted by product code” may repeat often enough to benefit; a personalised filter for every customer may not. Writes elsewhere in the product collection can also invalidate a cached listing, so a popular page is not necessarily reusable. The [cached-read guide](usage/cached-reads.md#filters-sorting-and-collation) explains the invalidation scope.

Checkout still validates price, promotions, and available stock before accepting an order.

## Logistics: display delayed status, authorise from current data

A parcel portal shows a tracking milestone beside the destination depot's address and collection instructions. Depot directions may be read by many customers between edits. A parcel's status may remain unchanged through many refreshes, then move through several milestones in quick succession.

For a portal that accepts delayed status display, repeated lookups of the same parcel can reuse a cached result between updates. A scan written by a separate warehouse service also triggers invalidation; the portal does not have to be the writer. During busy scanning periods, frequent updates leave less room for reuse.

| Part of the workflow                  | Possible role for caching                                               |
| ------------------------------------- | ----------------------------------------------------------------------- |
| Show depot directions                 | Reuse a frequently requested reference document.                        |
| Display the latest recorded milestone | Reuse repeated parcel lookups if delayed display is acceptable.         |
| Authorise collection or dispatch      | Use the operational system's current checks before allowing the action. |

Both kinds of read can appear on one screen: showing “in transit” after a parcel reaches a depot can be an acceptable display compromise, while deciding whether someone may collect it cannot rely on a cached value.

## Reporting: poll a status, coordinate the job elsewhere

A user requests a large monthly export. A background worker builds the file while the browser, other tabs, or colleagues repeatedly ask for the export's status. Most polls arrive while nothing has changed, so reusing the status document avoids executing the same database lookup on every refresh. When the worker records completion, invalidation allows a later lookup to retrieve the completed state.

The interface may therefore continue showing “preparing” after the file is ready. A product that promises immediate completion visibility needs a different notification or freshness design.

The cached read only displays progress. Claiming the job for a worker, preventing duplicate exports, and deciding who may download the file remain application responsibilities, including a current access check when required.

## Workers that share hot data

Requests for one destination, jacket, depot, or export may land on different worker processes. If trusted workers share a host, `SharedCacheManager` lets them reuse the same cached results instead of each warming an independent copy. The benefit depends on overlap: a worker handling entirely different tenants or destinations contributes little reuse for its neighbours. The [manager comparison](getting-started/choose-a-manager.md) covers deployment requirements, shared eligibility, costs, and options for workers on several hosts.

## Find candidates in your application

Follow one ordinary user journey and list the database reads behind it, then do the same for a different user's journey. Reads that appear in both lists are candidates. Use the [workload evaluation guide](benchmarks/index.md) to test whether that overlap produces a useful benefit in the application.
