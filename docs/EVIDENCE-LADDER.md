# Evidence ladder

## R1A — trigger / reachability

**Proves**

- the host-controlled trigger reached the intended DWC2 teardown path;
- a natural stop-timeout artifact satisfies the frozen R1 predicate for the linked attempt.

**Does not prove**

- real unmap in that attempt;
- post-unmap DMA;
- memory corruption.

## R2 — DMA lifetime violation / `D_issue`

`R2_PROVEN` requires all of:

```text
R1A_PROVEN
same_epoch
same_request_identity
same_mapping_identity
UNMAP_DONE(mapping, iova, len, device)
post_unmap_access(device, retired_iova)
access occurs after UNMAP_DONE
access range intersects retired mapping range
NO_REMAP for that retired range in the attribution window
```

If the fault source does not carry a request identifier, correlation is rebuilt through:

```text
request_seq
  → mapping identity / retired IOVA range
  → UNMAP_DONE
  → same device/SID accesses that exact retired range
```

A temporal-only `UNMAP_DONE` + unrelated IOMMU fault is insufficient.

## R3 — `D_commit`

Requires a completed memory-side effect after lifetime ended, such as a canary/marker or equivalent observation that distinguishes a committed DMA effect from a blocked transaction.

An IOMMU fault by itself cannot prove `D_commit`.

## Impact

Requires an effect on memory/object with changed ownership plus controllability and/or confidentiality/integrity boundary crossing.

The report should remain modular:

```text
Claim 1 — R1A: trigger reachability
Claim 2 — R2: same-mapping post-unmap DMA attempt
Claim 3 — R3: completed post-lifetime memory effect
Claim 4 — Impact: controllability + security-boundary crossing
```

A failure to prove Claim 3 must not erase a valid Claim 2.
