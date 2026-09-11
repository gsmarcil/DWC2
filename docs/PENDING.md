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
