# Design

## Context

See [proposal](proposal.md) for motivation and the delta specs for the behavior contract. Stream supervisors already chain PyMongo exceptions; coordinators log them and bypass caching. The README's raw write runs before any stream activation.

## Decisions

- Keep `MongoDBSetupError` local to the README example. A new exported library exception used only by documentation would enlarge the API without a library-owned failure boundary. Eager manager connection checks would catch raw-write failures earlier but add I/O and alter startup semantics. Neither alternative is necessary.
- Centralize startup message formatting in `_core.stream_startup`, called only after failure. Keep it separate from `stream_options`, whose constants are imported by `_types`. Match `OperationFailure.code == 40573`, whose meaning is defined by [MongoDB's change-stream implementation](https://github.com/mongodb/mongo/blob/r8.0.0/src/mongo/db/pipeline/document_source_change_stream.cpp). Message matching could tolerate undocumented codes but risks misdiagnosis. No research remains necessary.
- Put one copyable initializer in the CI guide. Use PyMongo's operation deadline, direct connection, `replSetGetStatus`, initialization only for error 94, and a writable-primary loop. A second MongoDB helper avoids Python setup but introduces another service lifecycle and job-readiness race. A packaged helper would require an unnecessary public interface. Disposable services are the only supported target; runtime cases are verified during implementation.
- Show replica-set setup fragments for an existing containerized GitLab test job and a GitHub host job. Complete workflow templates would require unrelated dependency caching and pipeline policy. Their service addresses differ, so examples supply `MONGODB_URI` and `MONGODB_MEMBER_HOST` separately. Direct connections avoid following container-only advertised addresses on the host job. This is unsuitable for production failover, which remains covered by deployment guidance.

## Costs and risks

Successful library paths gain no allocations, I/O, or work. Failure formatting adds constant-size string construction only. CI setup polls at a bounded interval under one deadline, outside test execution. No runtime benchmark is needed because neither successful reads nor their setup paths change.

Service command syntax depends on provider support; verify against current official references and run the initializer against real disposable MongoDB. Hosted runner execution is not implied by local validation.
