# Research gap review — 2026-09-08

> **HISTORICAL SNAPSHOT — SUPERSEDED.** This file records the execution plan as it stood on 2026-09-08. It is retained for audit chronology and must not be used as the current run order. Current state and execution semantics live in `EVIDENCE-LADDER.md`, `RUNTIME-RUNBOOK.md`, `PENDING.md`, `HARDWARE-ACQUISITION-GATE.md`, `INJURED-SURFACE-TABLE.md`, and the `POST-UNMAP-DMA-*` source-foundation ledgers now carried on `main`.

This document records the historical execution order for closing the DWC2 research record as of 2026-09-08. It does not promote any pending claim and does not override later canonical documents.

## Repository prerequisites

### G0 — Restore the canonical evidence epoch baseline

Status: **CLOSED** by the authenticated v4.2 import and baseline-sub-gate PASS.

`baseline/` must be restored as one byte-identical unit from the independently hash-verified canonical archive. Do not repair the fragment by editing individual files or by regenerating `SHA256SUMS` from the fragment.

Exit gate:

```text
clean checkout
+ every path in baseline/SHA256SUMS present, tracked, not ignored, byte-identical
+ executable EPOCH_ARTIFACTS contract resolves
+ `REPOSITORY_BASELINE: PASS` from `./VERIFY-REPOSITORY.sh`
```

### G1 — Import the actual harness sources and bind them to the next active epoch

Status: **OPEN — COMPATIBLE DEVICE PRODUCER MISSING**.

Canonical source locations:

```text
r1a-host/r1a_host.c
r1a-device/r1a_ffs_out_v2.c
```

The original tested bytes, build inputs/results, and source/binary/image hashes must be retained. The historical v4.2 epoch must not be rewritten to pretend it contained `device_harness`; that key belongs to the later expanded epoch.

The host source is canonical. The device path contains an earlier revision that
cannot emit the JSONL schema consumed by the active `holder_merger`. Obtain the
original matching producer, round-trip its output through the merger, then bind
its exact source/binary and the remaining external artifacts.

### G2 — State consistency

Status: **CLOSED FOR THE v4.2 BASELINE / G1 BLOCK EXPLICIT**. Current
documentation distinguishes the verified pre-runtime baseline, incompatible
device producer, and still-unexecuted runtime claims.

Documentation must distinguish historical verification of an archived package from reproducibility of the current checkout. A fragment must never be labelled a verified executable baseline.

## Research gates

### G3 — Reproducible real-hardware R1A protocol

Qualify the board/SoC/DWC2 revision/PHY/firmware/bootloader, USB topology, host HCD and gadget UDC identities, full kernel config/command line/DTB/image hashes, toolchains and exact build/run commands. Freeze attempt count, stopping rule and negative interpretation. Require positive controls for every observer and negative controls for contamination/misbinding.

Exit: one valid correlated natural-timeout attempt, or a complete eligible campaign whose strongest result is configuration-scoped `NOT_OBSERVED`.

### G4 — Runtime `UNMAP_DONE` and mapping identity

Capture request identity, IOVA/range, length, device, epoch and event ordering. Define linear/SG/partial-map and IOVA-reuse semantics. Require discriminating positive/negative observer selftests.

Exit: an artifact tying `UNMAP_DONE` to the same request/mapping without temporal-nearness inference.

### G5 — R2 / `D_issue`

Use a platform with a documented IOMMU/fault path. Freeze controller/device/SID identity, ordering mechanism, `NO_REMAP` over the retired range, and an injected known-fault capture control.

Exit: same request -> retired mapping -> same controller/SID accesses the retired range after `UNMAP_DONE`, with no intervening remap. This proves `D_issue`, not `D_commit`.

### G6 — R3 / `D_commit`

Design an isolated canary/marker experiment with explicit cache-coherency and memory-barrier semantics, before/after snapshots, CPU-write controls, and no secrets or third-party memory. Distinguish blocked transactions from completed memory effects.

Exit: a post-lifetime memory effect that cannot be explained by CPU writes, allocation reuse or remapping. Otherwise `D_commit` remains `UNKNOWN`.

### G7 — Generalization matrix

After first proof, separate exploratory tuning from a frozen confirmation campaign across relevant DWC2/SoC revisions, kernels, USB speeds, PHYs, request sizes and permitted teardown branches.

### G8 — Independent PIO RX track

Keep PIO RX evidence separate from DMA-lifetime evidence. Add a real-hardware harness for `len % 4 != 0`, measure physical versus logical write extent, and determine whether the 1–3 byte excess remains within allocation capacity or crosses an object/allocation boundary.

### G9 — Security impact and deployment model

Only after memory-effect evidence, establish affected gadget functions/deployments, host/device privileges and reachability, ownership after reuse, content/destination controllability, reliability and the actual security boundary. Do not assign final CVSS/CVE from R1A or an IOMMU fault alone.

## Documentation and automation gates

### G10 — Generated source-audit ledger

For every source claim record pinned commit, file/function, exact line/range or patch identity, call chain and a reproducible source-audit artifact. Extend explicitly to relevant vendor/version branches rather than assuming upstream equivalence.

### G11 — Artifact schema and data dictionary

Define versioned schemas for observer dumps, usbmon/holder evidence, manifests and gate/verdict outputs, including units, ordering clocks, missing values, normalization and raw-file hashing before transformation. Include a small sanitized example.

### G12 — Continuous clean-checkout verification

CI should run repository completeness, parser/gate/verdict selftests, sanitizer builds and deliberately corrupted fixtures (wrong ABI, truncation, `lost>0`, epoch mismatch, remap ambiguity, foreign traffic). While G0/G1 are open, CI failure is expected and must not be weakened into PASS.

### G13 — Disclosure and metadata hygiene

Maintain an internal contact/disclosure log, embargo owner/decision point, raw-evidence retention policy and a publication scrub checklist for serials, paths, device names and unnecessary timestamps before sharing material outside the private workspace.

## Required order

```text
G0 -> G1
       |
       +-> G10/G11/G12
               |
               +-> G3 -> G4 -> G5 -> G6 -> G7/G9

G8 runs in parallel as a separate evidence track.
G13 must be complete before external publication.
```

## Decision rule

Do not begin an evidence-bearing hardware campaign before G0 and G1 are closed. Each experiment may close only its own rung: timeout does not imply unmap; fault does not imply completed memory effect; memory effect does not imply security severity without ownership/attacker-boundary proof.
