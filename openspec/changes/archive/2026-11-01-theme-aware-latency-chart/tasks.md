## 1. Measurements

- [x] 1.1 Log the real-server benchmark's median cached and direct read latency per phase.
- [x] 1.2 Add a benchmark that measures cached-hit latency on a busy CPU without concurrent writes.

## 2. Chart

- [x] 2.1 Add a renderer that writes light and dark SVGs and updates the chart's alternative text from a stream-cost report, a real-server log and a cached-hit report.
- [x] 2.2 Add a `latency-chart` recipe that runs the three benchmarks and the renderer, labels the remote row with a required deployment name, and prints the raw output directory.
- [x] 2.4 Let the stream-cost runner select workloads so the recipe runs only `read_heavy-small`.
- [x] 2.3 Regenerate the chart from current measurements and inspect both variants.

## 3. Documentation

- [x] 3.1 Select the dark variant in README with theme image fragments.
- [x] 3.2 Select the variants in the benchmark guide with theme image fragments and describe the new rows.
- [x] 3.3 Document the regeneration procedure in the contributor guide.
- [x] 3.4 Record why the chart keeps one cached bar measured on a busy CPU.

## 4. Code Quality

- [x] 4.1 Check edited tests against the repository's Writing Tests guidance (only benchmark instrumentation changed).
- [x] 4.2 Check that no docstrings or code comments were added outside override rationales.
