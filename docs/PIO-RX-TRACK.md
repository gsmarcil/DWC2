# Separate track: DWC2 PIO RX logical/physical extent mismatch

This is a separate source-level finding and must not be merged into the R1 request-unmap claim.

## Frozen claim

In the DWC2 gadget PIO receive path, the FIFO is read in 32-bit words while request accounting uses the raw packet byte count. For a non-word-aligned packet size, the physical write extent can therefore exceed the logical extent by 1–3 bytes.

The source contains an explicit comment acknowledging that this operation may overwrite the end of the buffer by up to three bytes.

## Evidence state

```text
physical-vs-logical extent mismatch      SOURCE-PROVEN
request-boundary crossing                SOURCE-PROVEN
adjacent allocation corruption           NOT PROVEN
cross-object effect                       NOT PROVEN
information disclosure                    NOT PROVEN
security boundary impact                  UNKNOWN
runtime hardware reproduction             PENDING
```

## Reporting boundary

Do not describe this track as proven kernel memory corruption unless a runtime artifact establishes an actual memory-side effect beyond the intended object/allocation boundary.

## Still live in mainline

Re-checked at `08df884136f1c1197bab2a27814404fd329d9aac` in
`drivers/usb/dwc2/gadget.c`, `dwc2_hsotg_rx_data()`:

```c
if (to_read > max_req) {
        /* currently we don't deal this */
        WARN_ON_ONCE(1);
}

hs_ep->total_data += to_read;
hs_req->req.actual += to_read;
to_read = DIV_ROUND_UP(to_read, 4);

/*
 * note, we might over-write the buffer end by 3 bytes depending on
 * alignment of the data.
 */
dwc2_readl_rep(hsotg, EPFIFO(ep_idx), hs_req->req.buf + read_ptr, to_read);
```

`to_read` is never clamped to `max_req`. The oversize case warns once and then
falls through to the copy, and the word-rounding over-write is acknowledged in
the driver's own comment. Both halves of the frozen claim above are therefore
present in current mainline, not only at the pinned ref.

A fix was reported to this repository under the subject "usb: dwc2: truncate
PIO RX FIFO reads to the request's remaining space". No commit with that
subject exists in mainline, which is consistent with the defect still being
present as shown. Treat that fix as reported-but-unmerged until a merged commit
is produced.

The reporting boundary above is unchanged by this. Source presence is not a
runtime memory-side effect.
