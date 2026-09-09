# POST-UNMAP-DMA-001 — G2.5 target feasibility enumeration

## Gate purpose

G2.5 answers two distinct questions without conflating them:

1. Is a named DWC2 target fundamentally capable of exercising the selected R2 path?
2. Is the current rig/build tuple ready to observe that target with admissible identity?

A board must not be rejected merely because a convenience witness (`u_ether`) or a
particular observer has not yet been built.

The qualification order is frozen as follows:

```text
A. BOARD_CAPABLE
B. RIG_BASE_READY
C. DMA_TOPOLOGY_RESOLVED
---------------------------------
   R2-ELIGIBLE NAMED TARGET-BUILD
D. CONVENIENCE / RANKING ONLY
```

`NET_IP_ALIGN` and the stock `u_ether` bounce path belong to D. They are never an
initial board-admission predicate.

## Candidate identity — board is not enough

A G2.5 row is a **target-build tuple**, not merely a board name:

```text
TARGET_BUILD_ID =
    board_id
    + campaign_id
    + architecture
    + kernel_commit
    + toolchain_id
    + config_hash
```

This prevents evidence transfer between two builds on the same hardware. In
particular, PRIMARY-A and PRIMARY-B may use the same physical board after a rebuild,
but they are still distinct target-build tuples if `g_dma_desc`, config, toolchain,
or linked artifact differs.

A single board may therefore satisfy both campaigns only as two separately bound
rows/builds. Alternatively, two different boards may satisfy them.

## Campaign split — no evidence inheritance

L2 has two primary source survivors that require different DWC2 modes. They are
separate campaigns and must not inherit runtime or object evidence from one another.

```text
PRIMARY-A — reset/disconnect ordering
    g_dma      = 1
    g_dma_desc = 0
    mode       = address DMA

PRIMARY-B — DDMA isochronous dequeue
    g_dma      = 1
    g_dma_desc = 1
    endpoint   = isochronous
    chain_started = required
```

A board may qualify for A, B, or both. G2.5 records eligibility per campaign-build,
not as one global boolean.

## A — BOARD_CAPABLE

Immutable/controller capability fields are recorded before convenience ranking:

```text
board_name
board_id
soc
udc_name
udc_driver                     = dwc2
peripheral_gadget_mode         = reachable | unreachable

supports_g_dma                 = yes | no
supports_g_dma_desc            = yes | no
isoc_ep_available              = yes | no

primary_a_address_dma          = reachable | unreachable
primary_a_expected_params      = g_dma=1, g_dma_desc=0
primary_a_reset_path           = reachable | unreachable

primary_b_ddma                 = reachable | unreachable
primary_b_expected_params      = g_dma=1, g_dma_desc=1
primary_b_chain_start          = reachable | unreachable
```

The three capability columns below are mandatory in every candidate matrix:

```text
supports_g_dma
supports_g_dma_desc
isoc_ep_available
```

They are evaluated before `NET_IP_ALIGN` or any stock-canary convenience. A board
that cannot expose the selected campaign mode is not rescued by a convenient
unaligned-buffer path.

A board is not rejected merely because only one campaign mode is available. The
selected campaign determines which capability predicate must be satisfied.

## B — RIG_BASE_READY and build binding

Repairable operator/rig prerequisites are recorded separately:

```text
kernel_control                 = yes | no
dtb_control                    = yes | no
host_bus_reset_trigger         = yes | no        # required by PRIMARY-A
isoc_host_stimulus             = yes | no        # required by PRIMARY-B
observer_build_control         = yes | no
object_disassembly_available   = yes | no        # required to close PRIMARY-B silent-skip gate
```

The build identity is part of the candidate row, not a later annotation:

```text
architecture
toolchain_id
config_hash                    = sha256(exact campaign .config)
kernel_commit
lto_enabled                    = yes | no
```

For a board that supports both campaigns after rebuild, the matrix records two
campaign-specific bindings, for example:

```text
PRIMARY-A row:
    board_id = X
    toolchain_id = T_A
    config_hash = C_A
    g_dma=1, g_dma_desc=0

PRIMARY-B row:
    board_id = X
    toolchain_id = T_B
    config_hash = C_B
    g_dma=1, g_dma_desc=1
```

`T_A == T_B` or `C_A == C_B` must never be assumed. Evidence is scoped to the exact
row that produced it.

### PRIMARY-B named-target OBJECT_GATE binding

The layout-matched x86-64/gcc-13.3 reproducer has closed only the generic lowering
pattern:

```text
silent-skip codegen pattern = PATTERN-PROVEN
scope = x86-64 / gcc 13.3 / -O2 reproducer
```

It is not target closure. For every named PRIMARY-B target-build, G2.5 must record:

```text
board_id
architecture
toolchain_id
config_hash
kernel_commit
gadget_c_sha256
lto_enabled                    = yes | no
debug_source_mapping           = yes | no
object_gate_artifact           = gadget.o | vmlinux | final-module
object_gate_artifact_sha256
object_gate_status             = PENDING_OBJECT_GATE | OBJECT-PROVEN | KILLED | INDETERMINATE
```

