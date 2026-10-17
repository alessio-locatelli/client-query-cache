# Operations

[Choose a manager](../getting-started/choose-a-manager.md) before sizing or launching workers. Both managers need supported MongoDB change streams, long-lived application resources and direct reads where freshness is required.

- [Process-local deployment](deployment.md): one client and manager per process, independent cache budgets, security, recovery and memory sizing.
- [Shared worker deployment](shared-cache.md): one parent-owned cache server, trusted worker attachments, fixed collection names and shared capacity.
- [Monitoring](monitoring.md): the diagnostics available for each manager and how to investigate misses and bypasses.
- [Permission recovery exercise](permission-recovery.md): observe process-local fallback and recovery on a disposable authenticated replica set.
- [Rollback to plain PyMongo](../reference/api.md#rollback-to-plain-pymongo): disable caching without a stored-data migration.

For executable web lifecycles, use [FastAPI with shared caching](../examples/fastapi-shared.md) or the [compact process-local application](../examples/fastapi-minimal.md).
