# Design

## Context

See proposal.md for the observed failure. `evaluate_case` rejects any block below 0.005 seconds. `measure_and_evaluate_case` currently discards completed measurements when that validation raises. CI redirects all summary output to GitHub's summary file.

## Decisions

Separate measurement errors from evaluation errors. Preserve the completed arrays on evaluation failure with the existing report fields; do not compute relative statistics from rejected evidence. Increment the guard artifact schema to version 2 because timing arrays can contain null elements. Serialize nonfinite timing slots as JSON null while preserving the invalid value in the failure reason. Report the first invalid block with its side, one-based index, duration, and floor. Use `tee -a` for the existing summary and retain the command's failure via Bash pipefail.

No subprocess commands, connection strings, application documents, or environment variables are added to diagnostics. This adds bounded report serialization and output after timing; no timed path changes or extra database calls occur.

## Risks / Trade-offs

The duration failure remains possible. Changing workload calibration without the discarded evidence would be speculative. The existing failing-job URL records the discrepancy; this change supplies the evidence for investigation without accepting invalid timings.
