# Hardware acquisition gate — result before purchase

This file is the procurement control for the DWC2 campaign. Hardware is bought to resolve a live experimental dependency, not because it is generally useful or because a source hypothesis merely survived review.

## Normative rule

A new board or accessory MUST NOT be purchased unless all of the following are true:

1. a specific live hypothesis or blocker is named;
2. the exact decisive artifact expected from the hardware is defined;
3. cheaper paths have been exhausted or shown not to answer the same question (source audit, model, existing hosts, emulation, already-acquired hardware);
4. the candidate is the cheapest practical hardware path to that artifact, including required adapters/cables/power/storage;
5. a first definitive stop condition is defined before purchase;
6. the purchase and delivered cost are entered in the budget ledger.

`SURVIVED_SOURCE_KILL_ATTEMPT` is never, by itself, a purchase authorization.

The campaign rule is:

```text
RESULT -> unresolved dependency -> hardware necessity -> purchase
```

not:

```text
interesting board -> purchase -> look for a use
```

## Acquisition states

Use only these states in this file:

- `ACQUIRED / IN_TRANSIT` — already paid for; extract maximum useful evidence before another purchase.
- `ACTIVE PRIMARY` — current board on which the next decisive tests run.
- `JUSTIFIED / NOT YET BOUGHT` — all purchase gates passed, but no order has been placed.
- `DEFERRED` — technically useful, but an earlier experiment can remove the need for it.
- `SUBSTITUTE` — may replace, not accompany, another candidate for the same dependency.
- `SECONDARY-ONLY` — purchase only after a primary leaves board-specific ambiguity.
- `DO NOT BUY` — no remaining unique experiment justifies it.

Only one not-yet-bought board should normally be `JUSTIFIED` at a time.

## Experiment namespaces

Procurement experiment IDs use the `AQ-*`, `PI-*`, and `RK-*` prefixes. They are intentionally separate from `P0..P5` in `PENDING.md` so the acquisition ledger cannot be confused with the evidence ladder.

## Dependency graph

```text
AQ-S0  source/model kill attempts                         cost EUR 0
   |
   v
Pi Zero 2 W (already acquired)
   |
   +--> PI-FB1  real DWC2 UDC + usable peripheral state
   |       | FAIL
   |       +----------> kill Pi runtime branch; do not generalize to RK3288
   |
   +--> PI-FB2  GHWCFG4.DESC_DMA / effective gadget descriptor-DMA capability
   |       | 0
   |       +----------> PRIMARY-B_ON_PI killed only
   |
   +--> PI-R1A  cheapest real-hardware R1A reachability/timeout attempt
   |       | primitive killed decisively
   |       +----------> no second-board purchase for that primitive
   |
   +--> PI-G25  Pi-specific DMA topology and actual mapping classification
   |
   +--> PI-G6   memory-side canary work only if its prerequisites survive
   |
   v
AQ-D1  post-Pi purchase decision
   |
   +--> no unique unresolved hardware dependency --------> EUR 0 additional
   |
   +--> RK3288-specific topology/PRIMARY-B blocker alive
           |
           v
       Tinker Board S purchase may become JUSTIFIED
           |
           +--> RK-FB0  running .config: ARM_LPAE/SWIOTLB/boot parameters
           +--> RK-FB1  DWC2 UDC + actual peripheral state
           +--> RK-FB2  GHWCFG4.DESC_DMA / effective g_dma_desc
           +--> RK-G25  dma_ops/IOMMU/dma-ranges/SWIOTLB/actual mapping path
           +--> RK-R1   R1/R2/R3 work enabled by surviving topology
           |
           v
       AQ-D2
           |
           +--> decisive result --------------------------> stop buying
           +--> board-specific ambiguity only
                    |
                    v
              one SECONDARY-ONLY RK3288 board
```

## Source-prearrival eliminations for Pi

