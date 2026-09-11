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

### Positive-predicate rule for executable gates

An executable gate may return acceptance only from a **positive predicate** that directly establishes the property the gate claims to require. A count of weak indicators, symbol-name coincidence, metadata resemblance, or equality of an unbound scalar is not a substitute for the required evidence.

Every executable gate that can emit PASS/clean closure must carry at least one discriminating **negative control** in its selftest. The negative control must remove or alter the required evidence while keeping weaker look-alikes available, and the gate must fail closed. A selftest that exercises only the happy path is not an acceptance test.

Repository acceptance must execute those negative controls, not merely check that the selftest code exists.

## Identity before causality

Temporal adjacency is insufficient for R2. The chain must close identity across request, mapping, retired IOVA range and post-unmap device access, with no ambiguous remap in the attribution window.

## D_issue vs D_commit

An IOMMU fault can prove an attempted access to a retired mapping when correlation is closed. It does not prove the DMA transaction committed to memory. `D_commit` requires a memory-side observation or equivalent completed-effect evidence.

## Hardware acquisition is also evidence-gated

Hardware procurement follows the same closure discipline as claim promotion. A board is not purchased merely because a source hypothesis survived or because the board is generally useful.

Before any new hardware purchase, the campaign must name the live blocker, define the decisive artifact the hardware can produce, exhaust cheaper equivalent paths, and define the first stop condition. Already-acquired hardware is tested for all inexpensive decisive artifacts before another board is authorized.

The canonical procurement rule, experiment dependency graph, current board order, and budget ledger are maintained in [`HARDWARE-ACQUISITION-GATE.md`](HARDWARE-ACQUISITION-GATE.md).

## The rule being examined

The DMA API documentation states the invariant directly. Quoted from
`Documentation/core-api/dma-api-howto.rst` at
`08df884136f1c1197bab2a27814404fd329d9aac`:

```text
line 715   After the last DMA transfer call one of the DMA unmap routines
           dma_unmap_{single,sg}().

line 675   Every dma_map_{single,sg}() call should have its
           dma_unmap_{single,sg}() counterpart, because the DMA address space
           is a shared resource and you could render the machine unusable by
           consuming all DMA addresses.
```

Both were read out of the tree rather than quoted from memory, and the line
numbers are given so a reviewer can re-check them at that exact commit.

The question this repository investigates is narrower than "is the rule
violated". The source-level sequence in DWC2 is already established: on the
stop-timeout path the driver proceeds to unmap and giveback after warning that
the hardware did not acknowledge the stop. What is **not** established is
whether "the last DMA transfer" has actually occurred at that point on real
DWC2 hardware.

That distinction is the whole hypothesis. It is a hardware-behaviour question,
not a source-rule question, and it is why no amount of source reading closes it.
