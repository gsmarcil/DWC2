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

## Sibling-driver record added 2026-09-11

External material was checked against primary sources and recorded in
`INJURED-SURFACE-TABLE.md`, each entry labelled by what verified it.

Verified merged in mainline by subject match:

```text
cea2a1257a3b  2026-01-08  chipidea: fix DMA and SG cleanup in _ep_nuke()
0bddda5a1166  2026-06-23  mtu3: unmap request DMA on queue failure
d5e5cd3654d2  2026-07-16  dummy_hcd: prevent fifo_req reuse during giveback
06d9db7273c7  2013-03-15  musb: unmap_dma_buffer only for valid DMA addr
```

`CVE-2026-43250` covers the chipidea commit and is confirmed on NVD and
cve.org at CVSS 7.8. It is the closest external analogue: an exceptional
teardown path returned requests without mirroring the normal path's unmap.

The DWC3 precedent chain was bound to mainline with author dates
(`e4cf6580ac74`, `2b2da6574e77`, then `76bff31c7fba`, `4db0fbb60136`,
`c4e3ef568539`), carrying the scope limit that `e4cf6580ac74` speaks of
DWC_usb3x while DWC2 is DWC_otg.

The Fuchsia quarantine commit `4caf5d06d7f8` is recorded as a lead at
`MIRROR_VERIFIED / ORIGINAL_PENDING`, with its third-party mirror named.

The reported tegra-xudc fix could not be verified: every mailing-list archive is
blocked by the verifying environment. The driver was read directly instead, and
that produced a source classification rather than a lead. `ep_wait_for_inactive`
polls `EP_THREAD_ACTIVE` before retirement, but only on the dequeue path, and
its `-ETIMEDOUT` is discarded by a `void` wrapper without even a warning. The
surveyed sample in Axis 1 therefore grows from four drivers to five, with
tegra-xudc `ATTEMPTED` on dequeue and `ABSENT` elsewhere. The reported runtime
SMMU observation remains unverified and carries no weight.

An independent finding came out of the same checking: `dwc2_hsotg_rx_data()` at
`08df8841` still does not clamp `to_read` to `max_req`, so both halves of the
PIO RX frozen claim are present in current mainline and not only at the pinned
ref.

None of this moves the evidence ladder. It is precedent and context; DWC2
`K_hw` remains `UNDETERMINED`.

## Provenance episode 2026-09-11

A privacy-redacted derivative of the canonical v4.2 bundle was published and
then withdrawn. Every step of it was internally consistent, and the gate
reported green, while `verify_archive_tracking.py` failed on the tree binding.
The gate could not see it because the archive proof ran only when git was
absent. The bytes were restored, and the proof now runs in both modes. The
reasoning is kept in `REPOSITORY-POLICY.md`.
