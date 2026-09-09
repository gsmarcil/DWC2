# POST-UNMAP-DMA-001 — G2.5 target feasibility enumeration

## Gate purpose

G2.5 answers two distinct questions without conflating them:

1. Is a named DWC2 target fundamentally capable of exercising the R2 path?
2. Is the current rig/tooling ready to observe that target with admissible identity?

A board must not be rejected merely because a convenience witness (`u_ether`) or a
particular observer has not yet been built.

The qualification order is frozen as follows.

```text
A. BOARD_CAPABLE
B. RIG_BASE_READY
C. DMA_TOPOLOGY_RESOLVED
---------------------------------
   R2-ELIGIBLE NAMED TARGET
D. CONVENIENCE / RANKING ONLY
```

`NET_IP_ALIGN` and the stock `u_ether` bounce path belong to D. They are never an
initial board-admission predicate.

## A — BOARD_CAPABLE

Immutable/controller capability fields:

```text
board_name
soc
udc_name
udc_driver                     = dwc2
peripheral_gadget_mode         = reachable | unreachable
address_dma_mode               = reachable | unreachable
expected_dwc2_params           = g_dma=1, g_dma_desc=0
reset_disconnect_path          = reachable | unreachable
```

For this track the preferred mode is DWC2 address DMA, not DDMA. At the pinned
Linux source, `g_dma` and `g_dma_desc` are DWC2 core parameters; the intended
address-DMA configuration is `g_dma=1` with `g_dma_desc=0`.

A board that cannot expose this mode is not accepted merely because it offers a
convenient canary allocation.

## B — RIG_BASE_READY

Operator/rig prerequisites are recorded separately from board capability:

```text
kernel_control                 = yes | no
dtb_control                    = yes | no
host_bus_reset_trigger         = yes | no
observer_build_control         = yes | no
```

These are repairable rig properties and therefore do not redefine
`BOARD_CAPABLE`. They do, however, have to be satisfied before the named target is
usable for the planned R2 campaign.

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
  allocation rather than the intended canary object. A clean canary in that case
  is not evidence of no late DMA.
- On a non-coherent platform, cache maintenance at `U` can hide, delay, or create
  CPU-visible state transitions. Canary interpretation is not admissible until
  that behavior is classified.
- A DWC2-local bounce buffer likewise changes the object actually mapped to the
  controller and must be carried in mapping identity.

Only after A, B, and C are satisfied is the board promoted to:

```text
R2_ELIGIBLE_TARGET = yes
```

## D — convenience / witness ranking

Convenience fields are evaluated only among already eligible targets:

```text
effective_net_ip_align
net_ip_align_mod4_nonzero      = ((effective_net_ip_align & 3) != 0)
udc_quirk_avoids_skb_reserve   = yes | no
u_ether_reserve_executed       = yes | no
bounce_path_reachable          = <function>: yes | no
stock_u_ether_canary_shortcut  = yes | no
custom_gadget_canary_feasible  = yes | no
```

`net_ip_align_nonzero` is deliberately not used: DWC2's local unaligned-buffer
predicate is `(long)req_buf & 3`, so a non-zero alignment value that is still a
multiple of four does not activate the bounce path.

For the stock `u_ether` RX shortcut, source reachability requires:

```text
((effective_NET_IP_ALIGN & 3) != 0)
&& udc_quirk_avoids_skb_reserve == no
&& u_ether RX path reachable
```

`u_ether` conditionally calls `skb_reserve(skb, NET_IP_ALIGN)` only when
`dev->no_skb_reserve` is false. That value originates from the gadget/UDC
`quirk_avoids_skb_reserve` policy. The pinned DWC2 source audit found no DWC2
assignment of `quirk_avoids_skb_reserve` (nor `quirk_ep_out_aligned_size`) in
`gadget.c`, `core.h`, or `params.c`; nevertheless the field remains explicit in
the matrix because it is a UDC property, not an architecture property.

