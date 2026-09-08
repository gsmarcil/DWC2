# DWC2 R1 — DMA lifetime research

> **Private / embargoed workspace.** This repository is the canonical working record for the DWC2 research campaign. It is intentionally private until the research, coordinated disclosure, and any required publication approval are complete. See [`SECURITY.md`](SECURITY.md).

Research repository for the Linux DWC2 gadget request-unmap lifetime hypothesis and the separate DWC2 PIO RX boundary track.

## Frozen scope

- Kernel: `torvalds/linux`
- Pin: `f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8`
- Primary path: `drivers/usb/dwc2/gadget.c`
- Observer: r3 / ABI v9 (`header=112`, `record=80`)

## Current status

| Claim | State |
|---|---|
| Source path: stop-timeout may continue into teardown | **SOURCE-PROVEN** |
| Source path: request DMA mapping is unmapped before giveback | **SOURCE-PROVEN** |
| R1A trigger/reachability on real DWC2 hardware | **NOT EXECUTED** |
| Real `UNMAP_DONE` for the timed-out request | **NOT PROVEN** |
| Post-unmap DMA attempt (`D_issue`) | **UNKNOWN** |
| Completed post-lifetime memory effect (`D_commit`) | **UNKNOWN** |
| Security-boundary impact | **UNKNOWN** |

**No memory-corruption claim is made in this repository.**

The current evidence/tooling baseline is under [`baseline/`](baseline/). It closes the pre-runtime evidence/provenance pipeline; it does not substitute for real hardware evidence.

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

- [`docs/HISTORY.md`](docs/HISTORY.md) — research history, keeping only conclusions that survived later audits.
- [`docs/CONFIRMED.md`](docs/CONFIRMED.md) — facts currently accepted.
- [`docs/PIO-RX-TRACK.md`](docs/PIO-RX-TRACK.md) — separate source-proven PIO RX boundary finding.
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — evidence and fail-closed methodology.
- [`docs/HARDWARE-ENVIRONMENTS.md`](docs/HARDWARE-ENVIRONMENTS.md) — development hosts and their evidence limits.
- [`docs/PENDING.md`](docs/PENDING.md) — open claims and blockers.
- [`docs/EVIDENCE-LADDER.md`](docs/EVIDENCE-LADDER.md) — proof contracts for R1A/R2/R3/Impact.
- [`docs/RUNTIME-RUNBOOK.md`](docs/RUNTIME-RUNBOOK.md) — next hardware campaign.
- [`docs/THREAT-MODEL.md`](docs/THREAT-MODEL.md) — attacker/precondition boundaries.
- [`docs/PROVENANCE.md`](docs/PROVENANCE.md) — frozen artifacts and epoch rules.
- [`baseline/`](baseline/) — verified pre-runtime tooling and kernel observer package.

## Working rule

From this point onward, GitHub `main` is the canonical research record. New experiments, tooling changes, and evidence should be committed here with explicit epoch/provenance impact. Local copies are working copies only until their hashes/changes are recorded in this repository.

## Reporting discipline

Use only these epistemic labels unless a stronger artifact is present:

`SOURCE-PROVEN` · `RUNTIME-PROVEN` · `NOT PROVEN` · `UNKNOWN`

Absence of a timeout on a tested configuration is **not** `R1_DISPROVEN`; the strongest allowed negative is a configuration-scoped `NOT_OBSERVED` verdict emitted by the frozen gate after all eligibility checks pass.
