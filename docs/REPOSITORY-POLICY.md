# Repository policy

This private repository is the canonical research workspace for the DWC2 investigation until coordinated disclosure is complete.

## What belongs on `main`

`main` carries the current, reviewable state only:

- the userspace evidence pipeline;
- the host harness and its tests under `r1a-host/`;
- the gadget-side holder harness under `r1a-device/`;
- the DWC2 observer/patch chain and its verification tools;
- the canonical harness specification;
- top-level verification entry points;
- clean-room and build evidence that supports a surviving claim;
- documentation separating CONFIRMED from PENDING/UNKNOWN.

A full Linux source tree is deliberately not vendored. The frozen upstream pin and patch chain are sufficient to reproduce the instrumented tree.

Every instrumentation/observer component is TEST-ONLY and must not be described as a production kernel fix.

## Epoch completeness

Any artifact named by the active `EPOCH_ARTIFACTS` contract is load-bearing evidence infrastructure. It may not exist only as a manifest key or operator-supplied hash.

For an epoch to be self-contained, every such artifact must have one of the following inside the canonical repository:

1. the exact source/binary that is hashed at runtime; or
2. a reproducible, byte-verifiable derivation anchored by canonical source plus the build inputs required by the frozen contract.

This applies equally to host and device harnesses. If `holder_merger` is active,
the repository must carry a device producer that can emit every field and
sentinel consumed by that merger. If `device_harness` is added to the epoch, the
exact tested source and binary must also be pinned before negative evidence can
be accumulated. Path presence alone is never capability proof.

Do not synthesize missing epoch sources from documentation or memory.

### Executable repository gate

The prose rule above is not sufficient by itself. A checked-in baseline is not `VERIFIED` unless a clean checkout passes:

```sh
./VERIFY-REPOSITORY.sh
```

At minimum the gate must establish:

1. every path pinned by `baseline/SHA256SUMS` exists and matches its pinned SHA256; and
2. the checked-in validator/freezer can resolve the active local
   `EPOCH_ARTIFACTS` contract from real files in the repository; and
3. an active holder merger has a producer exposing its event-log schema.

The gate must fail closed when the validator, freezer, host source, device source,
or another load-bearing source is missing or incompatible. Its output separates
baseline integrity from campaign readiness: a baseline failure requires
canonical re-import, while a producer-capability failure leaves the authenticated
baseline intact and blocks the campaign.

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
