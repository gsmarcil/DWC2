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
    source executes a documented stop/NAK/disable sequence and waits for the
    relevant completion/status bit before U, but timeout is warning-only and
    execution continues.

K_sw_OBSERVED
    runtime artifact for one execution proves all required waits completed
    without timeout before U.

K_hw
    databook binds the observed terminal bit/state to DMA drain/quiescence.
```

The source cannot promote `K_sw_ATTEMPTED` to `K_sw_OBSERVED` because every wait
inside `dwc2_hsotg_ep_stop_xfr()` is fail-open: timeout emits `dev_warn()` and
control continues. Therefore:

```text
L2.4 SOURCE-CLOSED = EMPTY at source-only stage
```

No source partition is created for “successful wait” versus “timeout”; that is a
runtime partition. The runtime observer must record, for every stop attempt, which
wait(s) completed and which timed out.

The remaining classes are:

```text
L2.5  no K_sw attempt before U                    -> SURVIVOR
L2.6  K_sw_ATTEMPTED before U, K_hw unresolved   -> DATABOOK/RUNTIME GATE
```

Normal `XFERCOMPL`/DDMA `DMADONE` completion is also a databook gate and is kept
separate from teardown stop semantics.

## L2.1 — unique map and unique unmap sink

### Map

The request mapping path is unique in `gadget.c`:

```text
dwc2_hsotg_ep_queue()               : ~1465
  -> dwc2_hsotg_map_dma()            : ~1263
     -> usb_gadget_map_request()      : ~1270
```

The gadget core then performs either `dma_map_single()` or `dma_map_sg()`.

### Unmap

The request unmap sink is also unique:

```text
dwc2_hsotg_complete_request()        : ~2140
  -> dwc2_hsotg_unmap_dma()
     -> usb_gadget_unmap_request()
        -> dma_unmap_single() | dma_unmap_sg()
```

The ordering inside `dwc2_hsotg_complete_request()` is fixed:

```text
U: unmap
 -> dwc2_hsotg_handle_unaligned_buf_complete()
 -> hs_ep->req = NULL
 -> list_del_init()
 -> unlock
 -> usb_gadget_giveback_request()
```

Consequently G4 needs one canonical `UNMAP_DONE` observation point for DWC2 request
cleanup rather than separate per-teardown unmap probes.

## L2.2 — only source stop candidate

The only general teardown stop candidate is:

```text
dwc2_hsotg_ep_stop_xfr()             : ~3917
```

Its sequence is direction-dependent but converges on endpoint disable:

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

Every wait is timeout-bounded and warning-only. No timeout returns an error, retries
the stop, or blocks the subsequent completion/unmap path. Thus the source-level
classification is always `K_sw_ATTEMPTED`, never `K_sw_OBSERVED`.

The runtime observer must therefore record at least:

```text
stop_seq
wait_inepnakeff_timeout
wait_ginnakeff_timeout
wait_goutnakeff_timeout
wait_epdisbld_timeout
unmap_seq
```

Only waits applicable to the endpoint/direction are populated for a given attempt.

## L2.3 — source path partition

| Path | stop before U | Source classification |
|---|---|---|
| normal completion | no explicit stop; completion semantics only | L2.6 / databook gate |
| `ep_dequeue` active request (`~4348`) | `ep_stop_xfr()` attempted when request is current | L2.6 |
| `ep_dequeue` queued request never published to hardware | none, but `O=NO` | CLOSED as non-exposed mapping |
| **DDMA isoc `ep_dequeue`, descriptor-published request** | stop decision depends on `&hs_ep->req->req`; DDMA-isoc publication does not use `dwc2_hsotg_start_req()` | **CANDIDATE — COMPILER/OBJECT GATE** |
| `ep_disable` (`~4272`), `DXEPCTL_EPENA=1` | `ep_stop_xfr()` attempted | L2.6 |
| `ep_disable`, `DXEPCTL_EPENA=0` | no stop call | L2.5 candidate; requires prior-ownership classification |
| `core_init_disconnected()` EP0 kill (`~3394`) | kill precedes core reset/EP disable | L2.5 SURVIVOR |
| `dwc2_hsotg_disconnect()` (`~3315`) | no stop/disable before `kill_all_requests()` | **L2.5 PRIMARY SURVIVOR** |

## L2_PRIMARY — bus-reset / disconnect ordering

The device IRQ holds `hsotg->lock` through the handler pass. Within the
`GINTSTS_USBRST | GINTSTS_RESETDET` branch, source order is:

```text
read GOTGCTL
save hsotg->connected
ack USBRST