Artifact selection is part of feasibility:

```text
if lto_enabled == no:
    gadget.o is admissible

if lto_enabled == yes:
    pre-link gadget.o is inadmissible
    require final vmlinux or final linked module containing DWC2
```

The target gate must be built with debug/source mapping and inspected with
source-interleaved disassembly, for example:

```bash
objdump -dS --disassemble=dwc2_hsotg_ep_dequeue <artifact>
```

The adjudication predicate is pre-registered:

```text
OBJECT-PROVEN
  load hs_ep->req
  -> compare pointer value with req argument
  -> conditional branch remains
  -> no read through hs_ep->req before comparison
  -> NULL path skips stop and reaches complete_request/U

KILLED
  any read through hs_ep->req before comparison
  OR comparison folded to a constant that invalidates the silent-skip model
  OR stop sequence executes unconditionally on the NULL path
```

Do not require a literal `call dwc2_hsotg_ep_stop_xfr`: the helper is static and
may be inlined. The stop arm may instead appear as the inlined SNAK/SGOUTNAK,
EPDIS, and wait sequence.

`PRIMARY_B_R2_ELIGIBLE` may be selected while `object_gate_status` is pending, but
the silent-skip execution claim remains `PENDING_OBJECT_GATE` until the exact
named target-build artifact reaches a terminal verdict.

## C — DMA_TOPOLOGY_RESOLVED

These fields must be known before interpreting a negative canary result:

```text
dma_path                       = direct | bounce(SWIOTLB) | iommu
dma_coherent                   = yes | no
cache_maintenance_at_unmap     = yes | no | not-applicable
driver_local_bounce            = yes | no
```

The ordering matters:

- `dma_path=bounce(SWIOTLB)` can redirect a late device write into the bounce
  allocation rather than the intended canary object. A clean canary is then not
  evidence of no late DMA.
- On a non-coherent platform, cache maintenance at `U` can hide, delay, or create
  CPU-visible state transitions. Canary interpretation is inadmissible until that
  behavior is classified.
- A DWC2-local bounce buffer changes the object actually mapped to the controller
  and must be carried in mapping identity.

Promotion is per campaign-build:

```text
PRIMARY_A_R2_ELIGIBLE =
    supports_g_dma == yes
    && address-DMA/reset path reachable
    && exact PRIMARY-A build binding recorded
    && corresponding rig prerequisites ready
    && DMA topology resolved

PRIMARY_B_R2_ELIGIBLE =
    supports_g_dma == yes
    && supports_g_dma_desc == yes
    && isoc_ep_available == yes
    && DDMA chain-start path reachable
    && exact PRIMARY-B build binding recorded
    && corresponding rig prerequisites ready
    && DMA topology resolved
    && exact target-object gate can be captured/adjudicated
```

## Candidate matrix schema

Every enumerated target should be represented with at least these columns before
ranking:

| Field | Meaning |
|---|---|
| `board_id` | stable physical-board identity |
| `soc` | SoC/controller identity |
| `arch` | target architecture |
| `supports_g_dma` | address DMA capability |
| `supports_g_dma_desc` | DDMA capability |
| `isoc_ep_available` | usable isochronous endpoint |
| `primary_a_reset_path` | host-triggerable reset/disconnect path |
| `primary_b_chain_start` | reachable NAK/OUTTKNEPDIS DDMA-isoc start |
| `kernel_control` | exact kernel rebuild/control available |
| `dtb_control` | device-tree control available |
| `dma_path` | direct / SWIOTLB / IOMMU |
| `dma_coherent` | platform DMA coherency |
| `toolchain_id` | exact compiler/linker tuple for this row |
| `config_hash` | SHA256 of exact campaign config |
| `lto_enabled` | determines admissible object artifact |
| `campaign_id` | PRIMARY-A or PRIMARY-B |
| `r2_eligible` | derived verdict after A+B+C |
| `effective_net_ip_align` | convenience/ranking only |
| `stock_u_ether_canary_shortcut` | convenience/ranking only |

This schema intentionally permits two rows for one board when PRIMARY-A and
PRIMARY-B require separate builds.

## D — convenience / witness ranking

Convenience fields are evaluated only among already eligible target-builds:

```text
effective_net_ip_align
net_ip_align_mod4_nonzero      = ((effective_net_ip_align & 3) != 0)
udc_quirk_avoids_skb_reserve   = yes | no
u_ether_reserve_executed       = yes | no
bounce_path_reachable          = <function>: yes | no
stock_u_ether_canary_shortcut  = yes | no
custom_gadget_canary_feasible  = yes | no
```

`net_ip_align_nonzero` is deliberately not used: DWC2 tests `(long)req_buf & 3`,
so a non-zero alignment value that is still a multiple of four does not activate
the local bounce path.

