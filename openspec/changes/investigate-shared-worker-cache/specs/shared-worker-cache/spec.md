# Spec Delta

## Purpose

This capability defines optional shared cached-value access for a trusted group of application worker processes on one host, with explicit ownership, isolation and recovery boundaries.

The runtime contracts in this capability are conditional on production promotion under the change's decision gate. They are removed from the delivered delta if the investigation ends without integration.

## ADDED Requirements

### Requirement: Shared cache attachment is explicit

Shared cache use SHALL require explicit attachment to an application-owned worker group. Omitting attachment SHALL retain standalone behavior. Conflicting group configuration SHALL be rejected before serving a cached result.

#### Scenario: An existing application constructs its manager

- **WHEN** the caller supplies no shared attachment
- **THEN** cache storage, streams, options and client ownership retain their standalone contracts without coordinator infrastructure

#### Scenario: A worker supplies an incompatible budget

- **WHEN** an attachment's supplied budget or stream policy conflicts with its owner's fixed configuration
- **THEN** construction fails visibly rather than silently replacing either setting

### Requirement: Shared cache results retain one resident owner

A worker group SHALL retain one authoritative resident encoded-value store. Attached workers SHALL NOT keep an additional reusable result cache. Caller-owned decoded results, cursor snapshots and bounded admission candidates SHALL remain separate from the resident cache budget.

#### Scenario: Eight workers repeatedly read one entry

- **WHEN** each worker executes the same eligible read
- **THEN** all reuse the group entry without retaining eight worker-local cache copies

#### Scenario: A caller mutates its hit

- **WHEN** a worker changes a returned nested value
- **THEN** the shared entry and subsequent results in any worker retain the original value

### Requirement: Shared cache scopes require equivalent authority

An attachment SHALL be authorized for its explicit deployment, database allowlist and security scope. Distinct tenants, principals or incompatible decoding/encryption profiles SHALL NOT share entries or aliases. A claimed endpoint name or MongoDB address SHALL NOT establish authority.

#### Scenario: Different tenants request identical namespace keys

- **WHEN** tenants using separate authorized groups request the same database, collection and identity names
- **THEN** neither can select, admit, invalidate or inspect the other's entries

#### Scenario: A peer lacks the group capability

- **WHEN** an unauthorized local process connects to the group's transport
- **THEN** it receives no cache data or ability to mutate group state

### Requirement: Shared cache keys preserve portable query distinctions

Shared keys SHALL preserve every cache-relevant query and codec distinction independently of process-local hashes or object identities. Profiles without a verified portable representation SHALL bypass shared caching with an inspectable reason and retain native execution.

#### Scenario: Workers use distinct Python hash seeds

- **WHEN** two authorized workers execute the same supported query and codec profile
- **THEN** they can select the same entry without relying on matching Python hashes

#### Scenario: A worker uses a custom codec registry

- **WHEN** its decoding profile has no supported portable identity
- **THEN** it executes natively without reusing a superficially matching shared entry

### Requirement: Shared cache selection preserves invalidation ordering

Shared selection and admission SHALL use the existing namespace, identity, alias and stream-availability guards at one authoritative cache state. An invalidation processed before a selection decision SHALL prevent selecting its stale result. No shared health observation SHALL imply a per-write catch-up barrier.

#### Scenario: An admission races an external update

- **WHEN** one worker captures a read and another worker's update event is processed before admission
- **THEN** the obsolete result is rejected without replacing a newer valid entry

#### Scenario: A response was selected before invalidation

- **WHEN** an event is processed after a valid selection decision while that response is in transit
- **THEN** the overlapping read can finish its selected snapshot, but a later selection cannot reuse the invalidated entry

### Requirement: Shared cache continuity fences old sessions and admissions

Coordinator replacement, attachment reconnection and database uncertainty SHALL fence previous admission ownership. A native read spanning those boundaries SHALL NOT populate restored state through an obsolete handle. Shared state without established continuity SHALL remain unavailable for selection and admission.

