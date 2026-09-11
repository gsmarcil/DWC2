# Repository policy

This private repository is the canonical research workspace for the DWC2 investigation until coordinated disclosure is complete.

## What belongs on `main`

`main` carries the current, reviewable state only:

- the userspace evidence pipeline;
- the host harness and its tests under `r1a-host/`;
- the gadget-side holder harness under `r1a-device/`;
- the DWC2 observer/patch chain and its verification tools;
- the canonical harness specification;
- the source-foundation ledgers that define campaign vocabulary and derivation (`docs/POST-UNMAP-DMA-*.md`) together with any tools those ledgers directly require;
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
3. an active holder merger has a producer exposing its event-log schema; and
4. every source-foundation document or support tool referenced by the current campaign vocabulary is present on `main`.

The gate must fail closed when the validator, freezer, host source, device source,
source-foundation ledger/tool, or another load-bearing source is missing or incompatible. Its output separates
baseline integrity from campaign readiness: a baseline failure requires
canonical re-import, while a producer-capability failure leaves the authenticated
baseline intact and blocks the campaign.

## Evidence

Because this repository is private, evidence that materially supports a surviving claim should be retained under `evidence/` or inside the frozen observer package, including ABI layouts, clean-room identity checks, build logs, negative-control outputs, and scope audits.

Do not preserve failed hypotheses as current facts. If a superseded result matters to explain why a guard exists, record it in the audit history with an explicit `SUPERSEDED` label.


## Privacy redaction of imported evidence: withdrawn

A privacy-redacted derivative of the canonical v4.2 bundle was published and
then withdrawn. It is recorded here because the reasoning matters more than the
outcome.

The redaction replaced an environment-local path inside pinned evidence, then
regenerated every affected manifest and the transport archive so that all of
them agreed with the new bytes. Each of those steps was internally consistent,
and both the baseline check and the repository gate reported green afterwards.

What it could not regenerate is the binding in `verify_archive_tracking.py`.
Those constants tie `baseline/` to an authenticated source commit and tree OID.
Rewriting the bytes changed the tree, so the archive-native proof failed:

```text
baseline Git tree mismatch:
  4e1f21d99f813c0c6e34f5ff269d704996644a41
!= 223dd3983955393a9cadcbbf525767ce9a49f459
```

That constant cannot honestly be updated to the new value. It would then assert
only that the tree is whatever the tree currently is, which proves nothing. The
redacted bytes did not come from the authenticated archive, and no manifest
regeneration can make them have done so.

The failure was also **silent to the gate**. In a git checkout the gate proves
tracking with `git ls-files` and never runs the archive proof, so it stayed
green while the proof a reviewer would run on a tarball was failing. Green here
did not mean intact.

The redacted content was an operating-system username in build logs. No email
address, IP, credential or personal datum was present. That is ordinary build
provenance, and trading an authenticated archive for its removal was a bad
exchange: a self-verifying archive carrying an unremarkable username is strong,
and a clean-looking archive that fails its own proof is worthless.

The default is therefore restored without exception: do not edit files under
`baseline/`, and do not regenerate manifests to make edited bytes pass. If
identifiers must change, rebuild the evidence at its source and import a new
authenticated archive with its own constants.

## History

Do **not** rewrite `main` to manufacture historical commits.

Past development is represented on the `audit-trail` branch as a **RECONSTRUCTED audit chronology**. Each reconstructed milestone records:

1. the gap that existed;
2. how it was discovered;
3. the invariant or guard added;
4. the discriminating test that would fail without it;
5. the artifact/hash that anchors the change, when available.

The chronology is explanatory evidence, not a claim that the reconstructed commits were created at their historical dates.

## Branch status contract

`main` is the **only canonical current workspace**. A long-lived non-`main` branch may be retained for provenance, audit chronology, staging history, or recovery, but it must be classified here before its contents are cited by current documentation. An unlisted branch is `UNCLASSIFIED` and must not supply a definition, executable tool, or load-bearing artifact to a hardware campaign.

The table below records the reviewed role and head at this classification point. Moving a retained branch requires updating its classification in the same repository change.

| Branch | Status | Reviewed head | Allowed use |
|---|---|---|---|
| `main` | `CANONICAL_ACTIVE` | updated by normal fast-forward commits | sole source of current definitions, tools, runbooks, and campaign state |
| `audit-trail` | `HISTORICAL_AUDIT_ONLY` | `110f525b060ab288a0768abd4cd9ce215d97a497` | reconstructed chronology only; never current execution state |
| `canonical-v4.2-reimport` | `HISTORICAL_IMPORT_ANCESTOR` | `9e63c13144f2a3191e01710fbcb23804be182a71` | v4.2 re-import provenance; already ancestral to `main` |
| `holder-v2.3-staging` | `HISTORICAL_STAGING_ANCESTOR` | `9df7b1a4f91a10ef575daa4a658a69ec5ce5723f` | staging provenance; already ancestral to `main` |
| `holder-v2.3` | `PRESERVED_UNMERGED_HOLDER_CLOSURE` | `4635cff2c383d91f9170f90828b241854a155888` | historical holder closure candidate only; not canonical unless explicitly reconciled into `main` |
| `post-unmap-dma-g0` | `SOURCE_IMPORT_ORIGIN_FROZEN` | `47dec94ca77e524cf3c6bb1990062d017f99330c` | origin/provenance for the imported POST-UNMAP source foundation; current use is from `main` only |
| `restore-g0-g1` | `HISTORICAL_RECOVERY_ANCESTOR` | `bb84d0b6c07aaaf781726b7b49612feaf7e40f96` | recovery chronology; already ancestral to `main` |

Retaining these refs does not make them peers of `main`. Before any evidence-bearing hardware epoch, every definition and executable dependency named by the current runbook must resolve from a clean checkout of `main` alone.

## Current epistemic labels

Use only:

- `SOURCE-PROVEN`
- `RUNTIME-PROVEN`
- `NOT PROVEN`
- `UNKNOWN`
- `SUPERSEDED` for historical material

A valid negative campaign result is configuration-scoped `NOT_OBSERVED`; it is never generalized to `R1_DISPROVEN`.
