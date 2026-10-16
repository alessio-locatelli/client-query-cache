## ADDED Requirements

### Requirement: Byte relays preserve driver TCP delivery policy

Byte-counting relays SHALL enable `TCP_NODELAY` on both connected TCP legs, matching PyMongo's direct connection policy. Socket setup failures SHALL close both legs. Shared-cache qualification SHALL record and verify this observer policy before candidate timing without weakening byte attribution, fault controls or existing acceptance gates.

#### Scenario: A relay forwards a benchmark connection

- **WHEN** the relay establishes its client and upstream sockets
- **THEN** both sockets disable Nagle's algorithm before forwarding bytes and retain the existing direct-path counters

#### Scenario: A relay socket option cannot be configured

- **WHEN** configuring either connected socket fails
- **THEN** the relay closes all sockets established for that connection and accepts subsequent connections without leaking descriptors

#### Scenario: Qualification uses a different relay policy

- **WHEN** fresh qualification omits or differs from the registered TCP delivery policy
- **THEN** qualification fails and cannot authorize candidate timing

### Requirement: Shared-cache relay I/O runs outside the Python GIL

The shared-cache benchmark's native byte relay SHALL forward outside the Python GIL while retaining direct-path attribution and fault controls. It SHALL bound each direction's buffer to 64 KiB, count bytes successfully written, preserve backpressure and propagate EOF only after that direction's buffered bytes drain.

#### Scenario: A client half-closes after sending a large request

- **WHEN** a request exceeds the relay buffer and the client closes its write direction
- **THEN** the relay forwards and counts every request byte before EOF, permits the server's reverse reply and counts that reply independently

### Requirement: Native relays preserve ownership and fault-control lifecycle

Native relay I/O SHALL own its descriptors before releasing the GIL. Pause/resume SHALL gate forwarding, and shutdown SHALL wake paused senders before sockets close. Descriptor and thread setup failures SHALL remain visible. Fresh qualification SHALL verify the registered relay model and native binary.

#### Scenario: A paused relay shuts down

- **WHEN** teardown stops a relay with paused senders
- **THEN** those senders wake, queued bytes are not forwarded and socket shutdown releases blocked reads before the connection thread joins

#### Scenario: Python closes its socket handles during native forwarding

- **WHEN** Python teardown shuts down and closes its handles while native I/O is active
- **THEN** native code retains ownership of its duplicated descriptors until its pumps exit and cannot access a descriptor subsequently reused by Python

#### Scenario: Native relay setup cannot acquire resources

- **WHEN** descriptor duplication or thread creation fails
- **THEN** the setup error remains visible and the connection's acquired resources are released
