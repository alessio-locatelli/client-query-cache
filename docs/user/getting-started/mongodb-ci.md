# MongoDB in CI

Use a disposable single-member replica set to exercise caching in CI. These examples start one MongoDB service and initialize it from the Python test job, using PyMongo without installing `mongosh`.

The database has no authentication and is discarded after the job. For application deployments, follow [deployment guidance](../operations/deployment.md).

## Initialize the test database

Save this as `ci/init_mongodb.py` in your project:

```python
import os
from time import sleep

from pymongo import MongoClient, timeout
from pymongo.errors import OperationFailure

with MongoClient(os.environ["MONGODB_URI"]) as client, timeout(60):
    client.admin.command("ping")
    try:
        client.admin.command("replSetGetStatus")
    except OperationFailure as exc:
        if exc.code != 94:  # NotYetInitialized
            raise
        client.admin.command(
            "replSetInitiate",
            {
                "_id": "rs0",
                "members": [{"_id": 0, "host": os.environ["MONGODB_MEMBER_HOST"]}],
            },
        )
    while not client.admin.command("hello")["isWritablePrimary"]:
        sleep(0.5)
```

The initializer waits for a connection and then a writable primary under a [60-second operation deadline](https://pymongo.readthedocs.io/en/stable/api/pymongo/index.html#pymongo.timeout). It can run again against the same initialized service. Unexpected server errors and timeouts fail the job before tests start.

The fragments below extend an existing test job where Python and PyMongo are already available. Merge the service and environment settings into that job, then run the initializer after your dependency setup and before your tests. Configure your tests to read `MONGODB_URI`.

## GitLab CI

For a job using the [GitLab Docker executor](https://docs.gitlab.com/runner/executors/docker/):

```yaml
test:
  variables:
    FF_NETWORK_PER_BUILD: "true"
    MONGODB_URI: "mongodb://mongo:27017/?directConnection=true"
    MONGODB_MEMBER_HOST: "mongo:27017"
  services:
    - name: mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8
      alias: mongo
      command: ["--bind_ip_all", "--replSet", "rs0"]
  script:
    - python ci/init_mongodb.py
```

The job reaches MongoDB through its `mongo` service alias on the job's isolated network. See GitLab's [service networking documentation](https://docs.gitlab.com/ci/services/#connecting-services).

## GitHub Actions

For a job running directly on a GitHub-hosted Ubuntu runner:

```yaml
jobs:
  test:
    runs-on: ubuntu-24.04
    env:
      MONGODB_URI: "mongodb://localhost:27017/?directConnection=true"
      MONGODB_MEMBER_HOST: "localhost:27017"
    services:
      mongo:
        image: mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8
        command: --bind_ip_all --replSet rs0
        ports:
          - 127.0.0.1:27017:27017
    steps:
      - run: python ci/init_mongodb.py
```

This job runs on the host and reaches MongoDB through the published localhost port. See GitHub's [service-container networking](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers) and [service command](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idservicesservice_idcommand) references.

The examples use `directConnection=true` for these disposable single-member services. For production topology discovery and failover, use your deployment's connection settings instead.
