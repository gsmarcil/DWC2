# DWC2 R1 — DMA lifetime research

> **Private / embargoed workspace.** This repository is the canonical working record for the DWC2 research campaign. It is intentionally private until the research, coordinated disclosure, and any required publication approval are complete. See [`SECURITY.md`](SECURITY.md).

Research repository for the Linux DWC2 gadget request-unmap lifetime hypothesis and the separate DWC2 PIO RX boundary track.

## Frozen scope

- Kernel: `torvalds/linux`
- Pin: `f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8`
- Primary path: `drivers/usb/dwc2/gadget.c`
- Observer lineage: r3 / ABI v9 (`header=112`, `record=80`)

## Current status

| Claim | State |
|---|---|
| Source path: stop-timeout may continue into teardown | **SOURCE-PROVEN** |
| Source path: request DMA mapping is unmapped before giveback | **SOURCE-PROVEN** |
| Checked-in pre-runtime baseline | **VERIFIED — canonical v4.2 import** |
| Holder event producer compatible with active `holder_merger` | **BLOCKED — imported source is incompatible** |
| R1A trigger/reachability on real DWC2 hardware | **NOT EXECUTED** |
| Real `UNMAP_DONE` for the timed-out request | **NOT PROVEN** |
| Post-unmap DMA attempt (`D_issue`) | **UNKNOWN** |
| Completed post-lifetime memory effect (`D_commit`) | **UNKNOWN** |
| Security-boundary impact | **UNKNOWN** |

**No memory-corruption claim is made in this repository.**

The `baseline/` directory is a byte-identical import of the independently
authenticated v4.2 archive. Its 89 pinned paths and executable pre-runtime gates
are reproducible from this tree. Repository and campaign readiness are gated by:

```sh
./VERIFY-REPOSITORY.sh
```

The baseline-integrity portion reports `REPOSITORY_BASELINE: PASS`. The overall
gate intentionally exits nonzero because the currently preserved device source
cannot produce the JSONL contract consumed by the active `holder_merger`. See
[`docs/HOLDER-PRODUCER-CONTRACT.md`](docs/HOLDER-PRODUCER-CONTRACT.md). This does
not invalidate the imported v4.2 bytes, and it does not change the R1A/R2/R3
runtime states below.

## Evidence ladder

```text
R1A  trigger reachability / natural timeout
  ↓
R2   same retired mapping receives a post-unmap DMA attempt
  ↓
R3   completed memory-side effect after lifetime ended
  ↓
Impact  controllability + changed ownership/security boundary
```

Each transition requires its own artifact. A later claim is never inferred from an earlier one.

## Repository map

- [`r1a-host/`](r1a-host/) — canonical location for the host-side harness source in the next complete epoch.
- [`r1a-device/`](r1a-device/) — canonical location for the preserved legacy FunctionFS source; the compatible holder-event producer is still missing.
- [`docs/HISTORY.md`](docs/HISTORY.md) — research history, keeping only conclusions that survived later audits.
- [`docs/CONFIRMED.md`](docs/CONFIRMED.md) — facts currently accepted.
- [`docs/PIO-RX-TRACK.md`](docs/PIO-RX-TRACK.md) — separate source-proven PIO RX boundary finding.
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — evidence and fail-closed methodology.
- [`docs/HARDWARE-ENVIRONMENTS.md`](docs/HARDWARE-ENVIRONMENTS.md) — development hosts and their evidence limits.
- [`docs/HARDWARE-ACQUISITION-GATE.md`](docs/HARDWARE-ACQUISITION-GATE.md) — result-before-purchase rule, experiment dependencies, board order, and budget ledger.
- [`docs/HARDWARE-PROFILES.md`](docs/HARDWARE-PROFILES.md) — exact board identities, vendor specifications, local visuals, pinned-source facts, and runtime-pending fields.
- [`docs/HARDWARE-COMMANDS.md`](docs/HARDWARE-COMMANDS.md) — board-specific command index for Pi Zero 2 W and any later purchase-authorized target.
- [`docs/hardware/PI-ZERO-2W-PROFILE.md`](docs/hardware/PI-ZERO-2W-PROFILE.md) — Pi Zero 2 W specification/profile and campaign boundaries.
- [`docs/hardware/PI-ZERO-2W-COMMANDS.md`](docs/hardware/PI-ZERO-2W-COMMANDS.md) — copy/paste Pi first-boot, capability, topology, and artifact-capture commands.
- [`docs/hardware/TINKER-BOARD-S-PROFILE.md`](docs/hardware/TINKER-BOARD-S-PROFILE.md) — Tinker Board S/RK3288 specification/profile and revision boundary.
- [`docs/hardware/TINKER-BOARD-S-COMMANDS.md`](docs/hardware/TINKER-BOARD-S-COMMANDS.md) — deferred RK3288/Tinker command runbook, to be used only if `AQ-D1` authorizes the board.
- [`docs/hardware/images/`](docs/hardware/images/) — repository-local hardware identification visuals; exact acquired-unit photographs are added with runtime evidence.
- [`docs/PENDING.md`](docs/PENDING.md) — open claims and blockers.
- [`docs/EVIDENCE-LADDER.md`](docs/EVIDENCE-LADDER.md) — proof contracts for R1A/R2/R3/Impact.
- [`docs/RUNTIME-RUNBOOK.md`](docs/RUNTIME-RUNBOOK.md) — next hardware campaign.
- [`docs/THREAT-MODEL.md`](docs/THREAT-MODEL.md) — attacker/precondition boundaries.
- [`docs/PROVENANCE.md`](docs/PROVENANCE.md) — frozen artifacts and epoch rules.
- [`baseline/`](baseline/) — canonical v4.2 pre-runtime package; `SHA256SUMS` pins all 89 imported paths.
- [`VERIFY-REPOSITORY.sh`](VERIFY-REPOSITORY.sh) — fail-closed baseline-integrity and campaign-readiness gate.

## Working rule

GitHub `main` is the canonical research record. New experiments, tooling changes, and evidence should be committed here with explicit epoch/provenance impact. Local copies are working copies only until their exact bytes/hashes are recorded in this repository.

Do not repair a missing canonical epoch source by recreating it from documentation or memory. Import the original verified artifact, then verify it byte-for-byte.

## Reporting discipline

Use only these epistemic labels unless a stronger artifact is present:

`SOURCE-PROVEN` · `RUNTIME-PROVEN` · `NOT PROVEN` · `UNKNOWN`

Absence of a timeout on a tested configuration is **not** `R1_DISPROVEN`; the strongest allowed negative is a configuration-scoped `NOT_OBSERVED` verdict emitted by a complete frozen gate after all eligibility checks pass.
