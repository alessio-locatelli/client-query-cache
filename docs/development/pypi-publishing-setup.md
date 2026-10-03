# PyPI publishing setup

Before the first release, the repository owner completes two one-time steps outside this repository:

1. On [PyPI](https://pypi.org/manage/account/publishing/), register a pending trusted publisher with:
   - PyPI project name: `client-query-cache`
   - Owner: `<your_account_username>`
   - Repository name: `client-query-cache`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`
2. In the repository's GitHub Settings → Environments, create an environment named `pypi` and add at least one required reviewer. Without a required reviewer, the environment does not pause the publish workflow for approval.
