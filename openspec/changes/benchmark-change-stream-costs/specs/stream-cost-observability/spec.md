## Purpose

This capability exposes safe, precisely labelled cache and stream measurements that can inform workload-specific benchmark analysis without exposing application data.

## ADDED Requirements

### Requirement: Measurement snapshots have explicit scope
The manager SHALL expose immutable counts for cache outcomes, stream polls, logical projected-event bytes, invalidations, and resident cache bytes. It SHALL label logical payload measures as distinct from network wire bytes and server CPU, and SHALL omit queries, documents, credentials, and resume tokens.

#### Scenario: An application exports measurements
- **WHEN** an application serializes a manager measurement snapshot
- **THEN** the output states each measurement scope and contains no cached document or credential value

### Requirement: Stream projection preserves coherency fields
Benchmark instrumentation SHALL observe the same projected event fields required for invalidation and resume. It SHALL not request full-document update lookup solely for invalidation measurement.

#### Scenario: A projected update is processed
- **WHEN** the manager receives an update event during a measured run
- **THEN** it can route invalidation and preserve its resume token without a full document payload
