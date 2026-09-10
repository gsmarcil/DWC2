# Injured-surface table — `POST-UNMAP-DMA-001`

Source-only. No runtime claim. Answers one reviewer question: **is
stop-before-unmap a DWC2 anomaly or a class-wide pattern?**

## Pin

```text
repository   torvalds/linux
ref          f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
```

| File | SHA256 at ref |
|---|---|
| `drivers/usb/dwc2/gadget.c` | `baf17cb89e78c8a63f0a9688af7697875018f162923118f72f1092df703f6d8d` |
| `drivers/usb/dwc3/gadget.c` | `8b8f9a7e96e1d09e13242f75849cfd997ee8a4ee88243f6d4803627119c2e4e6` |
| `drivers/usb/musb/musb_gadget.c` | `f5e5163d86144b36c541f0e93dbc9764e004230c7d6b610f2dadaa3b2125aaf1` |
| `drivers/usb/chipidea/udc.c` | `f4fca70be8d33e7818553faeeaa67fcec98df5a4f82cac834d8dc1d13066b55d` |
| `drivers/usb/gadget/udc/core.c` | `17d0d78f3de3d3dbf28d7136496a1a92c5e3744791b3221269b58c0aecd91041` |
| `drivers/usb/gadget/function/f_fs.c` | `f8794cedc4b6d7289ce4711909a6c039283892dc57511b8245c048b93ba6b1e5` |
| `drivers/usb/gadget/function/u_ether.c` | `b2f84b7b9a97a3dd46b27114d24ab3755af7182999dcf0e37a97d8ec4fba45e4` |

The function rows below were additionally checked at the same pin in
`f_mass_storage.c`, `u_serial.c`, `f_acm.c`, `f_hid.c`, `f_midi.c`,
`f_uac1.c`, `f_uac2.c`, `u_audio.c`, and `drivers/usb/gadget/u_f.c`.
Their source predicates are recorded below; this table does not silently turn
those source checks into runtime coverage.

---

## Axis 1 — `stop-before-unmap` across UDC drivers

Vocabulary frozen in `L2.2`:

```text
ENFORCED   stop issued AND its completion confirmed before unmap,
           with a control-flow consequence if unconfirmed
ATTEMPTED  stop issued, timeout or failure logged, execution continues to unmap
ABSENT     no stop primitive on the path at all
```

| UDC | Teardown path | Stop primitive | Confirmation | Verdict |
|---|---|---|---|---|
| **dwc3** | `dwc3_gadget_reset_interrupt:4194` → `dwc3_stop_active_transfers:2510` → `dwc3_remove_requests:1031` | `DWC3_DEPCMD_ENDTRANSFER` with `HIPRI_FORCERM`, `__dwc3_stop_active_transfer:1761-1770` | command completion; on timeout sets `DWC3_EP_DELAY_STOP` | **ENFORCED** |
| **chipidea** | `_ep_nuke:908` | `hw_ep_flush:105` | unbounded poll: inner `while (hw_read(ENDPTFLUSH))`, outer `do…while (hw_read(ENDPTSTAT))`, no timeout | **ENFORCED** |
| **musb** | `nuke:159` | `FLUSHFIFO` writes `:177-185` + `c->channel_abort(ep->dma)` `:188` | return value logged only (`musb_dbg:189`), not acted on | **ATTEMPTED** |
| **dwc2** — endpoint stop paths | `ep_disable:4272`, `ep_dequeue:4348` | `dwc2_hsotg_ep_stop_xfr:3917` | four waits, each `dev_warn()` then continue | **ATTEMPTED** |
| **dwc2** — reset/disconnect | `dwc2_hsotg_disconnect:3315` → `kill_all_requests:3286` → `complete_request:2118` → `U:2140` | none | — | **ABSENT** |

### The decisive contrast

`dwc3_remove_requests:1031-1039`:

```c
dwc3_stop_active_transfer(dep, true, false);

/* If endxfer is delayed, avoid unmapping requests */
if (dep->flags & DWC3_EP_DELAY_STOP)
	return;
```

dwc3 **declines to unmap** when the hardware stop was not confirmed. That is
the control-flow consequence the `L2.2` ruling asks for, and it is exactly
what no DWC2 path has.

`hw_ep_flush:109-114` reaches the same outcome differently — it simply does
not return until the controller reports the endpoint idle.

