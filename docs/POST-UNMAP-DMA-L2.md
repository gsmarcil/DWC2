# POST-UNMAP-DMA-001 — L2.1–L2.3 source ledger

## Pin and source identities

All source claims in this ledger are bound to Linux commit:

```text
f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
```

Audited file identities:

```text
drivers/usb/dwc2/gadget.c
sha256 baf17cb89e78c8a63f0a9688af7697875018f162923118f72f1092df703f6d8d
lines  5739

drivers/usb/gadget/function/f_fs.c
sha256 f8794cedc4b6d7289ce4711909a6c039283892dc57511b8245c048b93ba6b1e5

drivers/usb/gadget/function/u_ether.c
sha256 b2f84b7b9a97a3dd46b27114d24ab3755af7182999dcf0e37a97d8ec4fba45e4
```

This is an ordering/source-topology ledger. It does **not** prove that DWC2 issues
or commits DMA after unmap, that a request was hardware-active at the reset edge,
or that any security impact exists.

## Frozen K vocabulary

```text
K_sw_ATTEMPTED
    source executes a stop/NAK/disable sequence and waits for the relevant
    completion/status bit before U, but timeout is warning-only and execution
    continues.

K_sw_OBSERVED
    runtime artifact for one execution proves all required waits completed
    without timeout before U.

K_hw
    databook binds the observed terminal bit/state to DMA drain/quiescence.
```

Every wait inside `dwc2_hsotg_ep_stop_xfr()` is fail-open: timeout emits
`dev_warn()` and control continues. Therefore:

```text
L2.4 SOURCE-CLOSED = EMPTY at source-only stage
```

No source partition is created for “successful wait” versus “timeout”; that is a
runtime partition. The observer must record, for every stop attempt, which wait(s)
completed and which timed out.

## L2.1 — unique map and unmap sink

Map:

```text
dwc2_hsotg_ep_queue()
  -> dwc2_hsotg_map_dma()
     -> usb_gadget_map_request()
```

Unmap:

```text
dwc2_hsotg_complete_request()
  -> dwc2_hsotg_unmap_dma()
     -> usb_gadget_unmap_request()
        -> dma_unmap_single() | dma_unmap_sg()
```

Fixed order in `dwc2_hsotg_complete_request()`:

```text
U: unmap
 -> dwc2_hsotg_handle_unaligned_buf_complete()
 -> hs_ep->req = NULL
 -> list_del_init()
 -> unlock
 -> usb_gadget_giveback_request()
```

In DDMA isochronous mode the function then returns directly; it does not rebuild,
retire, clear, or invalidate the descriptor ring.

Consequence for G4: `UNMAP_DONE` has one canonical DWC2 request-cleanup probe.

## L2.2 — source stop candidate

The general teardown stop primitive is:

```text
dwc2_hsotg_ep_stop_xfr()
```

Direction-dependent sequence:

```text
IN:
  SNAK or SGNPINNAK
  wait INEPNAKEFF or GINNAKEFF

OUT:
  SGOUTNAK
  wait GOUTNAKEFF

both:
  set EPDIS | SNAK
  wait EPDISBLD
  clear EPDISBLD
```

All four DMA-mode waits are timeout-bounded and warning-only. Thus source can prove
only `K_sw_ATTEMPTED`, never `K_sw_OBSERVED`.

Runtime records must carry at least:

```text
stop_seq
wait_inepnakeff_timeout
wait_ginnakeff_timeout
wait_goutnakeff_timeout
wait_epdisbld_timeout
unmap_seq
```

## L2.3 — source partition table

| Path | Stop before U | Source classification |
|---|---|---|
| normal completion | no explicit stop; completion semantics only | L2.6 / databook gate |
| `ep_dequeue`, ordinary active request | `ep_stop_xfr()` attempted when request is current | L2.6 |
| `ep_dequeue`, queued request never published | none, `O=NO` | CLOSED as non-exposed mapping |
| `ep_disable`, `EPENA=1` | `ep_stop_xfr()` attempted | L2.6 |
| `ep_disable`, `EPENA=0` | no stop call | L2.5 candidate; prior ownership required |
| `core_init_disconnected`, EP0 | kill precedes core reset/EP disable | L2.5 SURVIVOR |
| `dwc2_hsotg_disconnect` | no stop/disable before kill | **PRIMARY-A** |
| DDMA-isoc `ep_dequeue`, descriptor-published request | no descriptor retirement before U; stop decision passes through null-derived member-address expression | **PRIMARY-B; source-qualified, codegen PATTERN-PROVEN, target object pending** |

