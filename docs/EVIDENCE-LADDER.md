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

`program_generation` is a distinct monotonically increasing counter assigned only when the active OUT request is handed to hardware by the `DOEPCTL.EPENA` programming write. The associated `DOEPDMA` write is recorded as data for that generation but does not increment the counter. Therefore `program_generation` increasing again for the same mapping generation means a true re-programming event rather than the two normal register writes of one programming operation.

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

The observer also maintains an endpoint-interrupt-entry generation for the affected endpoint. It increments at entry to `dwc2_hsotg_epint()` and is sampled at `WAIT_RETURN` and `PRE_U`. The interval is considered clean only when those generations are equal. If another endpoint-interrupt handler ran between those observations, `timeout_no_ack` remains a candidate only and the attempt is `R1A_AMBIGUOUS`; absence of a visible bit cannot then be promoted to proof.

No measurement read may be inserted into the body of the driver's natural wait loop. The observer must not change the loop's polling cadence, timeout length, or iteration count.

### EPDIS_RESULT is four-state

```text
EPDIS_RESULT = fresh_ack
             | timeout_then_ack_before_U
             | timeout_no_ack
             | ambiguous
```

- `fresh_ack`: `EPDISBLD` was known clear immediately before EPDIS and a fresh assertion is observed before the natural wait deadline and before U.
- `timeout_then_ack_before_U`: the natural wait times out, but a fresh `EPDISBLD` assertion is observed after the timeout and before U.
- `timeout_no_ack`: the natural wait times out, no fresh `EPDISBLD` assertion is observed before U, and the `WAIT_RETURN -> PRE_U` interval is proven free of endpoint-interrupt-handler entries for that endpoint.
- `ambiguous`: stale-high PRE state, an intervening W1C clear, an endpoint-interrupt entry in the `WAIT_RETURN -> PRE_U` interval, observation loss, lineage mismatch, or any condition that prevents proving whether an assertion is fresh.

`fresh_ack` and `timeout_then_ack_before_U` both kill R1A for that linked attempt. A timeout warning is therefore never sufficient evidence by itself.

### Completion witness

`no same-request XferCompl before U` is not inferred by reading `DOEPINT`. The load-bearing completion witness is the same request's completion path itself, correlated by request, mapping and program generations.

A same-lineage completion-path event before U is a positive terminal artifact and yields `R1A_DEAD`. Absence of such an event is usable only when the event stream is complete and the hook is on the completion path, not after a point that may already have W1C-cleared `XferCompl`.

### XFRSIZ is SUPPORT only

`DOEPTSIZ.XFERSIZE` is sampled at PRE and RESULT. It is asynchronous to core activity, and a short OUT transfer can leave a positive value even when the transfer is effectively complete. Therefore a positive residual never proves ownership. Only the PRE/RESULT values and their delta are retained as supporting context.

### PRIMARY-A reset/disconnect branch

The reset/disconnect path is a distinct PRIMARY-A branch. In that path `dwc2_hsotg_disconnect()` can retire requests without first calling `dwc2_hsotg_ep_stop_xfr()`. Therefore:

```text
EPDIS_ASSERT = NOT_REACHED
WAIT_RETURN = NOT_REACHED
EPDIS_RESULT = NOT_APPLICABLE
```

for that branch. Missing EPDIS events are not treated as instrumentation failure. Evidence from the EPDIS branch is not silently inherited into reset/disconnect.

The reset branch also has an IRQ-ordering constraint: the top-level gadget IRQ handles `USBRST/RESETDET` and calls `dwc2_hsotg_disconnect()` before it later services `OEPINT/IEPINT` from the same IRQ snapshot. `kill_all_requests()` clears `ep->req` before completing the queued requests. Therefore the ordinary `XFERCOMPL_PATH` hook alone is structurally insufficient to guarantee preservation of a completion that becomes pending in the reset/kill window. A reset-safe witness must preserve the active request/map/program lineage before `disconnect()` retires it.

#### Reset hardware contract `K_hw`

Only an exact controller databook/revision matched to the running controller signature may carry the hardware-contract claim. The minimum signature is the raw tuple `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` from the same boot/configuration epoch. `GSNPSID` identifies the core revision but does not, by itself, establish the synthesized DMA/endpoint configuration. The selected databook must apply to that revision and to the observed `GHWCFG1..4` configuration relevant to reset/DMA semantics; if that applicability cannot be established, `K_hw` remains `UNDETERMINED`. Product pages, legacy Raspberry Pi source comments, and third-party implementations are at most `WEAK_SIGNAL` and are excluded from load-bearing report evidence.

The hardware-contract result is frozen as exactly one of:

```text
explicit text: reset terminates/quiesces pending device DMA
    -> K_hw = TERMINATES_PENDING_DMA
    -> RESET BRANCH = DEAD for the relevant contract scope

explicit text: reset does not terminate pending DMA,
or software must explicitly NAK/disable/quiesce the endpoint
    -> K_hw = ABSENT
    -> real promotion: reset itself is not a quiescence guarantee

no explicit text for the matched controller revision/configuration
    -> K_hw = UNDETERMINED
    -> no movement in the evidence ladder
```

Absence of documentation is never evidence that `K_hw` is absent.

#### Reset-safe completion/progress witness

When `K_hw = UNDETERMINED`, hardware observation is the planned fallback rather than an inference from missing documentation. The observer must record, for the active eligible OUT lineage, a `RESET_ENTRY` snapshot before request retirement and the existing `PRE_U` / `UNMAP_DONE` observations with:

```text
reset_generation
request_generation
mapping_generation
program_generation
epint_generation
raw DOEPINT
raw DOEPTSIZ
```

The measurement code remains read-only with respect to `DOEPINT` and must not reorder the reset/disconnect path.

