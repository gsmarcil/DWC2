# POST-UNMAP-DMA-001 — G2.5 target feasibility enumeration

## Gate purpose

G2.5 answers whether a **named target-build tuple** can exercise one of the surviving
POST-UNMAP-DMA-001 campaigns with admissible identity. Board capability, build/DTB
identity, DMA topology, rig readiness, and convenience witnesses are kept separate.

The qualification order is frozen as:

```text
1. CONTROLLER / CAMPAIGN CAPABILITY
2. BUILD + DTB BINDING
3. DMA TOPOLOGY / COHERENCY RESOLUTION
4. RIG READY FOR THE SELECTED CAMPAIGN
-------------------------------------------------
   R2-ELIGIBLE NAMED TARGET-BUILD
5. CONVENIENCE / RANKING ONLY
```

Steps 2 and 3 are evaluated together in practice because `dma_path` and DMA coherency
can change with the exact DTB and kernel configuration. `NET_IP_ALIGN` and stock
`u_ether` are never board-admission predicates.

## Candidate identity — board identity is insufficient

A row is one exact campaign build:

```text
TARGET_BUILD_ID =
    board_id
    + campaign_id
    + architecture
    + kernel_commit
    + toolchain_id
    + config_hash
    + dtb_hash
```

`dtb_hash` is mandatory on DT platforms. It is independent from `config_hash` and may
change `dma-ranges`, `dma-coherent`, `iommus`, role selection, PHY wiring, and therefore
`dma_path` or coherency without changing the kernel binary.

No runtime, OBJECT_GATE, R2, or R3 result transfers between rows with different
`TARGET_BUILD_ID` values.

One physical board may satisfy PRIMARY-A and PRIMARY-B only as two separately bound
rows/builds. Two different boards are also permitted.

## Campaign split — no evidence inheritance

```text
PRIMARY-A — reset/disconnect ordering
    g_dma      = 1
    g_dma_desc = 0
    mode       = address DMA

PRIMARY-B — DDMA isochronous dequeue
    g_dma      = 1
    g_dma_desc = 1
    endpoint   = isochronous
    chain_started = required at runtime
```

PRIMARY-A and PRIMARY-B are separate campaigns. A board supporting both modes still
produces two campaign rows if the config, DTB, linked artifact, or toolchain differs.

## 1 — CONTROLLER / CAMPAIGN CAPABILITY

Only immutable or SoC/controller-level capability belongs here:

```text
board_name
board_id
soc
udc_name
udc_driver                     = dwc2
peripheral_gadget_mode         = reachable | unreachable

supports_g_dma                 = yes | no | unknown
supports_g_dma_desc            = yes | no | unknown
isoc_ep_available              = yes | no | unknown

primary_a_address_dma          = reachable | unreachable | unknown
primary_a_reset_path           = reachable | unreachable | unknown

primary_b_ddma                 = reachable | unreachable | unknown
```

The mandatory board-capability columns are:

```text
supports_g_dma
supports_g_dma_desc
isoc_ep_available
```

`isoc_ep_available` means the DWC2 controller exposes a usable isochronous endpoint.
It does **not** mean the current rig has a gadget function that opens it.

The source pin auto-derives gadget DMA mode from hardware capability:

```text
g_dma      = controller architecture is DMA-capable
g_dma_desc = hw_params.dma_desc_enable
```

A historical board/platform setting is corroboration but does not replace the exact
named target's hardware/config artifact when the current source pin auto-detects a
field.

## 2 — BUILD + DTB BINDING

The build/description inputs are part of the candidate row before topology is judged:

```text
architecture
toolchain_id
config_hash                    = sha256(exact campaign .config)
dtb_hash                       = sha256(exact booted DTB)
kernel_commit
lto_enabled                    = yes | no
kernel_control                 = yes | no
dtb_control                    = yes | no
observer_build_control         = yes | no
```

For a board reused across campaigns:

```text
PRIMARY-A row:
    board_id = X
    campaign_id = PRIMARY-A
    toolchain_id = T_A
    config_hash = C_A
    dtb_hash = D_A
    g_dma=1, g_dma_desc=0

PRIMARY-B row:
    board_id = X
    campaign_id = PRIMARY-B
    toolchain_id = T_B
    config_hash = C_B
    dtb_hash = D_B
    g_dma=1, g_dma_desc=1
```

Equality of toolchain/config/DTB across those rows must never be assumed.

## 3 — DMA TOPOLOGY / COHERENCY RESOLUTION

Topology is resolved from the exact row's DTB/config plus runtime/build artifacts before
full rig qualification, because a bounce path can invalidate the intended canary witness.