dwc2_hsotg_disconnect()               : ~3757
  -> for every IN/OUT endpoint
     kill_all_requests()
       -> dwc2_hsotg_complete_request()
          -> U

clear device address

if (GOTGCTL.BSESVLD && connected)
  dwc2_hsotg_core_init_disconnected(true) : ~3763
    -> ep_disable() for non-EP0 endpoints
       -> ep_stop_xfr() only here
```

Thus on the reset path the request unmap precedes the later endpoint-disable/stop
sequence inside the same interrupt handling flow. By the time `ep_disable()` runs,
the request queues have already been drained by `disconnect()`.

### Mandatory qualification

Promotion to `L2_PRIMARY` carries both constraints below:

```text
reachability:
    hsotg->connected == 1
    otherwise dwc2_hsotg_disconnect() returns immediately

scope:
    proves ordering only
    does NOT prove that any request was hardware-active at the reset edge
    hardware-active ownership remains R1A / G3
```

A host-originated USB bus reset is therefore the primary source survivor because it
reaches a `U-before-stop` ordering without relying on a local teardown API call.
Whether USB reset itself causes the DWC2 core to quiesce DMA is explicitly **not**
a source conclusion here; that remains the `K_hw` / databook gate.

## DDMA isochronous dequeue candidate — COMPILER/OBJECT GATE

This candidate is separate from the address-DMA primary track and is retained
because it may expose a more direct `published descriptor -> U without stop`
ordering.

### Publication path

For DDMA isochronous requests, source order is:

```text
ep_queue
  -> map request
  -> add request to hs_ep->queue
  -> dwc2_gadget_fill_isoc_desc()
       desc->buf = request DMA address
       desc->status = HREADY

first start / chain rebuild:
  dwc2_gadget_start_isoc_ddma()
    -> initialize descriptor ring
    -> fill descriptors for requests in hs_ep->queue
    -> write hs_ep->desc_list_dma to DIEPDMA/DOEPDMA
    -> set EPENA | CNAK
```

`dwc2_gadget_start_isoc_ddma()` does not assign `hs_ep->req`. The assignment
`hs_ep->req = hs_req` belongs to `dwc2_hsotg_start_req()`, which is the ordinary
single-current-request path rather than the DDMA-isoc chain start.

Thus a DDMA-isoc request can be mapped and represented by a descriptor whose DMA
address has been published through the descriptor ring without being represented
by `hs_ep->req` in the same way as the ordinary path.

### Dequeue path

`dwc2_hsotg_ep_dequeue()` first checks only whether the request is on
`hs_ep->queue`, then decides whether to call the stop primitive using:

```c
if (req == &hs_ep->req->req)
    dwc2_hsotg_ep_stop_xfr(...);

/* unconditional after that condition */
dwc2_hsotg_complete_request(...);
```

`complete_request()` then reaches the unique `U` site. In DDMA isochronous mode it
returns after giveback and does not contain a software descriptor-retirement or
ring-rebuild operation before `U`.

Normal DDMA-isoc completion is different: `dwc2_gadget_complete_isoc_request_ddma()`
processes only descriptors whose buffer status has become `DMADONE` and only then
completes/gives back the queue head.

### Why this is not yet an L2.5 survivor

If `hs_ep->req` is NULL, the expression:

```c
&hs_ep->req->req
```

is a null-derived member-address expression in C. `req` is the first member of
`struct dwc2_hsotg_req`, so a particular compiler may reduce the comparison to an
address/NULL comparison without an actual load, but that result must **not** be
assumed source-side because the C expression crosses an undefined-behavior
boundary.

Therefore the next mandatory artifact is the exact target object's generated code
for `dwc2_hsotg_ep_dequeue()` under the campaign compiler/configuration.

```text
OBJECT_GATE success:
    generated code does not dereference NULL to obtain the embedded req address
    and the DDMA-isoc case skips ep_stop_xfr before complete_request/U