The pinned DWC2 BCM platform parameters do not override gadget DMA enablement or descriptor-DMA enablement. `dwc2_set_bcm_params()` changes only host FIFO/transfer/count/AHB parameters. Gadget defaults remain hardware-derived:

```text
PI: g_dma      <- dma_capable derived from hardware capability
PI: g_dma_desc <- hw->dma_desc_enable derived from GHWCFG4.DESC_DMA
```

Therefore the previously plausible branch "BCM platform parameters force gadget DMA off, so the DWC2 unmap path is unreachable on Pi" is killed at source for the pinned tree. This does not prove that the Pi hardware reports DMA-capable or descriptor-DMA-capable; those remain first-boot facts.

This source result matters to procurement because it preserves the Pi as a meaningful PRIMARY-A runtime target without buying another board merely to avoid a platform-parameter override that does not exist.

## Why each experiment exists

| ID | Board | Question | Decisive artifact | What it can save us from buying | Dependency created if it survives |
|---|---|---|---|---|---|
| `AQ-S0` | none | Can source/model evidence kill the required topology or primitive? | source contradiction or surviving predicate set | every board whose only purpose was the killed predicate | first real-hardware question only |
| `PI-FB1` | Pi Zero 2 W | Is a real DWC2 gadget UDC reachable in usable peripheral state? | `/sys/class/udc` identity plus actual peripheral/operational state | any board bought merely to obtain first DWC2 runtime | enables `PI-R1A` |
| `PI-FB2` | Pi Zero 2 W | Does this controller expose descriptor DMA for gadget mode? | `GHWCFG4.DESC_DMA` and effective parameter state | prevents buying accessories or building a PRIMARY-B plan that Pi cannot execute | if dead only on Pi, may justify another topology later |
| `PI-R1A` | Pi Zero 2 W | Does the R1 trigger/timeout primitive survive on real hardware? | frozen R1A artifact or configuration-scoped negative | potentially all later hardware if the core primitive is killed | surviving blocker must be named before another purchase |
| `PI-G25` | Pi Zero 2 W | What DMA translation actually occurs on this board? | CPU physical address, DMA address, translated physical address, backend/IOMMU state, and direct bounce-membership observation | prevents transferring false DMA assumptions to RK3288 and buying on a bad premise | establishes Pi-only topology |
| `PI-G6` | Pi Zero 2 W | Can a memory-side effect be observed without cache ambiguity? | mapped, cache-line-isolated canary after the required ownership transition | may produce the needed completed-effect evidence without a second board | only if the relevant primitive and mapping model survive |
| `RK-FB0` | Tinker S | What kernel topology actually booted? | running `.config` plus boot parameters | can immediately kill assumptions about LPAE/SWIOTLB before custom builds | enables valid interpretation of `RK-G25` |
| `RK-FB1` | Tinker S | Is the RK3288 DWC2 UDC actually usable as the target role? | UDC identity plus actual operational peripheral state | avoids spending on a secondary RK3288 board when role bring-up is the real blocker | enables RK runtime tests |
| `RK-FB2` | Tinker S | Is gadget descriptor DMA available? | `GHWCFG4.DESC_DMA` -> effective gadget parameter | can kill PRIMARY-B on this platform before deeper instrumentation | surviving PRIMARY-A/R1 work remains separate |
| `RK-G25` | Tinker S | Is this mapping direct, translated, IOMMU-backed, or SWIOTLB-bounced? | per-mapping classification, not boot-log inference | decides whether the board actually supplies the topology for which it was bought | enables topology-dependent R2/R3/G6 work |
| `RK-R1` | Tinker S | Does the remaining R1/R2/R3 hypothesis survive on the desired topology? | claim-specific runtime artifact | if decisive, eliminates all redundant RK3288 purchases | only board-specific ambiguity may authorize a secondary |

## First-boot collection rule

`PI-FB1 -> PI-FB2` is the logical decision order, not a requirement for separate boots. `GHWCFG4` is hardware configuration state and can be captured during the same first boot even if role bring-up later fails because of cable, overlay, or host conditions.

