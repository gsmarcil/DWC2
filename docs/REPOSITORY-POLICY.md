# Repository policy

This private repository is the canonical research workspace for the DWC2 investigation until coordinated disclosure is complete.

## What belongs on `main`

`main` carries the current, reviewable state only:

- the userspace evidence pipeline;
- the host harness and its tests;
- the DWC2 observer/patch chain and its verification tools;
- the canonical harness specification;
- top-level verification entry points;
- clean-room and build evidence that supports a surviving claim;
- documentation separating CONFIRMED from PENDING/UNKNOWN.

A full Linux source tree is deliberately not vendored. The frozen upstream pin and patch chain are sufficient to reproduce the instrumented tree.

Every instrumentation/observer component is TEST-ONLY and must not be described as a production kernel fix.

## Evidence

Because this repository is private, evidence that materially supports a surviving claim should be retained under `evidence/` or inside the frozen observer package, including ABI layouts, clean-room identity checks, build logs, negative-control outputs, and scope audits.

Do not preserve failed hypotheses as current facts. If a superseded result matters to explain why a guard exists, record it in the audit history with an explicit `SUPERSEDED` label.

## History

Do **not** rewrite `main` to manufacture historical commits.

Past development is represented on the `audit-trail` branch as a **RECONSTRUCTED audit chronology**. Each reconstructed milestone records:

1. the gap that existed;
2. how it was discovered;
3. the invariant or guard added;
4. the discriminating test that would fail without it;
5. the artifact/hash that anchors the change, when available.

The chronology is explanatory evidence, not a claim that the reconstructed commits were created at their historical dates.

## Current epistemic labels

Use only:

- `SOURCE-PROVEN`
- `RUNTIME-PROVEN`
- `NOT PROVEN`
- `UNKNOWN`
- `SUPERSEDED` for historical material

A valid negative campaign result is configuration-scoped `NOT_OBSERVED`; it is never generalized to `R1_DISPROVEN`.
