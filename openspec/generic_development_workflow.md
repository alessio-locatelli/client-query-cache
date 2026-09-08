## Generic Development Workflow

Use the **full path** for substantive features, architectural changes, performance-sensitive work, concurrency changes, storage changes, or anything with non-obvious system impact.

Use the **lightweight path** for small, well-contained changes where architecture and performance characteristics are already understood.

---

## Lightweight Path

Use this path only when the change is local, low-risk, and does not materially alter architecture, scalability, persistence, concurrency, security, or external contracts.

1. **Define the intended behavior**

   - State what changes and what must remain unchanged.
   - Identify the main success case and relevant edge cases.

2. **Check architectural fit**

   - Confirm that the change belongs in the component being modified.
   - Do not introduce a local workaround merely because it is faster to implement.
   - Escalate to the full workflow if the change requires bypassing existing abstractions or introducing new cross-cutting behavior.

3. **Check obvious resource impact**
   Consider whether the change introduces:

   - additional database or network calls;
   - loops over potentially large datasets;
   - repeated serialization or parsing;
   - additional allocations or retained memory;
   - blocking I/O;
   - polling;
   - N+1 behavior;
   - new work on a hot path.

   If any of these are potentially material, use the full workflow.

4. **Implement**

   - Prefer the smallest clear solution consistent with the existing architecture.
   - Avoid unnecessary abstractions and speculative optimization.

5. **Verify**

   - Run relevant tests.
   - Add or update tests for changed behavior and important edge cases.

6. **Sanity-check performance**

   - For ordinary small changes, inspection is sufficient.
   - Benchmark only if the change touches a hot path, adds meaningful I/O, changes algorithmic behavior, or introduces uncertainty about performance.

A lightweight change is complete when its behavior is tested, its architectural placement is reasonable, and there is no obvious new scalability or resource-cost concern.

If that cannot be established quickly, use the full workflow below.

---

## Full Path

For any substantive feature or architectural change, follow this sequence before considering the work complete.

1. **Define functional requirements**

   - State what the system must do.
   - Identify inputs, outputs, invariants, failure cases, and externally visible behavior.
   - Separate required behavior from optional enhancements.

2. **Define non-functional requirements**

   - Record relevant constraints for performance, latency, throughput, memory, CPU, network and disk I/O, scalability, reliability, consistency, security, operability, and maintainability.
   - Use concrete targets where they are known.
   - If an important constraint is unknown, state that explicitly rather than silently assuming it does not matter.

3. **Validate the architecture**

   - Determine where the feature belongs in the existing architecture.
   - Do not force the implementation into an existing abstraction merely because it is convenient.
   - Prefer extending existing architecture when it remains a good fit; otherwise propose the smallest justified architectural change.
   - Identify new components, responsibilities, interfaces, data flows, persistence, synchronization, and failure boundaries.

4. **Analyze resource and complexity costs**
   Before implementation, describe the important execution paths as a diagram, table, or concise bullet list.

   For each significant step, estimate or characterize:

   - time complexity, including relevant Big-O behavior;
   - memory usage and allocation behavior;
   - CPU work;
   - network I/O;
   - disk/database I/O;
   - number of remote calls or round trips;
   - work that scales with users, records, requests, workers, shards, or other important dimensions.

   Example:

   ```text
   request
     -> cache lookup          O(1), local memory
     -> database lookup       O(log n), 1 network round trip
     -> deserialize result    O(document size), CPU + allocation
     -> cache population      O(document size), local memory write
   ```

   Focus on costs that can materially affect the real system. Do not add meaningless Big-O annotations to constant-size administrative operations.

5. **Identify likely bottlenecks before coding**

   - State which part of the proposed design is expected to dominate latency, CPU, memory, or I/O.
   - Note assumptions behind that expectation.
   - Consider workload shape, especially read/write ratios, data size, concurrency, fan-out, and repeated work.
   - Check whether the proposed design creates unnecessary polling, duplicate computation, repeated serialization, excessive remote calls, N+1 queries, unbounded growth, or work proportional to a much larger dataset than necessary.

6. **Implement the simplest architecture-correct solution**

   - Optimize for clarity and correctness first, but do not knowingly introduce avoidable architectural or performance defects.
   - Avoid local hacks that bypass established ownership, interfaces, invariants, or lifecycle management.
   - Avoid speculative micro-optimizations without evidence.
   - Do not use "we can optimize it later" to justify a design whose foreseeable cost is fundamentally wrong for the expected workload.

7. **Verify correctness**

   - Test normal behavior, boundary cases, failures, concurrency-sensitive behavior, and recovery paths as applicable.
   - Verify that the implementation still satisfies the functional and non-functional requirements.
   - Confirm that resource ownership, cleanup, retries, caching, transactions, and synchronization behave correctly.

8. **Measure important performance claims**

   - Benchmark or profile the paths where performance materially affects the design.
   - Prefer representative data sizes and workloads over trivial microbenchmarks.
   - Measure the relevant metric: latency, throughput, CPU, allocations, memory, network traffic, database calls, disk I/O, or another appropriate resource.
   - Compare against a baseline when one exists.

9. **Record the observed bottleneck**

   - State what currently limits performance.
   - Distinguish measured bottlenecks from suspected ones.
   - Record enough evidence to prevent future work from optimizing the wrong component.
   - If no meaningful bottleneck exists at the expected workload, say so.

10. **Revisit the design when measurements contradict assumptions**

    - Do not patch around an architectural mismatch with increasingly local workarounds.
    - If the measured behavior invalidates the original design assumptions, reconsider the architecture or data flow.
    - Optimize only where the expected benefit justifies the added complexity.

### Completion criteria

A substantive feature is not complete until the implementation can answer:

- What behavior does it provide?
- What non-functional constraints matter?
- Why does this architecture fit?
- What are the important CPU, memory, network, and I/O costs?
- What scales with workload or data size?
- What was measured?
- What is the current bottleneck?
- Which remaining performance concerns are measured facts versus assumptions?