Therefore the first Pi boot should collect both artifacts opportunistically:

```text
PI-FB1: UDC identity + role/operational state
PI-FB2: GHWCFG4.DESC_DMA + effective g_dma_desc
```

Interpretation remains separate:

```text
PI-FB1 FAIL -> Pi runtime branch blocked/killed for that configuration
PI-FB2 = 0  -> PRIMARY-B_ON_PI killed only
```

A failure in one does not erase a valid artifact from the other.

## G2.5 mapping classification rule

Never classify a mapping from `req->dma == virt_to_phys(req->buf)` alone. Bus translations can make the raw values differ without a bounce buffer.

For each evidence-bearing mapping, record at minimum:

```text
cpu_va
cpu_phys
dma_addr
translated_dma_phys
dma_ops/backend
iommu_mapped
dma_mask
bus_dma_limit
dma-ranges / active DT context
bounce_membership
bounce_membership_method
```

The field is semantic: `bounce_membership` means whether the mapped physical address belongs to a SWIOTLB bounce pool (or equivalent bounce backing). The exact helper used is build/configuration-bound evidence and must be recorded in `bounce_membership_method`; do not hard-code one helper name into the evidence contract.

Interpretation:

```text
backend = dma-direct
cpu_phys == translated_dma_phys
bounce_membership = false
    -> DIRECT_NO_BOUNCE

bounce_membership = true
    -> SWIOTLB_BOUNCE

raw dma_addr != cpu_phys
but translated_dma_phys == cpu_phys
and bounce_membership = false
    -> bus translation / dma-ranges, not bounce
```

Pi and RK3288 MUST have separate G2.5 rows. No topology conclusion transfers between them.

### Observer-linkage constraint

The mapping observer implementation must be chosen only after the running kernel configuration is known.

At the pinned ARM32 tree, `dma_to_phys()` is provided as a static inline in `include/linux/dma-direct.h` when `CONFIG_ARCH_HAS_PHYS_TO_DMA` is not selected, so it does not inherently require an exported module symbol. Nevertheless this header is DMA-internal rather than a stable module API, so the actual observer build and modpost result must be preserved as evidence instead of assuming portability.

For SWIOTLB membership, helper availability depends on the exact configuration. In particular, an inline helper may call a non-exported internal routine under a dynamic-SWIOTLB configuration. If an out-of-tree loadable observer cannot link the required helper, use either an in-tree observer/patch or another configuration-correct direct observation. Do not substitute address inequality as a bounce detector.

## G6 canary placement rule

For a memory-side canary experiment, keep the canary inside the DMA-mapped allocation but after the logical request boundary. Place the logical boundary at a cache-line boundary and dedicate complete cache line(s) to the canary.

```text
[ DMA-mapped allocation                         ]
[ logical request ][ full-cache-line canary ... ]
                   ^ forbidden logical boundary
```

This separates request-boundary violation from mapping-boundary violation and avoids treating an un-synchronized external canary as evidence.

## Current acquisition ledger

| Priority | Candidate | State | Unique purpose | Dependency before purchase |
|---:|---|---|---|---|
| 1 | Raspberry Pi Zero 2 W | `ACQUIRED / IN_TRANSIT` | cheapest first real DWC2 PRIMARY-A and prerequisite-kill platform | none; already acquired |
| 2 | ASUS Tinker Board S / RK3288 | `DEFERRED` | RK3288-specific DMA topology and possible PRIMARY-B path | `AQ-D1` must show a live blocker that Pi cannot decide |
| 3 | Firefly-RK3288 | `SECONDARY-ONLY` | distinguish a Tinker-board-specific failure from an RK3288-wide result | Tinker tested first and ambiguity proven board-specific |
| alt | MiQi RK3288 | `SUBSTITUTE` | substitute RK3288 target if it is the cheaper/faster way to the same artifact | use instead of, not in addition to, Tinker/Firefly unless a new unique dependency is recorded |
| alt | Radxa Rock 2 Square | `SUBSTITUTE` | same substitution role | same rule as MiQi |

