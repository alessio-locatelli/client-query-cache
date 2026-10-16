## ADDED Requirements

### Requirement: Locally captured misses preserve admission fencing

A research worker MAY capture a miss without an owner round trip. Admission SHALL reject captures spanning a processed write, namespace reset, owner replacement, database availability transition or expired upstream progress. The authoritative cache SHALL validate admission races after capture validation. Capture lifetime and transport buffers SHALL remain bounded; cancellation SHALL retain no owner capture.

#### Scenario: A previously uncached identity is written during a read

- **WHEN** the owner processes its write after local capture and before admission
- **THEN** admission rejects the captured value even if the core tracked no identity when the write arrived

#### Scenario: Progress expires and resumes during a read

- **WHEN** upstream progress expires between local capture and admission and subsequently resumes
- **THEN** the old capture remains inadmissible

#### Scenario: Validation races another write

- **WHEN** a write arrives after the owner's local-token validation
- **THEN** the core's identity capture prevents stale publication

#### Scenario: Reusable core guard sections

- **WHEN** concurrent admissions reuse the core's lock-order guard objects
- **THEN** namespace/LRU exclusion remains thread-local and lasts through the outermost section
- **AND** an exception releases the section without weakening later checks

#### Scenario: Namespace acquisition is interrupted

- **WHEN** acquiring a reused namespace lock raises before the primitive lock is held
- **THEN** its lock-order guard unwinds and later LRU/namespace exclusion remains correct

#### Scenario: Integer identities reuse a BSON envelope

- **WHEN** a signed 64-bit plain integer key uses the optimized wire path
- **THEN** its bytes and decoded type match the existing tagged BSON representation exactly
- **AND** damaged lengths, field names or terminators remain protocol errors

#### Scenario: A local capture is unavailable

- **WHEN** metadata, publication slots or attachment validity cannot authorize capture
- **THEN** the worker retains the owner selection or native bypass path

#### Scenario: A worker queues an admission

- **WHEN** a worker posts an encoded admission to its native session queue
- **THEN** the owner consumes only complete records, copies them before reuse and applies the same admission fencing
- **AND** a full queue uses bounded socket fallback when a data channel is available, otherwise skips admission while preserving the MongoDB result

#### Scenario: A native queue is available without a data socket

- **WHEN** a valid authenticated control mapping provides a native admission queue and an executor thread has no data socket or loses its data socket
- **THEN** the worker captures and queues eligible misses without an owner selection RPC or data-socket setup
- **AND** a full queue reuses the same encoded frame for socket fallback when that transport is available
- **AND** socket-only attachments retain data-channel reconnection and owner selection

#### Scenario: An endpoint closes while its control mapping still exists

- **WHEN** the closed endpoint receives an admission with a queue-capable reader
- **THEN** it drops the admission without publishing through that queue
- **AND** detached readers remain unable to capture or enqueue

#### Scenario: Sustained admissions use short queue drains

- **WHEN** an owner consumes queued admissions
- **THEN** it polls admission queues every millisecond until fifty milliseconds after the latest nonempty drain
- **AND** capture cleanup and recency sweeps retain their fifty-millisecond cadence
- **AND** quiet owners return to fifty-millisecond polling

#### Scenario: A queue peer sends a damaged record

- **WHEN** queue positions, frame boundaries or admission fields are malformed
- **THEN** the owner detaches that peer without processing an unbounded record or disrupting other sessions

### Requirement: Default identity classification retains request policy

An optimized default identity read SHALL retain per-request session and read-profile inspection, metadata eligibility, owner reattachment, codec normalization and the existing capture/admission authorities. Requests outside the optimized shape SHALL retain general classification.

#### Scenario: A session is bound after warming an integer identity

- **WHEN** the same default identity request executes inside a bound session
- **THEN** it bypasses the shared hit and executes through the driver's session policy

#### Scenario: Metadata discovers a default collation

- **WHEN** a default integer identity request first probes a collection with non-simple default collation
- **THEN** both that read and subsequent reads bypass the shared cache

#### Scenario: Identity-key eviction leaves the default shape unchanged

- **WHEN** a collection view repeats its portable default read shape after unrelated identity keys leave the bounded key cache
- **THEN** it reuses its previously encoded default shape
- **AND** other shapes retain existing key preparation

#### Scenario: Codec metadata cannot form a canonical key

- **WHEN** a valid codec contains unhashable metadata
- **THEN** constructing the view succeeds and reads preserve the existing native bypass

### Requirement: Miss optimization evidence repeats the complete protocol

A follow-up miss study SHALL preregister fresh baseline calibration and all version 5 phases, plus the version 6 timed fault protocol. Its miss P95 and P99 upper confidence bounds SHALL satisfy the registered direct-read delta at four and eight workers in both models. Missing phases, failed capacity windows or regressed hot and active criteria SHALL prevent promotion.

#### Scenario: Cold misses pass but capacity fails

- **WHEN** fresh cold comparisons meet their limit but any required capacity window fails
- **THEN** the report retains that failure and withholds promotion
