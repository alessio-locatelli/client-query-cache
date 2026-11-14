# Quantitative worker-recovery study constraint

The active [worker-fault change](../../openspec/changes/benchmark-worker-fault-recovery/proposal.md)
keeps quantitative work pending. Its V8 study stopped at the observer-overhead
gate; no complete fault matrix or recovery-time claim was established. Earlier
trial implementations and registrations are removed.

At 250 ms observer cadence, four of six comparisons exceeded the 10% worker-CPU
limit. The registered one-second retry still failed direct-read request P99 and
independent-worker CPU. The P99 allowance was the larger of 10% or 0.2 ms over
the uninstrumented control. Thus a slower observer cadence alone did not qualify
the method. Resuming needs a small pilot demonstrating acceptable observer cost
before registering or running another full matrix. Historical raw outputs are
untracked; these results establish no operational recovery bound.