#### Scenario: A delayed result arrives after owner restart

- **WHEN** a worker submits a capture from the previous owner incarnation
- **THEN** the new owner rejects it even if namespace and identity counters have the same numeric values

#### Scenario: Stream history cannot be resumed

- **WHEN** the owner loses the required resume history
- **THEN** the affected database is unavailable and cleared before healthy selection resumes, and pre-transition captures remain invalid

### Requirement: Shared cache uncertainty falls back to native reads

Transport failure, expired upstream progress or request deadlines SHALL reject new shared selection and admission. Eligible reads SHALL execute through their caller-owned native client while shared cache use is unavailable. Publication failure after successful native execution SHALL NOT repeat that database read or replace its result with an IPC error.

#### Scenario: The coordinator stops responding

- **WHEN** selection exceeds its configured deadline
- **THEN** the worker abandons that cache attempt and performs the native read without using a buffered expired response

#### Scenario: Admission times out

- **WHEN** the native read succeeded but cache publication cannot be confirmed
- **THEN** the caller receives the native result and no duplicate native read is issued for cache recovery

### Requirement: Upstream progress governs shared readiness

Shared readiness SHALL expire when completed upstream observations exceed the configured progress deadline. A transport heartbeat alone SHALL NOT renew readiness. Recovery SHALL establish upstream progress and current availability before enabling new shared selection or admission.

#### Scenario: A healthy-looking service has a stalled watch

- **WHEN** RPC replies continue while completed upstream polls stop
- **THEN** selection and admission become unavailable within the configured progress deadline despite the responsive coordinator

### Requirement: Shared transport bounds peer resource use

Shared transport SHALL validate message version, framing and scope without arbitrary Python object deserialization. It SHALL bound connected peers, outstanding requests, queued bytes and retained captures. A slow, malformed or cancelled peer SHALL NOT prevent invalidation or another peer's bounded progress.

#### Scenario: A worker stops reading replies

- **WHEN** its queued bytes exceed the configured limit
- **THEN** the owner applies bounded backpressure or detaches it while other workers and invalidation continue

#### Scenario: A worker dies with captured reads

- **WHEN** a worker exits without discarding its captures
- **THEN** closure or finite expiry reclaims its captures without deleting another worker's entry or retaining unbounded generation references

### Requirement: Shared asyncio access preserves event-loop progress

Async shared cache operations SHALL suspend without blocking the event loop on transport waits. Cancellation SHALL release request and admission ownership while preserving native cursor cleanup and cancellation behavior.

#### Scenario: An async cache operation waits behind a paused owner

- **WHEN** a shared request is outstanding
- **THEN** unrelated tasks continue running and cancellation does not leave an unbounded pending request or capture

### Requirement: Shared ownership survives worker recycling

The application SHALL own coordinator launch and shutdown independently of worker lifetimes. Importing a module or constructing an attachment SHALL NOT elect or spawn another owner. Worker-local clients and attachments SHALL be created after process start; inherited live attachments SHALL be rejected before resource use.

#### Scenario: Gunicorn recycles a worker

- **WHEN** a replacement worker starts and attaches using newly created local resources
- **THEN** existing workers keep using the same group budget and streams without transferring live clients or starting another coordinator

#### Scenario: Preloaded state is inherited by fork

- **WHEN** a child tries to use an attachment created in its parent
- **THEN** the library rejects it before touching inherited locks or sockets

### Requirement: Shared shutdown separates attachment and group ownership

Closing a worker manager SHALL detach only that worker's cache resources and leave caller-owned clients and other attachments usable. Owner shutdown SHALL disable new shared work before cleanup, prevent late readiness publication, and visibly report persistent cleanup failures.

#### Scenario: One manager closes while peers read

- **WHEN** a worker closes its manager
- **THEN** its requests and captures are released while peer workers and the group's streams remain usable

#### Scenario: Owner shutdown races database activation

- **WHEN** a database watch finishes opening after owner shutdown starts
- **THEN** it is cleaned up without enabling shared selection, and attached workers use native reads
