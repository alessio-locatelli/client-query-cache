# Spec Delta

## ADDED Requirements

### Requirement: Harness proxies bound and account forwarded bytes

The shared-cache benchmark SHALL implement its byte proxy in harness code outside the installed package. Each direction SHALL use a 64 KiB buffer, count bytes successfully written, preserve backpressure and propagate EOF only after buffered bytes drain.

#### Scenario: A client half-closes after sending a large request

- **WHEN** a request exceeds the proxy buffer and the client closes its write direction
- **THEN** the proxy forwards and counts every request byte before EOF, permits the server's reverse reply and counts that reply independently

### Requirement: Harness proxies gate and release fault-controlled traffic

Pause and resume SHALL gate forwarding, and teardown SHALL wake paused senders before sockets close. Socket setup and teardown failures SHALL remain visible. A comparison that depends on proxy cost SHALL measure the proxy's CPU separately from the library's.

#### Scenario: A paused proxy is torn down

- **WHEN** teardown stops a proxy with paused senders
- **THEN** those senders wake, the teardown releases blocked reads and the connection thread joins

## REMOVED Requirements

### Requirement: Shared-cache relay I/O runs outside the Python GIL

**Reason**: The native byte relay was a benchmark-only runtime binding and is removed from the installed package. The harness proxy runs in Python.

**Migration**: The harness-proxy requirements above preserve directional accounting, buffering, backpressure and EOF behavior. Proxy overhead is measured separately and no longer attributed to the library.

### Requirement: Native relays preserve ownership and fault-control lifecycle

**Reason**: No native relay remains, so descriptor ownership across the GIL and native thread setup no longer exist.

**Migration**: Pause/resume gating, teardown of paused senders and visible failures are required of the harness proxy by the harness-proxy requirements above.
