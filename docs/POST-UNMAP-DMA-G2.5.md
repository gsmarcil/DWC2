# POST-UNMAP-DMA-001 — G2.5 target feasibility enumeration

## Gate purpose

G2.5 separates immutable board/controller capability from rig/tool readiness.
A board is not rejected merely because an observer has not yet been built.

```text
BOARD_CAPABLE
    genuine DWC2 UDC
    peripheral/gadget mode reachable
    DMA mode under study reachable
    target reset/disconnect teardown reachable

RIG_READY
    observer can bind to the same runtime epoch
    mapping identity can be preserved/proven
    required canary or IOMMU observation path is available
```

Exit requires at least one **named board** satisfying the full R2 predicate, or a
documented empty target set followed by the reordered path `G3 -> G4 -> G6`.
Canary remains primary; IOMMU remains optional.

## Canary preconditions

These fields precede `canary_feasible` logically:

```text
dma_path                    direct | bounce(SWIOTLB) | iommu
dma_coherent                yes | no
cache_maintenance_at_unmap  yes | no
driver_local_bounce         yes | no
net_ip_align_nonzero        yes | no
bounce_path_reachable       <function>: yes | no
canary_feasible             yes | no
```

For a no-IOMMU board, attribution additionally requires:

```text
commit_content_matches_host_payload = REQUIRED
```

A generic memory change is not sufficient to attribute `D_commit` to DWC2.

## `u_ether` architecture filter

Pinned Linux source:

```text
commit: f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
u_ether.c sha256: b2f84b7b9a97a3dd46b27114d24ab3755af7182999dcf0e37a97d8ec4fba45e4
```

`u_ether` RX allocates an skb with extra `NET_IP_ALIGN`, conditionally executes
`skb_reserve(skb, NET_IP_ALIGN)`, then assigns `req->buf = skb->data` before
`usb_ep_queue()`.

The generic networking definition is:

```c
#ifndef NET_IP_ALIGN
#define NET_IP_ALIGN 2
#endif
```

Architecture overrides at the same kernel pin currently establish:

| Kernel architecture | `NET_IP_ALIGN` | u_ether RX 2-byte-offset candidate |
|---|---:|---|
| arm64 | 0 | DEAD |
| x86 | 0 | DEAD |
| arm32 | no override found in `arch/arm/include/asm/processor.h`; generic fallback is 2 | `PENDING_PREPROCESSOR_CONFIRM` |

The arm32 row is deliberately not promoted to `yes` until the exact target kernel
configuration is preprocessed/compiled and `NET_IP_ALIGN` is recorded as a build
artifact. Absence from one architecture header is not used as final proof that no
other target-specific override exists.

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

## Current G2.5 status

```text
architecture filter:
    arm64 u_ether bounce   DEAD
    x86 u_ether bounce     DEAD
    arm32 u_ether bounce   CANDIDATE / PREPROCESSOR CONFIRM REQUIRED

named BOARD_CAPABLE target  NOT YET FROZEN
RIG_READY target            NOT YET FROZEN
G2.5 exit                   NOT REACHED
```
