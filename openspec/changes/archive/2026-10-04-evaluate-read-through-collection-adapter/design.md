# Design

## Context

The existing cached find/aggregate methods return lists; native PyMongo returns
cursors. A transparent adapter was investigated to remove that interface
friction. The selected contract also requires warm reads to preserve native
live errors and server effects.

## Decision

Keep that contract and stop the adoption investigation at its decisive boundary.
A zero-command hit has the same cached information whether the skipped native
command would succeed or encounter a new server/network failure. It cannot
preserve both outcomes. Native execution preserves the required error but
removes the demonstrated avoided-command benefit.

Retain a concise engineering report and one fail-point reproduction. The example
uses the current explicit cached count API to demonstrate skipped execution;
it does not claim a complete adapter or a defect in that explicit API contract.
Run the same source on PyMongo 4.18.1 and 4.18.2 against a disposable MongoDB 8.0.4
replica set. The existing container bridge and readiness mechanism provide the
fixture; no custom infrastructure or production configuration is added.

## Scope

The approved review cleanup replaces the broad method inventory, generated
matrices, consumer catalog and resource campaign with the proof needed for this
selected contract. Those experiments are not required to establish this no-go
and are not represented as complete driver-wide compatibility coverage.

Changing the explicit-view cursor contract or accepting skipped live errors
would need a separate proposal. A native-execution/cache-processing hybrid is
unverified, not rejected. The production session fix is independent. Keep its
runtime code, tests, specification changes and user documentation outside this
research branch.

## Trade-offs

The concise proof declines transparent zero-command caching under the selected
policy without claiming that all caching or all cursor adapters are impossible.
It gives up a generated compatibility catalog because no cached production
contract is being adopted. Executable research is retained as a regular Python
file for direct execution, formatting, linting and type checking.

## Completion

Reproduce the live-error example on both tested releases, review the report and
code, confirm the branch has no production changes, then archive the research
with no spec deltas. Production behavior and dependency requirements are unchanged.
