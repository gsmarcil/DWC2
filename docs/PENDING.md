# Pending work

## P-1 — Import the canonical device harness

Before the next expanded evidence epoch is frozen, import the original tested gadget-side source:

```text
r1a-device/r1a_ffs_out_v2.c
```

The source must be imported byte-for-byte from the tested package/artifact, not recreated from prose. Its SHA256 must then become part of the active epoch contract under `device_harness`.

Reason: the holder witness is load-bearing for a negative R1A campaign. An epoch that names `device_harness` without preserving the source that produced the holder log is not self-contained.

This is a repository/provenance blocker, not a runtime finding.

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