## PRIMARY-A — bus-reset / disconnect ordering

Within one `dwc2_hsotg_irq` pass for `USBRST | RESETDET`:

```text
dwc2_hsotg_disconnect()
  -> kill_all_requests(all endpoints)
     -> dwc2_hsotg_complete_request()
        -> U

then, only afterwards:

dwc2_hsotg_core_init_disconnected(true)
  -> ep_disable()
     -> ep_stop_xfr() conditionally
```

Mandatory qualification:

```text
reachability = hsotg->connected == 1
scope        = ordering-only; active hardware ownership remains R1A/G3
```

This branch is frozen for address DMA campaign configuration:

```text
PRIMARY-A
  g_dma      = 1
  g_dma_desc = 0
```

Whether USB reset itself quiesces in-flight DMA remains `K_hw = UNKNOWN`.

## PRIMARY-B — DDMA isochronous dequeue

This is a separate campaign branch. It does not replace PRIMARY-A and inherits no
runtime evidence from it.

Required configuration/reachability:

```text
g_dma_desc = 1
endpoint   = isochronous
chain_started = yes
```

The chain-start condition must be real, not inferred merely from queueing. Source
starts/rebuilds DDMA-isoc through the NAK / OUTTKNEPDIS synchronization handlers;
`ep_queue()` only appends directly to an existing chain once
`target_frame != TARGET_FRAME_INITIAL`.

### A — descriptor remains software-published

Source establishes:

```text
dwc2_gadget_fill_isoc_desc()
  desc->buf = request DMA address
  desc->status = HREADY

dwc2_gadget_start_isoc_ddma()
  writes desc_list_dma -> DIEPDMA/DOEPDMA
  sets EPENA | CNAK
```

Software does not transition that descriptor from `HREADY` to `DMADONE`.
`dwc2_gadget_complete_isoc_request_ddma()` reads descriptor status and only
processes entries already reported `DMADONE` by the controller.

Therefore:

```text
A = SOURCE-PROVEN
software leaves HREADY + ring published + EPENA
```

Whether the controller has fetched, owns, or will fetch the descriptor in a
particular execution remains a `K_hw/runtime` question.

### B — no software retirement/rewrite before or after U in dequeue completion

`ep_dequeue()` flows to `dwc2_hsotg_complete_request()`. Inside completion:

```text
U
-> bounce completion if any
-> hs_ep->req = NULL
-> list_del_init(request)
-> giveback
-> if DDMA && isochronous: return
```

No statement in this path clears the descriptor buffer address, rewrites its
status, advances `next_desc`, advances `compl_desc`, or rebuilds the DDMA ring.
The descriptor therefore retains the DMA address that has just been unmapped from
the request lifecycle.

```text
B = SOURCE-PROVEN
no software descriptor retirement / rewrite on the dequeue -> U path
```

### Enabler — zero-offset embedded request

`struct dwc2_hsotg_req` has `struct usb_request req` as its first member:

```text
offsetof(struct dwc2_hsotg_req, req) == 0
```

DDMA-isoc chain publication does not go through the ordinary
`dwc2_hsotg_start_req()` assignment of `hs_ep->req = hs_req`.

The stop condition in `ep_dequeue()` is:

```c
if (req == &hs_ep->req->req)
    dwc2_hsotg_ep_stop_xfr(...);
```

The practical silent-skip lowering has now been characterized on a layout-matched
control build:

```text
architecture  x86-64
compiler      gcc 13.3
optimization  -O2
result        load hs_ep->req value -> compare directly to req -> conditional stop branch
              no read through the loaded pointer before comparison
```

The same lowering was observed with and without `-fdelete-null-pointer-checks`.
The pinned kernel build itself adds `-fno-delete-null-pointer-checks`, but that flag
is not treated as the carrier of the pattern.

Frozen classification:

```text
zero-offset enabler             SOURCE-PROVEN
silent-skip codegen pattern     PATTERN-PROVEN
  scope                         x86-64 / gcc 13.3 / -O2 reproducer
exact named-target object       PENDING_OBJECT_GATE
```

Target closure remains two-sided and pre-registered:

```text
OBJECT-PROVEN
  load hs_ep->req
  -> compare pointer value with req
  -> conditional branch retained
  -> no read through hs_ep->req before comparison
  -> NULL path skips stop and reaches complete_request/U

KILLED
  read through hs_ep->req before comparison
  OR comparison folded to a constant that invalidates the model
  OR stop sequence executes unconditionally on the NULL path
```