`UNMAP_DONE` occurs after U and therefore has a stricter payload rule than earlier events. It may emit only stable lineage metadata (`reset/request/map/program`, endpoint, endpoint-interrupt generation) plus raw endpoint MMIO (`DOEPCTL`, `DOEPINT`, `DOEPTSIZ`). Mapping/request-payload fields are zero sentinels at this stage: `dma_addr=0`, `program_dma=0`, `length=0`, `actual=0`, `result=0`, `status=0`, `dma_mapped=0`. The `UNMAP_DONE` path must not read `req->dma`, `req->buf`, a saved/alignment buffer, or invoke `dma_sync_*`, another map/unmap, or any memory-side witness helper after the real unmap has returned.

#### Mandatory reset transition controls

A campaign `0 -> 1` `XferCompl` transition is discriminating only when **both** negative-control classes have passed in the same frozen controller/observer configuration:

```text
CTRL-IDLE / idle-reset
    no eligible live OUT transfer at reset
    purpose: detect XferCompl synthesized/reasserted by reset itself

CTRL-COMPLETED / completed-then-reset
    matching OUT transfer has a positive natural completion witness
    reset follows after a recorded, pre-frozen interval
    purpose: detect delayed/stale completion reporting from a transfer
             that was already complete before reset

CAMPAIGN-LIVE / live-then-reset
    matching OUT transfer is positively outstanding at RESET_ENTRY
    purpose: test the surviving reset branch
```

For `CTRL-COMPLETED`, `XferCompl` high at `RESET_ENTRY` is the direct expected signature when the bit has not already been naturally W1C-serviced. It is **not** made an unconditional validity requirement, because the ordinary endpoint-interrupt path may legitimately clear a completed transfer before the later reset. The fail-closed discriminator is stronger: if an already-completed control can show `RESET_ENTRY.XferCompl=0` followed by a new `0 -> 1` assertion after reset, then the same transition in `CAMPAIGN-LIVE` is non-discriminating and is `R1A_AMBIGUOUS`, not promotion evidence. Likewise, any post-reset `0 -> 1` in `CTRL-IDLE` kills the transition as an attribution discriminator.

Control counts, the completed-to-reset interval, and the exact host completion witness must be frozen before the campaign; they are not chosen after seeing campaign output.

A fresh same-lineage `XferCompl` transition observed before U is terminal and yields `R1A_DEAD` for that attempt. For reset-safe register attribution, a transition is considered fresh only when the earlier snapshot had `XferCompl` clear, the later snapshot has it set, request/map/program generations are unchanged, and no endpoint-interrupt-handler entry or re-programming occurred between the two snapshots. A bit already high at the first reset snapshot is not silently treated as fresh; without an independently attributable completion-path event it is `AMBIGUOUS`.

If `XferCompl` is clear at `PRE_U` and becomes set only at `UNMAP_DONE`, with the same lineage and no intervening endpoint handler/re-programming, the observer has proved **post-U controller completion progress for that programmed transfer**. This may support the reset-specific R1A predicate that software unmapped before the controller's terminal completion signal, but it does not by itself prove that an OUT memory write occurred after U. A `DOEPTSIZ` delta across `PRE_U -> UNMAP_DONE` is supporting context only and is never promoted alone to `D_issue` or `D_commit`.

If no post-reset progress is observed, the result is `NOT_OBSERVED` for that configuration; it does not prove that reset globally quiesces DMA.

### R1A_PROVEN

For one linked PRIMARY-A endpoint-stop attempt, all of the following are required:

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
WAIT_RETURN epint_generation == PRE_U epint_generation
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

For the reset/disconnect PRIMARY-A branch, `R1A_PROVEN` uses a separate branch-specific predicate and does not require EPDIS observations that the source path never executes. A reset-specific promotion may come from an explicit matched-databook `K_hw = ABSENT` contract combined with the frozen software ordering, or from a positive same-lineage runtime observation that the controller's terminal completion signal occurs only after U. Until one of those predicates is satisfied under complete lineage controls, the branch may be `SUPPORTED`, `DEAD`, `AMBIGUOUS`, or `NOT_OBSERVED`, but it may not borrow the endpoint-stop criterion.

### R1A_SUPPORTED_ONLY

The following are supporting signals but are insufficient alone:

- `DXEPCTL_EPENA` still set near U: the bit may be stale.
- no completion-path witness before U when event completeness is not independently established.
- positive residual `DOEPTSIZ.XFRSIZ`.
- PRE/RESULT `XFRSIZ` delta.
- a stop timeout without the full fresh-ack and lineage controls.
- a `timeout_no_ack` observation whose `WAIT_RETURN -> PRE_U` interval is not proven clean of endpoint-interrupt-handler entries.
- reset/disconnect retirement while `K_hw = UNDETERMINED` and no positive reset-safe runtime progress witness exists.
- a `DOEPTSIZ` delta without a fresh terminal-status transition.

### R1A_DEAD

For a linked endpoint-stop attempt, R1A is killed by a positive terminal observation before U, including either:

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

For the reset/disconnect PRIMARY-A branch, R1A is killed by either an exact matched-databook `K_hw = TERMINATES_PENDING_DMA` guarantee or a fresh same-lineage completion witness before U. A reset-safe `XferCompl` transition from clear to set before U is an acceptable positive terminal witness when its lineage and no-handler/no-reprogram controls are complete.

A dead attempt is not eligible for R2/R3 promotion.

Missing data, stale PRE-set acknowledgement bits, an intervening W1C clear, endpoint-interrupt activity in an unguarded attribution interval, event loss, identity mismatch, re-programming, or ambiguous ordering produce `R1A_AMBIGUOUS`, not `R1A_PROVEN` and not `R1A_DEAD`.

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
