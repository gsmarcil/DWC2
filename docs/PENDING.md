# Pending work

## P-1 — Compatible holder-event producer — CLOSED (pre-runtime)

The canonical holder-witness producer is imported and admitted by the executable
gate. It lives at:

```text
r1a-device/r1a_ffs_out_v2.c
```

It emits the JSONL event contract consumed by the frozen `holder_merge.py`, and
`holder_roundtrip.py` builds it with warnings as errors and feeds its real
output through the repository guard, the frozen merger, and the frozen manifest
validator. See `HOLDER-PRODUCER-CONTRACT.md` for the consumer-to-producer
matrix.

The exact pre-holder source is preserved separately as a permanent negative
control at:

```text
r1a-device/legacy/r1a_ffs_out_v2.c.pre-holder
SHA256 83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d6116958f126118e
```

That legacy file is structurally incompatible with the active `holder_merger`:
it has no `--event-log` and emits none of the required event sentinel, phase,
`pending_reads`, `session_id`, `boot_id`, or `device_seq` fields. It must never
be pinned as `device_harness`, and the canonical path must never be overwritten
with it.

Earlier revisions of this section printed the legacy digest directly beneath the
canonical path, which read as an instruction to replace the admitted producer
with the negative control. `verify_status_sync.py` now fails closed on any
document that cites a producer digest without naming the file that actually
hashes to it.

Closed at the pre-runtime layer only. This proves format, namespace, identity
binding, counting rule, and fail-closed control compatibility. It proves nothing
about real DWC2 holder depth. Binding an expanded evidence epoch to the exact
built harness, image, and observer patch remains open and is covered by P0.

## P0 — Real hardware qualification

Required target properties:

```text
real DWC2 gadget UDC
custom observer kernel booted
g_dma=1
g_dma_desc=0
observer ABI=9
snapshot_atomic=1
lost=0
separate USB host
raw EP0 trigger while Bulk OUT remains outstanding
usbmon + device holder evidence
```

The existing x86/xHCI development hosts are useful for tooling but do **not** count as DWC2 timing evidence.

## P1 — R1A runtime

Goal: determine whether a valid host-controlled teardown produces a natural DWC2 stop timeout while the same request is active.

Success must be tied to one valid attempt, not merely to a batch-level counter.

If no timeout is observed, only a configuration-scoped negative result is permitted after all sensitivity/denominator/witness gates pass.

## P2 — Real unmap observation

R1A does not contain an explicit runtime unmap observer. To claim the mapping lifetime ended in the tested attempt, add/enable a runtime `UNMAP_DONE` artifact tied to the same request/mapping.

## P3 — R2 / post-unmap DMA attempt

Need an artifact chain proving:

```text
same epoch
same request/mapping identity
UNMAP_DONE(iova,len,device)
NO_REMAP(retired_range)
post-unmap transaction/fault to retired range
same controller/device/SID
```

This establishes `D_issue`, not `D_commit`.

## P4 — R3 / completed memory effect

Need a memory-side observation showing the controller actually completed a read/write after the software lifetime ended.

Candidate evidence must distinguish attempted DMA from completed DMA.

## P5 — Security impact

Only after R3, evaluate:

- whether memory ownership changed;
- destination/content controllability;
- confidentiality/integrity effect;
- process/kernel/tenant/privilege boundary crossing;
- attacker position, privileges, interaction and deployment prerequisites.

Do not assign High/Critical solely from R1A or an IOMMU fault.

## Test-condition note: IOMMU mode

Any DWC2 runtime test must record the IOMMU mode in effect.

Under strict IOMMU/SMMU mode an unmap invalidates the IOVA synchronously, which
is what would let an in-flight write fault visibly. Under non-strict mode the
invalidation is deferred and the same race need not surface as a fault at all.

Therefore: absence of an IOMMU fault under non-strict mode is **not** evidence
of safety. It is an untested condition. A test plan must either pin strict mode
or state explicitly that the race window was not probed.

This matters concretely for the planned target. Pi Zero 2W has no IOMMU on the
USB path, so the fault-based witness that would make `D_issue` cheap to observe
is unavailable there. That is a property of the target, not of the hypothesis,
and it is why `P3` requires an independent artifact chain rather than a fault
log.

## P6 (proposed): static-analysis pattern for map/unmap asymmetry

No existing Coccinelle or Smatch pattern was found that flags a `dma_unmap`
reached without a preceding quiescence check on the same path.

A naive SmPL rule of the form:

```text
dma_map...(...);
... when != dma_unmap...(...)
giveback(...);
```

would not capture the interesting cases, because the unmap *is* called. The
interesting pattern is path-sensitive: an unmap reached after a timeout warning
that arguably should have gated it. That likely needs a dedicated rule or a
manual per-driver audit.

Listed as proposed future work, not as a gap in current evidence.

