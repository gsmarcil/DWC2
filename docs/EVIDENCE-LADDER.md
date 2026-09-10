# Evidence ladder

## PRIMARY-A / R1A — teardown without confirmed quiescence

R1A is deliberately defined in terms of observable controller/software state. It does **not** claim that a hidden hardware-ownership bit exists.

### Observable lineage

Every load-bearing event is tied to:

```text
request_generation
mapping_generation
program_generation
endpoint
```

`mapping_generation` is an explicit monotonically increasing counter assigned at every successful map. `dma_addr` is diagnostic only and is never mapping identity.

`program_generation` is a distinct monotonically increasing counter assigned every time the active OUT request is programmed into the endpoint/DMA state for that lineage. Re-programming the same DMA mapping therefore cannot be hidden by address reuse or an unchanged map generation.

### EPDISBLD witness discipline

`DXEPINT_EPDISBLD` is W1C. The measurement path itself must never write `DOEPINT`; it is read-only with respect to that register.

Immediately before the driver's existing EPDIS write, `EPDIS_ASSERT` records the raw values of:

```text
DOEPCTL
DOEPINT
DOEPTSIZ
request_generation
mapping_generation
program_generation
```

Any observed or instrumented driver-side clear of `EPDISBLD` between PRE and RESULT invalidates fresh-edge attribution for that attempt and yields `R1A_AMBIGUOUS`, unless the clear is itself tied to a positive terminal outcome for the same lineage.

### EPDIS_RESULT is four-state

```text
EPDIS_RESULT = fresh_ack
             | timeout_then_ack_before_U
             | timeout_no_ack
             | ambiguous
```

- `fresh_ack`: `EPDISBLD` was known clear immediately before EPDIS and a fresh assertion is observed before the natural wait deadline and before U.
- `timeout_then_ack_before_U`: the natural wait times out, but a fresh `EPDISBLD` assertion is observed after the timeout and before U.
- `timeout_no_ack`: the natural wait times out and no fresh `EPDISBLD` assertion is observed before U.
- `ambiguous`: stale-high PRE state, an intervening W1C clear, observation loss, lineage mismatch, or any condition that prevents proving whether an assertion is fresh.

`fresh_ack` and `timeout_then_ack_before_U` both kill R1A for that linked attempt. A timeout warning is therefore never sufficient evidence by itself.

### Completion witness

`no same-request XferCompl before U` is not inferred by reading `DOEPINT`. The load-bearing completion witness is the same request's completion path itself, correlated by request, mapping and program generations.

A same-lineage completion-path event before U is a positive terminal artifact and yields `R1A_DEAD`. Absence of such an event is usable only when the event stream is complete and the hook is on the completion path, not after a point that may already have W1C-cleared `XferCompl`.

### XFRSIZ is SUPPORT only

`DOEPTSIZ.XFERSIZE` is sampled at PRE and RESULT. It is asynchronous to core activity, and a short OUT transfer can leave a positive value even when the transfer is effectively complete. Therefore a positive residual never proves ownership. Only the PRE/RESULT values and their delta are retained as supporting context.

### R1A_PROVEN

For one linked PRIMARY-A attempt, all of the following are required:

```text
same_epoch
same request_generation
same mapping_generation
same program_generation
MAP -> PROGRAMMED observed for that lineage
host-controlled PRIMARY-A trigger linked to the attempt
host Bulk OUT still outstanding at trigger
exact holder/wire validity gates pass
EPDISBLD known clear immediately before EPDIS assertion
EPDIS_RESULT == timeout_no_ack
no same-lineage completion-path witness before U
UNMAP_BEGIN -> UNMAP_DONE for the same lineage
no intervening map generation
no intervening program generation
observer loss == 0
```

Supporting register observations (`EPENA`, PRE/RESULT `XFRSIZ`, and their delta) are retained but are not promoted to proof conditions on their own.

This proves the narrower statement:

> Software proceeded to retire/unmap the same request/mapping/program lineage without an observed same-lineage completion and without obtaining a fresh endpoint-disable acknowledgement before U.

It does **not**, by itself, prove literal hardware ownership at U, post-unmap DMA, or a memory-side effect.

### R1A_SUPPORTED_ONLY

The following are supporting signals but are insufficient alone:

- `DXEPCTL_EPENA` still set near U: the bit may be stale.
- no completion-path witness before U when event completeness is not independently established.
- positive residual `DOEPTSIZ.XFRSIZ`.
- PRE/RESULT `XFRSIZ` delta.
- a stop timeout without the full fresh-ack and lineage controls.

### R1A_DEAD

For a linked attempt, R1A is killed by a positive terminal observation before U, including either:

```text
same-lineage completion-path event before U
```

or

```text
EPDIS_RESULT == fresh_ack
```

or

```text
EPDIS_RESULT == timeout_then_ack_before_U
```

A dead attempt is not eligible for R2/R3 promotion.

Missing data, stale PRE-set acknowledgement bits, an intervening W1C clear, event loss, identity mismatch, re-programming, or ambiguous ordering produce `R1A_AMBIGUOUS`, not `R1A_PROVEN` and not `R1A_DEAD`.

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
Claim 1 — R1A: unmap proceeds without same-lineage completion/fresh disable ack
Claim 2 — R2: same-mapping post-unmap DMA attempt
Claim 3 — R3: attributed completed post-lifetime memory effect
Claim 4 — Impact: controllability + security-boundary crossing
```

A failure to prove Claim 3 must not erase a valid Claim 2.

## PRIMARY-B separation

PRIMARY-B (`dequeue` on isochronous DDMA) has its own trigger, capability assumptions, R1-equivalent gate, attribution controls, and R2/R3 evidence. No PRIMARY-A runtime evidence is inherited by PRIMARY-B, and vice versa.
