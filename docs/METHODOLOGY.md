# Methodology frozen by the campaign

## Evidence labels

Use only evidence states justified by an artifact:

- `SOURCE-PROVEN`
- `RUNTIME-PROVEN`
- `NOT PROVEN`
- `UNKNOWN`

## Guard vs detector

A detector is not a guard merely because it observes an invalid state. A guard qualifies only when its branch changes control/data flow so the forbidden effect cannot commit (for example return, clamp, abort, or a path that cannot reach the effect).

## Source audit is a filter, not closure

A clean source predicate does not close a hypothesis if the physical effect has a different extent or if mode-specific/state-machine behavior changes the safety condition. Safety equivalence must be proven over the relevant parameter space.

## Positive and negative evidence

A single complete positive artifact can close its claim.

Negative evidence is much stricter:

- the run must be sensitive to the target path;
- all attempts contributing to the denominator must be valid;
- artifact loss, witness mismatch, foreign traffic or epoch mismatch fail closed;
- absence is configuration scoped;
- no negative result is carried across an epoch change.

## Identity before causality

Temporal adjacency is insufficient for R2. The chain must close identity across request, mapping, retired IOVA range and post-unmap device access, with no ambiguous remap in the attribution window.

## D_issue vs D_commit

An IOMMU fault can prove an attempted access to a retired mapping when correlation is closed. It does not prove the DMA transaction committed to memory. `D_commit` requires a memory-side observation or equivalent completed-effect evidence.

## Hardware acquisition is also evidence-gated

Hardware procurement follows the same closure discipline as claim promotion. A board is not purchased merely because a source hypothesis survived or because the board is generally useful.

Before any new hardware purchase, the campaign must name the live blocker, define the decisive artifact the hardware can produce, exhaust cheaper equivalent paths, and define the first stop condition. Already-acquired hardware is tested for all inexpensive decisive artifacts before another board is authorized.

The canonical procurement rule, experiment dependency graph, current board order, and budget ledger are maintained in [`HARDWARE-ACQUISITION-GATE.md`](HARDWARE-ACQUISITION-GATE.md).
