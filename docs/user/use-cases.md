# Use cases: the familiar data behind a new request

A traveller changes their dates. A shopper opens another product. A dispatcher checks the next parcel. Each request looks different, yet the application may keep retrieving the same destination description, size guide, or depot address.

These supporting reads are easy to overlook. They rarely define the business operation, but they accompany it again and again. `client-query-cache` can serve repeated eligible database reads from memory, with change-driven invalidation when the underlying data changes.

The scenarios below are hypothetical application designs, not accounts of production adoption. They explore where caching could fit into everyday business workflows. In each case, the application must be able to tolerate a preceding value while invalidation catches up; the [consistency guide](usage/consistency.md) defines that contract, including the absence of a guaranteed delay.

## Travel: new itineraries, familiar destinations

Imagine a travel planner assembling weekend trips. One visitor searches for two adults in spring; another plans a family break in autumn. Their offers differ, but both may need the same destination introduction, airport details, and descriptions of local attractions.

An editor maintains those documents in the database. Several pages reuse them: search cards show a short destination description, an itinerary page shows airport details, and a saved trip includes the same attraction descriptions.

The opportunity is in those repeated supporting lookups. A destination document can be reused across searches even when the dates and passenger counts change. If an editor corrects its description, change-driven invalidation lets subsequent reads pick up the edit after the event is processed.

The business workflow might look like this:

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

The offer itself has a different lifetime. Seat availability and the price accepted at booking need the reservation system's current checks. Caching destination content does not make an offer bookable.

This distinction also prevents a tempting mistake: treating every travel search as reusable. If almost every visitor asks for a different itinerary, the complete search may rarely repeat. The shared destination content is a more plausible starting point.

## Retail: a product story shared by many shopping journeys

Consider a specialist outdoor shop releasing a seasonal collection. Customers arrive from different campaigns and browse different categories, but many open the same jacket. Its material description, care instructions, photographs, and size guide change much less often than people view them.

A product detail page could reuse its catalogue document while the shop handles stock and checkout separately. The same size guide might also appear on several products, giving it another source of repeated reads.

There is a practical modelling question here. Suppose every sale updates a stock counter inside the product document. Even a cache of its description can lose reuse as that document changes. If catalogue content and stock already have separate business lifecycles, separate documents can let the stable content remain useful between editorial changes. That is a data-design decision to evaluate, rather than a reason to restructure every catalogue for caching.

A merchandising page has another tradeoff. A fixed collection such as “rainwear, first page, sorted by product code” may repeat often enough to benefit. A personalised result with a different filter for every customer may not. Writes elsewhere in the product collection can also invalidate a cached listing; a popular page alone does not establish that it will stay reusable. The [cached-read guide](usage/cached-reads.md#filters-sorting-and-collation) explains the invalidation scope.

For the shop, the useful boundary is concrete: reuse the content that helps a customer choose, then validate price, promotions, and available stock through the checkout workflow before accepting an order.

## Logistics: repeated context around a moving parcel

A parcel portal often presents movement alongside relatively stable context. A customer sees a tracking milestone, the destination depot's address, and instructions for collecting a parcel.

Those pieces have different rates of change. Depot directions may be read by many customers between edits. A parcel's status may remain unchanged through many refreshes, then move through several milestones in quick succession.

For a portal that accepts delayed status display, repeated lookups of the same parcel could reuse a cached result between updates. A scan written by a separate warehouse service can trigger invalidation; the portal does not have to be the writer. During busy scanning periods, however, frequent updates leave less room for reuse.

| Part of the workflow                  | Possible role for caching                                               |
| ------------------------------------- | ----------------------------------------------------------------------- |
| Show depot directions                 | Reuse a frequently requested reference document.                        |
| Display the latest recorded milestone | Reuse repeated parcel lookups if delayed display is acceptable.         |
| Authorise collection or dispatch      | Use the operational system's current checks before allowing the action. |

The distinction matters even on one screen. Showing “in transit” after a parcel reaches a depot can be an acceptable display compromise for this hypothetical portal. Deciding whether someone may collect that parcel requires a separate business decision with its own correctness controls.

## Reporting: many refreshes, one unfinished export

Imagine a business portal where a user requests a large monthly export. A background worker builds the file while a browser repeatedly asks for the export's status. Other tabs or colleagues may watch the same export.

Most polls can arrive while nothing has changed. Reusing the status document could avoid executing the same database lookup on every refresh. When the worker records completion, invalidation allows a later lookup to retrieve the completed state.

Here the consequence of a preceding value is easy to explain: the interface may continue showing “preparing” after the file is ready. A product that promises immediate completion visibility needs a different notification or freshness design.

The cached read also has a deliberately limited job. It helps display progress. It does not claim the job for a worker, prevent duplicate exports, or decide who may download the file. Those remain application responsibilities, including a current access check when required.

## When several workers meet the same hot data

All four scenarios can run in a service with multiple workers. Requests for one destination, jacket, depot, or export may land on different processes. If trusted workers share a host, `SharedCacheManager` gives them a way to reuse the same cached results instead of each warming an independent copy.

That is most interesting when their frequently requested data overlaps. A worker handling entirely different tenants or destinations may contribute little reuse for its neighbours. Workers spread across hosts also need a different sharing arrangement. The [manager-selection guide](getting-started/choose-a-manager.md) covers those deployment choices and costs.

To find a candidate in your own domain, follow one ordinary user journey and list the database reads behind it. Then follow a different user's journey. The documents and queries that appear in both lists are worth investigating: they reveal where new business requests keep asking familiar questions. Use the [workload evaluation guide](benchmarks/index.md) to test whether that overlap produces a useful benefit in the application.
