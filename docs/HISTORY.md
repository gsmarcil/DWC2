# Research history — valid state only

This is a compact history of conclusions that survived later audits. It deliberately omits claims that were disproven or depended on stale tooling.

## 2026-07-31 → 2026-08-11 — DWC2 RX path audit

The first DWC2 track focused on `dwc2_hsotg_rx_data()` in PIO gadget receive mode at the pinned upstream tree.

Valid conclusion that remains:

- the function consumes FIFO data in 32-bit words while request accounting advances by the raw packet byte count;
- therefore the physical write extent can exceed the logical packet/request extent by up to three bytes when the packet size is not word aligned;
- the in-tree source itself acknowledges that the copy may overwrite the buffer end by up to three bytes;
- request-boundary crossing is source-proven;
- corruption of an adjacent allocation, disclosure, or security-boundary impact is **not proven**.

This track is retained separately in `PIO-RX-TRACK.md`. It is not used as evidence for the request-unmap lifetime hypothesis.

## 2026-08-18 onward — request-unmap lifetime hypothesis

The second track narrowed to the lifetime of an active DMA request during endpoint teardown.

Pinned source:

```text
torvalds/linux
f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
primary file: drivers/usb/dwc2/gadget.c
```

The source audit established the following surviving chain:

```text
active request
→ DMA address programmed to controller
→ endpoint-stop waits for quiescence
→ timeout paths warn and continue
→ request completion/kill path
→ DMA unmap
→ giveback
```

The critical epistemic boundary was frozen immediately afterward:

```text
source proves timeout→software teardown can continue
source does NOT prove hardware remained active
source does NOT prove post-unmap DMA
```

That distinction is still the basis of the current R1/R2/R3 ladder.

## Host-trigger work

The normal Linux convenience configuration path was rejected for R1A overlap testing because it locally tears down URBs before the raw control reaches the gadget. The surviving host trigger therefore uses usbfs raw control submission.

A second host-side issue was identified during re-arm design: a raw configuration cycle bypasses normal usbcore host endpoint reset bookkeeping, while DWC2 resets a non-control endpoint to DATA0. The accepted re-arm design therefore uses a two-arm preflight around `USBDEVFS_RESETEP` and measures whether endpoint reset is required on the actual HCD instead of assuming it.

## Observer/tooling evolution

The observer/tooling went through several revisions. Only the currently frozen state matters for evidence:

- observer package: r3;
- ABI: v9, header 112, record 80;
- P3 remains `NOT_BUILT` and is not a prerequisite for R1A under the frozen predicate;
- timeout records and aggregate counters are kept distinct;
- negative evidence is fail-closed and configuration scoped;
- `R1_DISPROVEN` is not an allowed conclusion from absence.

Several audits found provenance and denominator failures in earlier tooling. The surviving methodological fixes are:

1. host attempts and kernel stop opportunities are separate denominators;
2. sensitivity traffic must not inflate the campaign denominator;
3. setup-count deltas and measured `k` have different purposes and are both required where applicable;
4. campaign timeout records must be sliced to the campaign window;
5. usbmon and gadget-holder evidence are independent witnesses and must be bound to their source artifacts;
6. load-bearing tools are epoch-pinned;
7. the gate validates the manifest directly instead of trusting a hand-produced bridge JSON;
8. artifact hashes are computed from the files that actually execute;
9. negative evidence never carries across an epoch change.

## 2026-09-08 — current freeze

The repository currently freezes the independently audited pre-runtime v4.2 provenance/tooling baseline available to this workspace.

Current state:

```text
source teardown ordering     SOURCE-PROVEN
pre-runtime tooling          VERIFIED BASELINE
R1A on real DWC2             NOT EXECUTED
real unmap in linked run     NOT PROVEN
D_issue                      UNKNOWN
D_commit                     UNKNOWN
security impact              UNKNOWN
severity                     UNRESOLVED
```

A separately developed, more expanded predicate matrix was discussed later in development. Because its complete archive is not present in this repository snapshot, it is not promoted here until imported and reverified.