### Reading

Two of four drivers enforce; one attempts; DWC2 attempts on two paths and does
nothing on a third. `stop-before-unmap` is therefore a **normal expectation of
the class, not a luxury** — and the DWC2 reset path is the only surveyed path
in the sample with no stop primitive whatsoever.

This is a source-level ordering comparison. It does **not** establish that any
controller performs DMA after unmap, and it does not import dwc3, musb, or
chipidea into any hypothesis. Different controllers, different descriptor
models; the only thing compared is whether the driver retires a mapping
without confirmed hardware quiescence.

Sample size is four. `ENFORCED` for dwc3 and chipidea is established at this
pin only, on the teardown paths named, and was not audited for every entry
point into those functions.

---

## Axis 2 — which gadget functions reach the affected path

DWC2 has exactly one unmap site (`gadget.c:2140`), and every teardown partition
funnels through `dwc2_hsotg_complete_request`. Mapping is performed by the UDC
layer, not by functions: `usb_gadget_map_request_by_dev` in
`drivers/usb/gadget/udc/core.c`.

Consequence: a gadget function that queues an OUT request with an ordinary
unmapped buffer reaches the same DWC2 request-retirement/unmap site. This is a
**source reachability** statement only.

| Function | OUT transfer type | OUT buffer origin / queue path | Sets its own `req->dma`? | Reaches DWC2 unmap path | Status |
|---|---|---|---|---|---|
| `f_fs` (FunctionFS / adb) | descriptor-defined; frozen R1A campaign uses Bulk OUT | `ffs_alloc_buffer → kmalloc`; `req->buf = data`; function queues the OUT request | no | yes | **VERIFIED** |
| `u_ether` (ECM/RNDIS/NCM RX) | Bulk OUT | `req->buf = skb->data` after `skb_reserve`; RX request queued to OUT endpoint | no | yes | **VERIFIED** |
| `f_mass_storage` | Bulk OUT | `bh->buf = kmalloc(FSG_BUFLEN)`; `bh->outreq->buf = bh->buf`; `start_transfer(... bulk_out, bh->outreq)` reaches `usb_ep_queue()` | no assignment found at pin | yes | **VERIFIED** |
| `u_serial` / CDC ACM data RX | Bulk OUT | `gs_alloc_req()` allocates `req->buf = kmalloc(...)`; `gs_start_rx()` queues the request to `port_usb->out`; `f_acm` descriptors define the data OUT endpoint as bulk | no assignment found at pin | yes | **VERIFIED** |
| `f_hid` with `use_out_ep=1` | Interrupt OUT | `hidg_alloc_ep_req() → alloc_ep_req()`; `alloc_ep_req()` uses `kmalloc`; requests are queued to `hidg->out_ep` | no assignment found at pin | yes, source-level | **VERIFIED** |
| `f_midi` | Bulk OUT | `midi_alloc_ep_req() → alloc_ep_req()`; OUT buffers are allocated then queued to `midi->out_ep` in `f_midi_set_alt()` | no assignment found at pin | yes | **VERIFIED** |
| `f_uac1` / `f_uac2` capture | Isochronous OUT | both call `u_audio_start_capture()`; `u_audio` allocates `prm->rbuf = kcalloc(...)`, sets `req->buf = prm->rbuf + offset`, then queues to the OUT endpoint | no assignment found at pin | yes, source-level | **VERIFIED** |

The previously grouped `f_hid`, `f_midi`, `f_uac*` row is split because the
transfer types are materially different. This matters to evidence promotion:
the current reset observer V4 deliberately admits **non-EP0 Bulk OUT only**.
Therefore source reachability for HID interrupt OUT or UAC isochronous OUT does
not inherit a Bulk-OUT runtime R1A result. Each transfer class would need its
own runtime qualification before it could be described as runtime-affected.

### Note on the bounce sub-path

`dwc2_hsotg_handle_unaligned_buf_start:1283` allocates a driver-owned bounce
buffer when `(long)req_buf & 3`. It is not reachable from `f_fs` (kmalloc is
always ≥ 4-byte aligned) and is reachable from `u_ether` only where
`(NET_IP_ALIGN & 3) != 0` and the UDC does not set
`quirk_avoids_skb_reserve` — dwc2 sets neither that quirk nor
`quirk_ep_out_aligned_size` at this pin. Tracked in G2.5, not here.