The candidate order is not a shopping list. A lower row is never purchased merely because the rows above it were tested.

## Budget ledger

The financial ceiling is external to technical evidence, but every hardware decision must be visible here before purchase.

```text
CAMPAIGN_HW_BUDGET_EUR   = UNSET
COMMITTED_EUR            = actual paid price of acquired items, including shipping
RESERVED_EUR             = EUR 0 unless one specific JUSTIFIED purchase exists
REMAINING_EUR            = BUDGET - COMMITTED - RESERVED
```

Do not invent missing prices. Replace `UNSET`/unknown entries from receipts or order confirmations.

| Item | State | Item EUR | Shipping EUR | Required accessories EUR | Total delivered EUR | Experiment unlocked | Can another owned item answer it? |
|---|---|---:|---:|---:|---:|---|---|
| Raspberry Pi Zero 2 W | acquired / in transit | TBD | TBD | TBD | TBD | `PI-FB1`, `PI-FB2`, `PI-R1A`, `PI-G25`, conditional `PI-G6` | already selected as current primary |
| Tinker Board S | deferred | TBD | TBD | TBD | TBD | `RK-FB0/1/2`, `RK-G25`, topology-dependent runtime | decision pending Pi results |
| RK3288 secondary | secondary-only | TBD | TBD | TBD | TBD | board-specific replication only | forbidden until primary ambiguity exists |

## Purchase authorization record

Before changing a not-yet-bought candidate to `JUSTIFIED`, add a block in this file or a linked receipt note containing:

```text
HYPOTHESIS:          exact live claim/blocker
SUCCESS_ARTIFACT:    observable result the board can produce
CHEAPER_PATHS:       source/model/existing-hardware alternatives already exhausted
WHY_THIS_BOARD:      unique capability needed for the artifact
STOP_CONDITION:      first result that ends this hardware branch
DELIVERED_COST_EUR:  item + shipping + mandatory accessories
BUDGET_AFTER_EUR:    remaining campaign budget after purchase
REUSE/RESALE:        optional value; never substitutes for experimental necessity
AUTHORIZATION:       JUSTIFIED / DEFERRED / DO NOT BUY
```

If any required field is unknown, authorization remains `DEFERRED`.

## Anti-waste rules

1. Extract all inexpensive decisive tests from an acquired board before buying another.
2. Never buy two boards simultaneously to answer the same unresolved question.
3. A second board with the same SoC family requires a demonstrated board-specific ambiguity, not a desire for replication.
4. Failure on Pi never automatically kills RK3288; success on Pi never automatically proves RK3288 topology.
5. A board capability failure (`PRIMARY-B_ON_PI`, for example) is platform-scoped unless the underlying claim itself is killed.
6. Accessories are hardware spend and need the same dependency justification when they are not already owned.
7. Prefer the candidate with the lowest total delivered cost that produces the same decisive artifact with acceptable setup risk.
8. Stop spending as soon as the live hypothesis is decisively proven, killed, or no longer blocked by hardware.

## Current decision

```text
CURRENT PRIMARY          Raspberry Pi Zero 2 W — ACQUIRED / IN TRANSIT
FIRST BOOT COLLECTION    PI-FB1 + PI-FB2 in the same boot
LOGICAL DECISION ORDER   PI-FB1 -> PI-FB2 -> PI-R1A -> PI-G25 -> conditional PI-G6
NEXT PURCHASE            NONE AUTHORIZED
TINKER BOARD S           DEFERRED pending AQ-D1 after Pi evidence
SECOND RK3288 BOARD      NOT AUTHORIZED
```

This document controls procurement only. Evidence promotion remains governed by `METHODOLOGY.md`, `EVIDENCE-LADDER.md`, `PROVENANCE.md`, and the active repository gates.