## Negative evidence: no mainline commit addresses DWC2 stop-before-unmap

Scope of the search, stated so the claim can be judged and repeated:

```text
searched      full torvalds/linux history, commit SUBJECTS, via git log --grep
at            08df884136f1c1197bab2a27814404fd329d9aac
not searched  LKML / lore.kernel.org — unreachable from the verifying
              environment (egress blocked). The negative claim below covers
              merged mainline only.
```

No mainline commit was found that addresses a quiescence check before request
unmap on a DWC2 teardown path. Every DWC2 commit touching unmap falls into one
of four categories, none of which is this question:

```text
75a41ce46bae  2021-05-06  unmap direction on Control OUT status phase
44583fecfd85  2015-09-29  ordering of unmap vs unaligned-buffer completion
5dce95554a18  2014-09-16  host-side URB bounce-buffer unmapping (not gadget)
(reported)    2026-08-26  PIO RX out-of-bounds write — different failure mode
```

The fourth is listed because a reviewer will find it; it is a host-path change
using `usb_hcd_unmap_urb_for_dma()`, not a gadget teardown change.

The only mainline commit that explicitly ties an incomplete stop to unmap and
to resulting faults is `2b2da6574e77`, and it is DWC3-only. It does not mention
DWC2.

What this does and does not establish:

```text
establishes   the question this repository asks has not been answered for
              DWC2 in merged mainline
does NOT      establish that the answer is "safe", or that no one has
              encountered it outside mainline
```

Absence of a fix is not evidence of absence of a defect, and it is equally not
evidence of one. It is recorded so the novelty of the question is documented
rather than assumed, and so a reviewer can repeat the search.

## External corroboration: Fuchsia DWC2 quarantine workaround

```text
commit        4caf5d06d7f8ac53c7e044b605a36c26d024a9ce
title         [usb][dwc2] Deliberately leak pinned endpoint memory.
author        johngro
date          2025-10-02 (as reported)
change-id     I3b26c82ebf694aa703b0239944fdf58efd935eeb
reviewed-on   https://fuchsia-review.googlesource.com/c/fuchsia/+/1382006

status        MIRROR_VERIFIED / ORIGINAL_PENDING
```

### What was actually fetched

The commit was read at a **third-party** GitHub mirror,
`github.com/misttech/fuchsia`, not at `fuchsia.googlesource.com` and not at the
Gerrit review. Both of those are blocked by this environment's egress proxy.

That distinction is kept deliberately. The artifact in hand is a mirror of the
commit, so the entry claims exactly that and no more.

Two things raise confidence without closing the gap: the mirror's diff touches
the real driver files (`src/devices/usb/drivers/dwc2/dwc2.cc`, `dwc2.h`,
`usb_dwc_regs.h`, `dwc2-test.cc`), and the message carries an internally
consistent Gerrit `Change-Id` and `Reviewed-on` pointing at review 1382006.
Neither substitutes for reading the original.

### What the commit says

Quoted from the mirrored message:

```text
"If the channel connection to this server is closed at any point in time, the
 library (by default) will Unpin the memory. This is not safe, because no
 attempt is made to stop the hardware which may be using this memory."

"The proper thing to do would be to make certain that the DMA is 100% for sure
 stopped before unpinning the memory."
```

Stopping individual endpoints in DWC2 is described there as "only
_reluctantly_ supported". The chosen remedy is to leak the pinned memory to a
**quarantine** on endpoint channel close rather than attempt to recover it.

### What this corroborates, and what it does not

```text
corroborates   an engineer working on DWC2 independently identified the same
               invariant: the lifetime of memory the hardware may still be
               using must not be ended before DMA is proven stopped.

corroborates   that stopping an individual DWC2 endpoint is involved enough
               that another implementation preferred holding memory in
               quarantine over reclaiming it before quiescence was proven.

does NOT       establish that Linux DWC2 carries the defect under study.

reason         different driver, different codebase, different teardown path,
               and Fuchsia pin/unpin is not the semantic equivalent of the
               Linux dma_map/dma_unmap path.

therefore      the reference strengthens the safety invariant only.
               It establishes neither reachability, nor ordering, nor
               post-unmap DMA in Linux.

Linux K_hw     UNDETERMINED
```

Note on the `ordering` line: DWC2's source-level teardown ordering is
established independently in this repository and is not in question. What this
reference does not supply is any Linux ordering evidence of its own. It is
corroboration of the premise, not of the conclusion, and the Linux runtime
question is untouched by it.

### To close the remaining gap

Read the commit at `fuchsia.googlesource.com` or at Gerrit review 1382006 from
an unblocked host and upgrade the status line to `ORIGINAL_SOURCE_VERIFIED`. A
third-party mirror is the weakest acceptable provenance for a quotation this
load-bearing.