---

## Axis 3 — upstream history and stable-tree coverage of the reset/disconnect shape

This axis is source-only. It records both a durable lower bound for the current
shape and checked maintained-LTS points.

### History bound

The reset-to-disconnect link predates the current implementation shape:

```text
6d713c1531638df8d459d248a89948318cbeec4c   2015-01-12
    added s3c_hsotg_disconnect() to the USB reset handler

dccf1bad4be7eaa096c1f3697bd37883f9a08ecb   2018-10-02
    changed disconnect from kill_all_requests() to ep_disable()
    (a stop-before-retire form)

4fe4f9fecc36956fd53c8edf96dd0c691ef98ff9   2018-12-11
    explicitly reverted the disconnect-body change back to
    kill_all_requests(), while keeping endpoint disable in
    core_init_disconnected()
```

The release-boundary check matters: `v4.20` still has the `ep_disable()` form
inside `dwc2_hsotg_disconnect()`, while `v5.0` has the current
`kill_all_requests()` form. Therefore the durable checked lower bound for the
**current no-stop disconnect form** is `v5.0`; do not claim uninterrupted
current-form coverage back to the older 2015 reset-link commit.

### Maintained LTS points

Pinned branch heads checked on 2026-09-10 from the kernel.org stable mirror:

| Stable branch | Checked release | Commit | Durable statement |
|---|---|---|---|
| `linux-6.1.y` | `6.1.187` | `cf82dcca96346600c7068cf3f841335f9fa08f54` | current shape still present **through this checked point at least** |
| `linux-6.6.y` | `6.6.156` | `8b73de7da85fde281a385e0b26eda9bffd3ca477` | current shape still present **through this checked point at least** |
| `linux-6.12.y` | `6.12.108` | `064531c7e30cd67b79c0c694ac97f00c7796f4d6` | current shape still present **through this checked point at least** |

For all three checked heads, the same four load-bearing source facts hold:

```text
1. dwc2_hsotg_complete_request()
   if (using_dma(hsotg))
       dwc2_hsotg_unmap_dma(...)

2. kill_all_requests()
   clears ep->req and drains ep->queue through
   dwc2_hsotg_complete_request(...)

3. dwc2_hsotg_disconnect()
   walks IN/OUT endpoints and calls kill_all_requests(...)
   without first invoking dwc2_hsotg_ep_stop_xfr() or another stop primitive

4. dwc2_hsotg_irq()
   handles USBRST/RESETDET by calling dwc2_hsotg_disconnect()
   before the later OEPINT/IEPINT service block in that IRQ pass
```

Verdict:

```text
v5.0      checked lower bound of current no-stop disconnect form   PRESENT
6.1.187   maintained LTS checked point                              PRESENT
6.6.156   maintained LTS checked point                              PRESENT
6.12.108  maintained LTS checked point                              PRESENT
mainline pin f5a7e2ae...                                             PRESENT
```

`PRESENT` means the source-level ordering relevant to the hypothesis is still
present; it does **not** mean byte-for-byte identity, runtime reachability on a
particular board, post-unmap DMA, or a confirmed memory effect. The dated LTS
heads are reproducibility points, while the lower-bound/history wording remains
useful after those branches advance.

These are upstream trees, not proof that every vendor/distro shipping kernel
preserves the same code unchanged.

---

## Open fields

```text
shipping_kernel_line: owned by the per-platform G2.5 matrix; do not duplicate
                      the same platform set as a fourth axis here
additional UDCs for axis 1: cdns3, renesas_usb3, tegra xudc, bdc
deployment weighting: which verified functions/platforms ship enabled by default
```

The upstream function-source rows above are now source-verified. The next
shipping-kernel work belongs in G2.5 beside each platform's DWC2 peripheral and
DMA-topology facts, via a `shipping_kernel_line` field rather than a separate
platform list in this table.

---

## What this table is for

It converts a single-platform laboratory result, if one is ever obtained, from
"one board did something odd" into "this driver retires DMA mappings without
the confirmation its peers require, on a path multiple gadget functions reach."

It does not raise any claim on the evidence ladder. `R1A`, `R2`, and `R3`
remain exactly where they were.