For LTO builds, only the final linked `vmlinux` or final module is admissible;
pre-link `gadget.o` is not. Non-LTO may close on `gadget.o`. The target build must
carry debug/source mapping and be inspected with source-interleaved disassembly.

Do not require a literal call to `dwc2_hsotg_ep_stop_xfr()`: it is static and may
be inlined. The adjudicator must recognize the equivalent inlined SNAK/SGOUTNAK,
EPDIS, and wait sequence.

### PRIMARY-B status

```text
DDMA_ISOC_DEQUEUE_PROGRAMMED
mapping                               SOURCE-PROVEN
descriptor HREADY publication         SOURCE-PROVEN
ring publication + EPENA              SOURCE-PROVEN
A: software leaves descriptor live    SOURCE-PROVEN
B: no retirement/rewrite around U     SOURCE-PROVEN
offsetof(req) == 0                     SOURCE-PROVEN
silent skip-stop pattern               PATTERN-PROVEN (x86-64/gcc13.3/-O2)
exact target silent skip-stop          PENDING_OBJECT_GATE
hardware ownership/fetchability at U   UNKNOWN / K_hw
post-U DMA                             NOT PROVEN
```

PRIMARY-B is therefore source-qualified with a pattern-level codegen result, but
the exact silent-skip execution claim must not be promoted until the named-target
object gate reaches `OBJECT-PROVEN` or `KILLED`.

## Independent identity-risk entry — DDMA descriptor/queue drift

This is not folded into the post-unmap claim.

Normal DDMA-isoc completion associates the current descriptor index
`hs_ep->compl_desc` with `get_ep_head(hs_ep)`. A dequeue removes one request from
the software queue via `list_del_init()`, while the dequeue path does not adjust
`compl_desc` and does not retire the corresponding descriptor.

For a dequeue that is not naturally aligned with the next completion index, the
software queue head and descriptor index can diverge. A later hardware `DMADONE`
may therefore be interpreted against a different request than the request whose DMA
address the descriptor originally carried.

Status:

```text
DDMA_DESC_QUEUE_IDENTITY_DRIFT
source asymmetry        SOURCE-PROVEN
concrete misassociation REACHABILITY NOT YET PROVEN
security impact         UNKNOWN
```

G4 must not infer `same_mapping_identity` from queue position or `compl_desc`
alone. Any DDMA-isoc runtime witness must bind descriptor identity, request
identity, mapping identity, and dequeue sequence explicitly.

## FunctionFS unaligned-bounce hypothesis — DEAD

Standard FunctionFS does not expose an unaligned userspace address as
`usb_request->buf`: non-SG I/O uses a kernel `kmalloc` buffer; SG I/O uses
`req->buf = NULL`. Therefore:

```text
FunctionFS -> DWC2 local unaligned bounce = DEAD
```

## u_ether convenience candidate — G2.5 only

The exact predicate carried by G2.5 is:

```text
effective_net_ip_align
net_ip_align_mod4_nonzero      = ((effective_net_ip_align & 3) != 0)
udc_quirk_avoids_skb_reserve   = yes | no
u_ether_reserve_executed       = yes | no
stock_u_ether_canary_shortcut  = yes | no
custom_gadget_canary_feasible  = yes | no
```

Failure of the stock u_ether shortcut does not block G6; a new-epoch custom gadget
canary remains allowed.

## Current closure state

```text
POST-UNMAP-DMA-001

L2.1 map/unmap topology       SOURCE-PROVEN
L2.2 K_sw candidate           SOURCE-PROVEN as ATTEMPTED only
L2.4 source-closed paths      EMPTY

L2.5 PRIMARY-A                reset/disconnect, g_dma=1 g_dma_desc=0
L2.5 PRIMARY-B                DDMA-isoc dequeue, g_dma_desc=1/isoc
  A                           SOURCE-PROVEN
  B                           SOURCE-PROVEN
  silent-skip pattern         PATTERN-PROVEN (x86-64/gcc13.3/-O2)
  target object               PENDING_OBJECT_GATE
  K_hw                        OPEN

identity-drift side entry     SOURCE ASYMMETRY PROVEN; reachability open
R1A runtime                   NOT EXECUTED
D_issue                       UNKNOWN
D_commit                      UNKNOWN
security impact               UNKNOWN
```