```text
dma_path                       = direct | bounce(SWIOTLB) | iommu | unresolved
dma_coherent                   = yes | no | unresolved
cache_maintenance_at_unmap     = yes | no | not-applicable | unresolved
driver_local_bounce            = yes | no | unresolved
```

Interpretation rules:

- `dma_path=bounce(SWIOTLB)` means a late device write may land in the SWIOTLB allocation
  rather than the intended canary. A clean canary is then not admissible negative evidence.
- On a non-coherent platform, cache maintenance at `U` can hide, delay, or create
  CPU-visible transitions. Canary interpretation remains open until classified.
- A DWC2-local bounce changes the object actually mapped and must be carried in mapping
  identity.
- `dma-ranges`, `dma-coherent`, and `iommus` are DT-sensitive; this is why `dtb_hash` is
  part of `TARGET_BUILD_ID`.

A row that cannot make its observer semantics valid for its DMA topology is not accepted
merely because the board/controller supports the required mode.

## 4 — RIG READY

Repairable execution prerequisites are separate from board capability and topology:

```text
host_bus_reset_trigger         = yes | no        # PRIMARY-A

isoc_gadget_function           = <name> | none   # PRIMARY-B
isoc_function_opens_endpoint   = yes | no        # PRIMARY-B
isoc_host_stimulus             = yes | no        # PRIMARY-B
primary_b_chain_start_observable = yes | no      # PRIMARY-B

object_disassembly_available   = yes | no        # PRIMARY-B OBJECT_GATE
```

For PRIMARY-B, `isoc_ep_available=yes` at the board level is insufficient. The rig must
bind a real gadget function that opens an isochronous endpoint and drives the DWC2 chain
to the started state (`target_frame != TARGET_FRAME_INITIAL` / NAK or OUTTKNEPDIS start
path as applicable).

### PRIMARY-B exact OBJECT_GATE binding

The layout-matched x86-64/gcc-13.3/-O2 reproducer establishes only:

```text
silent-skip codegen = PATTERN-PROVEN
```

For each PRIMARY-B target-build row record:

```text
board_id
architecture
toolchain_id
config_hash
dtb_hash
kernel_commit
gadget_c_sha256
lto_enabled                    = yes | no
debug_source_mapping           = yes | no
object_gate_artifact           = gadget.o | vmlinux | final-module
object_gate_artifact_sha256
object_gate_status             = PENDING_OBJECT_GATE | OBJECT-PROVEN | KILLED | INDETERMINATE
```

Artifact selection:

```text
if lto_enabled == no:
    gadget.o is admissible

if lto_enabled == yes:
    pre-link gadget.o is inadmissible
    require final vmlinux or the final linked module containing DWC2
```

Use source-interleaved disassembly (`objdump -dS` or equivalent). Do not require a
literal `call dwc2_hsotg_ep_stop_xfr`: the helper is static and may be inlined.

Pre-registered verdict:

```text
OBJECT-PROVEN
  load hs_ep->req
  -> compare its pointer value with req
  -> conditional branch remains
  -> no read through hs_ep->req before comparison
  -> NULL path skips the stop arm and reaches complete_request/U

KILLED
  read through hs_ep->req before comparison
  OR comparison is folded so the proposed NULL path disappears
  OR stop sequence executes unconditionally on that path
```

A capture with incomplete identity or unrecoverable final control flow is
`INDETERMINATE`, never PASS.

## R2 eligibility predicates

```text
PRIMARY_A_R2_ELIGIBLE =
    supports_g_dma == yes
    && primary_a_address_dma == reachable
    && primary_a_reset_path == reachable
    && exact build + DTB identity recorded
    && DMA topology/coherency resolved with admissible observer semantics
    && host_bus_reset_trigger == yes

PRIMARY_B_R2_ELIGIBLE =
    supports_g_dma == yes
    && supports_g_dma_desc == yes
    && isoc_ep_available == yes
    && primary_b_ddma == reachable
    && exact build + DTB identity recorded
    && DMA topology/coherency resolved with admissible observer semantics
    && isoc_function_opens_endpoint == yes
    && isoc_host_stimulus == yes
    && primary_b_chain_start_observable == yes
    && object_disassembly_available == yes
```

`object_gate_status=PENDING_OBJECT_GATE` may coexist with a feasible PRIMARY-B row, but
the silent-skip execution claim remains pending until the exact target object receives a
terminal verdict.

## Candidate matrix schema

Every enumerated campaign row carries at least:

| Field | Meaning |
|---|---|
| `board_id` | stable physical board identity |
| `campaign_id` | PRIMARY-A or PRIMARY-B |
| `soc` | SoC/controller identity |
| `arch` | target architecture |
| `supports_g_dma` | address DMA capability |
| `supports_g_dma_desc` | descriptor DMA capability |
| `isoc_ep_available` | hardware isochronous endpoint capability |
| `primary_a_reset_path` | host-triggerable reset/disconnect path |
| `primary_b_ddma` | DDMA mode reachable |
| `kernel_control` | exact kernel build/control available |
| `dtb_control` | exact DTB control available |
| `toolchain_id` | compiler/linker tuple bound to row |
| `config_hash` | SHA256 of exact campaign config |
| `dtb_hash` | SHA256 of exact booted DTB |
| `lto_enabled` | chooses admissible OBJECT_GATE artifact |
| `dma_path` | direct / SWIOTLB / IOMMU / unresolved |
| `dma_coherent` | DMA coherency for exact DTB/build |
| `cache_maintenance_at_unmap` | relevant non-coherent behavior |
| `host_bus_reset_trigger` | PRIMARY-A rig predicate |
| `isoc_gadget_function` | PRIMARY-B rig function |
| `isoc_function_opens_endpoint` | PRIMARY-B rig predicate |
| `isoc_host_stimulus` | PRIMARY-B rig predicate |
| `primary_b_chain_start_observable` | PRIMARY-B started-chain evidence ability |
| `object_gate_status` | PRIMARY-B exact-codegen verdict |
| `r2_eligible` | derived campaign-row verdict |
| `effective_net_ip_align` | ranking only |
| `stock_u_ether_canary_shortcut` | ranking only |

## 5 — convenience / witness ranking

Only after a row survives the R2 predicates do we rank convenience:

```text
effective_net_ip_align
net_ip_align_mod4_nonzero      = ((effective_net_ip_align & 3) != 0)
udc_quirk_avoids_skb_reserve   = yes | no
u_ether_reserve_executed       = yes | no
bounce_path_reachable          = <function>: yes | no
stock_u_ether_canary_shortcut  = yes | no
custom_gadget_canary_feasible  = yes | no
```

The stock `u_ether` shortcut requires:

```text
((effective_NET_IP_ALIGN & 3) != 0)
&& udc_quirk_avoids_skb_reserve == no
&& u_ether RX path reachable
```

Critical non-implication:

```text
stock_u_ether_canary_shortcut = no
    !=>
G6 = BLOCKED
```

A new-epoch custom gadget can still own and identify its canary buffer.

Pinned source convenience filter:

| Kernel architecture | Effective source value | Stock `u_ether` offset candidate |
|---|---:|---|
| arm64 | `0` | DEAD |
| x86 | `0` | DEAD |
| arm32 | generic fallback `2`, but earlier override still possible | `PENDING_PREPROCESSOR_CONFIRM` |

The ARM32 row is promoted only from the exact target build/preprocessor artifact.

Standard FunctionFS does not expose an arbitrary unaligned userspace pointer as
`usb_request->buf`; therefore:

```text
FunctionFS -> DWC2 local unaligned bounce = DEAD
```

This does not block FunctionFS as a request/holder mechanism for PRIMARY-A or a custom
G6 witness.

## Canary attribution and R2/R3 implication

For a no-IOMMU target:

```text
commit_content_matches_host_payload = REQUIRED
```

A generic memory modification does not attribute the write to DWC2.

A qualified R3 artifact may discharge R2 by implication:

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

For PRIMARY-B, never derive `same_mapping_identity` from queue order or `compl_desc`
alone. Runtime evidence must bind descriptor slot, request ID, mapping ID, DMA address,
dequeue sequence, and epoch.

## G2.5 exit

Per campaign:

```text
at least one named TARGET_BUILD_ID
&& campaign capability predicate
&& exact build + DTB identity
&& DMA topology/coherency resolved
&& campaign rig ready
=> G2.5 PASS for that campaign
```

If the enumerated set is empty:

```text
G2.5_TARGET_SET = EMPTY
=> reorder to G3 -> G4 -> G6
```

Canary remains primary; IOMMU remains optional.

## Current G2.5 status

```text
PRIMARY-B codegen pattern      PATTERN-PROVEN (x86-64/gcc13.3/-O2 reproducer)
PRIMARY-B target object        PENDING_OBJECT_GATE

mandatory capability columns:
    supports_g_dma
    supports_g_dma_desc
    isoc_ep_available

mandatory build identity:
    toolchain_id
    config_hash
    dtb_hash

PRIMARY-A named target-build   NOT YET FROZEN
PRIMARY-B named target-build   NOT YET FROZEN
DMA topology                   NOT YET FROZEN
G2.5 exit                      NOT REACHED
```