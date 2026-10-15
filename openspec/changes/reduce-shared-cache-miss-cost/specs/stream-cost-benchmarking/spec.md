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
