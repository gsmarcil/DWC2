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