For the stock `u_ether` RX shortcut:

```text
((effective_NET_IP_ALIGN & 3) != 0)
&& udc_quirk_avoids_skb_reserve == no
&& u_ether RX path reachable
```

`u_ether` conditionally calls `skb_reserve(skb, NET_IP_ALIGN)` only when
`dev->no_skb_reserve` is false. That value originates from the gadget/UDC
`quirk_avoids_skb_reserve` policy. The pinned DWC2 source audit found no DWC2
assignment of `quirk_avoids_skb_reserve` (nor `quirk_ep_out_aligned_size`) in
`gadget.c`, `core.h`, or `params.c`; the field remains explicit because it is a UDC
property, not an architecture property.

Critical non-implication:

```text
stock_u_ether_canary_shortcut = no
    !=>
G6 = BLOCKED
```

The stock path is only a convenience witness. G6 may use a new-epoch custom gadget
function that owns and identities its own DMA buffer, subject to frozen provenance
rules.

## `u_ether` architecture filter

Pinned Linux source:

```text
commit: f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
u_ether.c sha256: b2f84b7b9a97a3dd46b27114d24ab3755af7182999dcf0e37a97d8ec4fba45e4
```

The generic fallback is:

```c
#ifndef NET_IP_ALIGN
#define NET_IP_ALIGN 2
#endif
```

Verified source values:

| Kernel architecture | Effective value known from source | Stock u_ether offset candidate |
|---|---:|---|
| arm64 | `0` | DEAD |
| x86 | `0` | DEAD |
| arm32 | no definition in `arch/arm/include/asm/processor.h`; generic fallback is `2` | `PENDING_PREPROCESSOR_CONFIRM` |

The ARM32 row is not promoted until the exact target kernel build is preprocessed
or compiled and the effective value is retained as a build artifact. This table
ranks qualified target-builds; it does not qualify them.

## FunctionFS filter

Standard FunctionFS is not a route to DWC2's local unaligned-buffer bounce:
non-SG I/O gives DWC2 a kernel `kmalloc` buffer and SG I/O sets `req->buf=NULL`.

```text
FunctionFS -> DWC2 unaligned bounce = DEAD
```

This only kills that convenience witness; it does not block FunctionFS as a holder
mechanism for PRIMARY-A and does not block a custom G6 canary.

## Canary feasibility

`canary_feasible` is derived only after topology is known:

```text
canary_feasible =
    selected_campaign_R2_ELIGIBLE
    && mapping identity can be preserved/proven
    && observer semantics are valid for dma_path/coherency
    && (stock_u_ether_canary_shortcut || custom_gadget_canary_feasible)
```

For a no-IOMMU board, attribution additionally requires:

```text
commit_content_matches_host_payload = REQUIRED
```

A generic memory change is insufficient to attribute `D_commit` to DWC2.

## R2/R3 implication rule

R2 may also be discharged by a qualified R3 artifact:

```text
D_commit
&& same_epoch
&& same_mapping
&& NO_REMAP
&& (same_device/SID || commit_content_matches_host_payload when no IOMMU)
    => D_issue
```

The reverse implication is invalid:

```text
D_issue !=> D_commit
```

For PRIMARY-B, G4 additionally must not infer mapping identity from DDMA queue
position alone. Runtime records must bind descriptor identity, request identity,
mapping identity, and dequeue sequence explicitly.

## G2.5 exit

Normal exit for either campaign:

```text
at least one named target-build
&& campaign-specific BOARD_CAPABLE predicate
&& campaign-specific RIG_BASE_READY/build binding
&& DMA_TOPOLOGY_RESOLVED
=> G2.5 PASS for that campaign
```

One physical board can satisfy both exits only through separately recorded
campaign-build tuples. If no enumerated target-build satisfies a campaign:

```text
G2.5_TARGET_SET = EMPTY
=> reorder to G3 -> G4 -> G6
```

Canary remains primary and IOMMU optional. Missing stock `u_ether` is not an
empty-target condition.

## Current G2.5 status

```text
source/architecture convenience filter:
    arm64 stock u_ether bounce   DEAD
    x86 stock u_ether bounce     DEAD
    arm32 stock u_ether bounce   CANDIDATE / PREPROCESSOR CONFIRM REQUIRED

DWC2 quirk audit:
    quirk_avoids_skb_reserve assignment in audited DWC2 files  NOT OBSERVED

mandatory capability columns:
    supports_g_dma
    supports_g_dma_desc
    isoc_ep_available

mandatory build-binding columns:
    toolchain_id
    config_hash

PRIMARY-B codegen pattern      PATTERN-PROVEN (x86-64/gcc13.3/-O2 reproducer)
PRIMARY-B target object        PENDING_OBJECT_GATE
PRIMARY-A named target-build   NOT YET FROZEN
PRIMARY-B named target-build   NOT YET FROZEN
DMA topology                   NOT YET FROZEN
G2.5 exit                      NOT REACHED
```