### Critical non-implication

```text
stock_u_ether_canary_shortcut = no
    !=>
G6 = BLOCKED
```

The stock `u_ether` path is only a convenience witness. G6 can still use a
new-epoch custom gadget function that owns and identities its own DMA buffer,
subject to the frozen epoch/provenance rules.

## `u_ether` architecture filter

Pinned Linux source:

```text
commit: f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
u_ether.c sha256: b2f84b7b9a97a3dd46b27114d24ab3755af7182999dcf0e37a97d8ec4fba45e4
```

`u_ether` RX allocates an skb with extra `NET_IP_ALIGN`, conditionally executes
`skb_reserve(skb, NET_IP_ALIGN)`, then assigns `req->buf = skb->data` before
`usb_ep_queue()`.

The generic networking fallback is:

```c
#ifndef NET_IP_ALIGN
#define NET_IP_ALIGN 2
#endif
```

Verified architecture values at the same pin:

| Kernel architecture | Effective value known from source | Stock u_ether offset candidate |
|---|---:|---|
| arm64 | `0` | DEAD |
| x86 | `0` | DEAD |
| arm32 | no definition in `arch/arm/include/asm/processor.h`; generic fallback is `2` | `PENDING_PREPROCESSOR_CONFIRM` |

The arm32 row is deliberately not promoted to `yes`. The fallback is guarded by
`#ifndef`, so an earlier target/build header can override it. The exact target
kernel configuration must be preprocessed/compiled and the effective value stored
as a build artifact.

This table ranks already-qualified boards; it does not qualify them.

## FunctionFS filter

Standard FunctionFS is not a route to DWC2's local unaligned-buffer bounce:
non-SG I/O gives DWC2 a kernel `kmalloc` buffer and SG I/O sets `req->buf=NULL`.
Therefore:

```text
FunctionFS -> DWC2 unaligned bounce = DEAD
```

This does not affect FunctionFS as a holder/request-generation mechanism for the
primary reset/disconnect ordering witness; it only kills the proposed unaligned
buffer witness.

## Canary feasibility

`canary_feasible` is derived only after the topology fields are known. It is not a
raw property of the board.

```text
canary_feasible =
    R2_ELIGIBLE_TARGET
    && mapping identity can be preserved/proven
    && observer semantics are valid for dma_path/coherency
    && (stock_u_ether_canary_shortcut || custom_gadget_canary_feasible)
```

For a no-IOMMU board, attribution additionally requires:

```text
commit_content_matches_host_payload = REQUIRED
```

A generic memory change is not sufficient to attribute `D_commit` to DWC2.

## R2/R3 implication rule

R2 can also be discharged by a qualified R3 artifact:

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

## G2.5 exit

Normal exit:

```text
at least one named target
&& BOARD_CAPABLE
&& RIG_BASE_READY
&& DMA_TOPOLOGY_RESOLVED
=> G2.5 PASS
```

If the enumerated target set is empty after those predicates:

```text
G2.5_TARGET_SET = EMPTY
=> reorder to G3 -> G4 -> G6
```

Canary remains the primary observation strategy and IOMMU remains optional. A
missing stock `u_ether` shortcut is not an empty-target condition and does not
block G6.

## Current G2.5 status

```text
source/architecture convenience filter:
    arm64 stock u_ether bounce   DEAD
    x86 stock u_ether bounce     DEAD
    arm32 stock u_ether bounce   CANDIDATE / PREPROCESSOR CONFIRM REQUIRED

DWC2 quirk audit:
    quirk_avoids_skb_reserve assignment in audited DWC2 files  NOT OBSERVED

named BOARD_CAPABLE target        NOT YET FROZEN
RIG_BASE_READY target             NOT YET FROZEN
DMA_TOPOLOGY_RESOLVED target      NOT YET FROZEN
R2_ELIGIBLE_TARGET                NOT YET FROZEN
G2.5 exit                         NOT REACHED
```