OBJECT_GATE failure:
    compiler emits a faulting/load-dependent path or otherwise invalidates the
    proposed skip-stop execution
```

Even after OBJECT_GATE success, descriptor ownership/fetchability at the dequeue
edge remains a runtime/databook question. Source proves descriptor publication and
absence of software descriptor retirement before `U`; it does not prove that the
controller had not already changed `HREADY` to `DMADONE` or otherwise consumed the
descriptor in the particular execution.

Current status:

```text
DDMA_ISOC_DEQUEUE_PROGRAMMED
mapping                         SOURCE-PROVEN
software descriptor publication SOURCE-PROVEN
ring base publication + EPENA    SOURCE-PROVEN
software descriptor retirement before U  NOT OBSERVED IN PATH
skip-stop execution              COMPILER/OBJECT GATE
hardware ownership at U          UNKNOWN
post-U DMA                       NOT PROVEN
```

## FunctionFS unaligned-bounce hypothesis — DEAD

The DWC2-local unaligned-buffer helper cannot be driven merely by choosing an
unaligned userspace address through standard FunctionFS:

```text
f_fs.c: ffs_alloc_buffer()
    non-SG -> kmalloc(data_len, GFP_KERNEL)
    SG     -> req->buf = NULL; req->sg = ...

f_fs.c: ffs_epfile_io()
    req->buf = kernel `data`, not the userspace iterator address
```

The non-SG `kmalloc` object has kernel allocator alignment sufficient for the
DWC2 `(long)req_buf & 3` test; the SG path does not present a non-NULL `req->buf`.
Therefore:

```text
unaligned-bounce via standard FunctionFS = KILLED_BY_SOURCE
```

Do not use this path for the G6 canary.

## u_ether bounce candidate — retained, G2.5 only

`drivers/usb/gadget/function/u_ether.c` contains an architecture- and UDC-dependent
convenience candidate. It is not a board-admission predicate and is not required
for G6.

G2.5 carries the exact derived fields:

```text
effective_net_ip_align
net_ip_align_mod4_nonzero      = ((effective_net_ip_align & 3) != 0)
udc_quirk_avoids_skb_reserve   = yes | no
u_ether_reserve_executed       = yes | no
stock_u_ether_canary_shortcut  = yes | no
custom_gadget_canary_feasible  = yes | no
```

The stock shortcut requires both a modulo-4 unaligned effective offset and the
absence of the UDC's `quirk_avoids_skb_reserve`. Failure of that shortcut does not
block a new-epoch custom gadget canary.

The topology fields that precede canary interpretation remain:

```text
dma_path                    direct | bounce(SWIOTLB) | iommu
dma_coherent                yes | no
cache_maintenance_at_unmap  yes | no | not-applicable
driver_local_bounce         yes | no
```

## Current closure state

```text
POST-UNMAP-DMA-001
L2.1 map/unmap topology       SOURCE-PROVEN
L2.2 K_sw candidate           SOURCE-PROVEN as ATTEMPTED only
L2.4 source-closed paths      EMPTY
L2.5 primary survivor         USB reset -> disconnect -> U-before-stop
L2.DDMA dequeue candidate     COMPILER/OBJECT GATE
L2.6 databook gate            OPEN
R1A active-at-reset           NOT PROVEN / G3
D_issue                       NOT PROVEN
D_commit                      NOT PROVEN
impact                        UNKNOWN
```