## ADDED Requirements

### Requirement: Candidate prototypes follow measured cost floors

A shared-value study SHALL preregister its candidate selection rule and measure each candidate family's minimum added CPU per hit before building a full candidate. It SHALL NOT build a family whose floor exceeds the registered margin under the CPU criterion. Floor measurements SHALL be labelled exploratory, and the report SHALL retain every floor and the resulting choice.

#### Scenario: A round-trip floor exceeds the margin

- **WHEN** the minimal round trip of a family costs more CPU per hit than the registered margin allows
- **THEN** no full candidate of that family is built and the report records the floor and the exclusion

#### Scenario: Floor results favour one family

- **WHEN** floor diagnostics have ranked the eligible families
- **THEN** the ranking selects which candidates to build but cannot support production promotion

### Requirement: Locally served hits respect processed invalidations

When workers serve hits from owner-published shared state, a worker SHALL NOT serve an entry if the owner processed its invalidation, eviction or namespace reset, or its database's unavailability, before that read began. An event that the owner processes while a read is in progress SHALL NOT retract a value that the read has already validated.

#### Scenario: A write is processed before the read

- **WHEN** the owner has processed the invalidation of a cached document and a worker then reads that document
- **THEN** the worker does not serve the invalidated entry from shared state

#### Scenario: The database becomes unavailable

- **WHEN** the owner has marked a database unavailable
- **THEN** no worker serves a local hit for that database until the owner publishes its recovery

#### Scenario: A write races an admission

- **WHEN** the owner processes a document's invalidation after an admission for that document validated its capture but before the admission committed
- **THEN** the admission is not published and no worker serves that value locally

### Requirement: Locally served hits never return torn or reclaimed data

A locally served hit SHALL return either bytes that the owner published for the requested key or no value. A read that overlaps publication, removal or reuse of the same space SHALL be detected and its bytes SHALL NOT be decoded. An inconsistent location read SHALL NOT access memory outside the shared mapping.

#### Scenario: Space is reused during a copy

- **WHEN** the owner removes an entry and reuses its space while a worker is copying it
- **THEN** the worker discards the copy and does not serve it

#### Scenario: A location is read mid-update

- **WHEN** a worker reads an entry location that the owner is rewriting
- **THEN** the read stays inside the mapping and is treated as absent

### Requirement: Owner-served hits use stable payload snapshots

When the owner keeps payloads in reusable shared storage, every hit it serves over RPC SHALL encode a snapshot taken while the payload was still valid. A concurrent removal or space reuse SHALL turn that read into a miss, never into a reply containing other data.

#### Scenario: An entry is evicted while an RPC hit is in flight

- **WHEN** the owner selects an entry for an RPC hit and another thread evicts it and reuses its space before the reply is encoded
- **THEN** the reply is a miss or carries the entry's original bytes

### Requirement: Local validation fences owner loss

Without contacting the owner, a worker SHALL stop serving local hits from an owner incarnation within the registered detection bound after that owner process exits, and once the incarnation's published upstream progress is older than the registered expiry. After attaching to a replacement owner, a worker SHALL NOT read the shared state published by an earlier incarnation.

#### Scenario: The owner is killed

- **WHEN** the owner process exits while workers serve local hits
- **THEN** every worker stops serving local hits within the registered detection bound and executes reads natively

#### Scenario: The watch stalls while the owner stays alive

- **WHEN** the owner is paused, or its change stream stops completing upstream polls
- **THEN** workers stop serving local hits once the published progress exceeds the registered expiry

#### Scenario: A replacement owner starts

- **WHEN** a worker attaches to a new owner incarnation
- **THEN** it serves local hits only from that incarnation's published state

### Requirement: Shared-state reclamation is bounded

Published shared state SHALL have registered size bounds. A paused, slow or crashed worker SHALL NOT delay the reclamation of removed entries or cause shared memory to grow.

#### Scenario: A worker dies during a read

- **WHEN** a worker is killed while it copies a published entry
- **THEN** the owner reclaims and reuses that entry's space without waiting for the worker

#### Scenario: Publication capacity is exhausted

- **WHEN** the resident entries exceed the registered publication capacity
- **THEN** shared memory stays within its bounds and unpublished entries are served only through owner selection

### Requirement: Workers cannot modify published state

The owner SHALL give workers no descriptor or mapping through which the published index or entries can be written, including descriptors reopened from ones the worker received. Writable per-worker state SHALL use separate shared objects that grant no access to the published index.

#### Scenario: A worker tries to write the index

- **WHEN** a worker writes through its index descriptor, maps it writable, makes its mapping writable, or reopens the descriptor read-write and writes
- **THEN** every attempt fails and the published state is unchanged

### Requirement: Owner-liveness detection does not compete for RPC replies

A worker SHALL detect owner exit only through a connection's sole reader. A liveness watcher SHALL NOT read from a connection that another reader uses for RPC replies.

#### Scenario: A synchronous worker watches the owner

- **WHEN** a synchronous worker issues RPC selections while its liveness watcher waits for owner exit
- **THEN** every RPC reply reaches its requester intact, and owner exit still sets the worker's detached state

### Requirement: Published state agrees with the authoritative cache

A candidate whose workers validate entries locally SHALL pass a differential check against the authoritative cache. The check covers generated sequences of admissions, writes, namespace resets, evictions and availability changes, and every locally served value SHALL equal the value the authoritative cache serves at the same point.

#### Scenario: A generated sequence invalidates a cached key

- **WHEN** a generated operation sequence leaves the authoritative cache unable to serve a key
- **THEN** the published state also serves no value for that key

### Requirement: Native research components are reproducible

Reports SHALL record the compiler toolchain version, locked native dependency versions and build configuration of every native component they measure. The documented reproduction commands SHALL build those components from repository sources.

#### Scenario: A native candidate is reproduced

- **WHEN** a contributor follows the report's reproduction commands from a clean checkout of the measured revision
- **THEN** the native components build from the committed sources and lockfile and the documented smoke run completes
