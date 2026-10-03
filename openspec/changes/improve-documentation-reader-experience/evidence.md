# Implementation evidence

## Versioning compatibility

The locked mike fork and Zensical 0.0.67 built two TOML-configured editions in a disposable Git repository. Headless Chromium verified the stable default, exactly two edition titles, shared-page/fragment switching, missing-page fallback, subpath URLs and distinct search content. A missing heading returned exit 1 through mike with `project.strict = true`; no extra prebuild is needed.

## Reader journey and local MongoDB

The working-tree preview verified installation → synchronous → asyncio footer navigation. Public prose no longer contains the duplicated installation introduction, generic continuation endings, installation reminders or “effective caching”. The README badge matches `requires-python = ">=3.14.6"`.

The original Compose helper failed on repeated startup with “already initialized”. The corrected helper checks replica-set status, initializes only an uninitialized deployment and waits for a writable primary. Fresh and repeated documented startup sequences succeeded through the host Podman Compose provider (Docker CLI is unavailable in this toolbx). The disposable `cqc-docs-local` fixture was stopped afterward. No live database was used.
