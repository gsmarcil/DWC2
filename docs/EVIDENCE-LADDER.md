# Evidence ladder

## PRIMARY-A / R1A — teardown without confirmed quiescence

R1A is deliberately defined in terms of observable controller/software state. It does **not** claim that a hidden hardware-ownership bit exists.

### R1A_PROVEN

For one linked PRIMARY-A attempt, all of the following are required:

```text
same_epoch
same_request_identity
same_mapping_generation
MAP -> PROGRAMMED observed for that request/map
host-controlled PRIMARY-A trigger linked to the attempt
pre-stop snapshot shows the OUT endpoint still enabled
pre-stop DOEPTSIZ shows residual programmed transfer bytes > 0
no same-request XferCompl was observed before U
endpoint-disable acknowledgement was known clear before EPDIS assertion
fresh EPDISBLD was not observed before U and the natural wait timed out
UNMAP_BEGIN -> UNMAP_DONE follows for that same mapping generation
no intervening PROGRAMMED event for that request/map
observer loss == 0
```

This proves the narrower statement:

> Software proceeded to retire/unmap an incompletely transferred, same-generation request without obtaining a fresh positive endpoint-disable acknowledgement from the controller.

It does **not**, by itself, prove literal hardware ownership at U, post-unmap DMA, or a memory-side effect.

### R1A_SUPPORTED_ONLY

The following are supporting signals but are insufficient alone:

- `DXEPCTL_EPENA` still set near U: the bit may be stale.
- no `XferCompl` before U: absence is not a positive ownership signal.
- residual `DOEPTSIZ.XFRSIZ > 0` without a fresh disable-timeout observation.
- a stop timeout without a same-request residual-transfer snapshot.
- any endpoint-disable observation whose `EPDISBLD` bit was already set before the disable request.

### R1A_DEAD

For a linked attempt, R1A is killed by a positive terminal observation before U, including either:

```text
same-request XferCompl observed before U
```

or

```text
EPDISBLD known clear before EPDIS assertion
AND fresh EPDISBLD transition observed after EPDIS assertion
AND before U
AND no intervening re-programming/map generation
```

A dead attempt is not eligible for R2/R3 promotion. Missing data, stale pre-set acknowledgement bits, event loss, identity mismatch, or ambiguous ordering produce `R1A_AMBIGUOUS`, not `R1A_PROVEN` and not `R1A_DEAD`.

### Mapping identity

`dma_addr` is not mapping identity. `same_mapping_generation` means an explicit monotonically increasing generation assigned at each successful map and emitted in every load-bearing event for that request. Address reuse alone never closes identity.

## R2 — DMA lifetime violation / `D_issue`

`R2_PROVEN` requires all of:

```text
R1A_PROVEN
same_epoch
same_request_identity
same_mapping_generation
UNMAP_DONE(mapping, iova, len, device)
post_unmap_access(device, retired_iova)
access occurs after UNMAP_DONE
access range intersects retired mapping range
NO_REMAP for that retired range in the attribution window
```

`NO_REMAP` and `same_mapping_generation` are attribution controls, not vertical steps in the evidence ladder.

If the fault source does not carry a request identifier, correlation is rebuilt through:

```text
request_seq
  -> explicit mapping generation / retired IOVA range
  -> UNMAP_DONE
  -> same device/SID accesses that exact retired range
```

A temporal-only `UNMAP_DONE` plus an unrelated IOMMU fault is insufficient.

## R3 — `D_commit`

R3 requires a completed memory-side effect after lifetime ended and a discriminator that attributes that effect to the post-U device transaction.

For the retained-buffer PRIMARY-A experiment, the positive artifact must include:

```text
R1A_PROVEN
UNMAP_DONE for the same request/map generation
NO_REMAP during the attribution window
buffer remains gadget-owned during the observation window
no CPU write path to the observed range during the window
no post-U dma_sync_* on the observed range
exactly one declared post-U CPU observation of the witness range
memory mutation occurs after U
mutated bytes match a host-supplied post-U pattern
```

On a platform without an IOMMU, matching the post-U host pattern is a load-bearing attribution discriminator, not merely an impact embellishment. A mutation with no such discriminator is `POST_U_MUTATION_OBSERVED / SOURCE_UNATTRIBUTED`, not `R3_PROVEN`.

An IOMMU fault by itself cannot prove `D_commit`.

## Impact

Retained-buffer R3 and changed-ownership impact are separate experiments:

```text
A-R3a  gadget retains allocation -> stable witness -> prove post-unmap commit
A-R3b  allocation is released/reused -> successor ownership possible -> separate attribution design required
```

A-R3b does not inherit the retained witness from A-R3a. Security-impact promotion requires a concrete ownership/confidentiality/integrity boundary crossing plus attacker preconditions and controllability.

The report remains modular:

```text
Claim 1 — R1A: unmap proceeds without fresh quiescence acknowledgement on an incomplete same-generation transfer
Claim 2 — R2: same-mapping post-unmap DMA attempt
Claim 3 — R3: attributed completed post-lifetime memory effect
Claim 4 — Impact: controllability + security-boundary crossing
```

A failure to prove Claim 3 must not erase a valid Claim 2.

## PRIMARY-B separation

PRIMARY-B (`dequeue` on isochronous DDMA) has its own trigger, capability assumptions, R1-equivalent gate, attribution controls, and R2/R3 evidence. No PRIMARY-A runtime evidence is inherited by PRIMARY-B, and vice versa.
