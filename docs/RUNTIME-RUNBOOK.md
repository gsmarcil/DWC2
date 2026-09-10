# R1A runtime runbook

## Campaign order

Run PRIMARY-A R1A `SET_CONFIGURATION(0)` first. Escalate to nonzero configuration/interface branches only if needed and only under their own frozen configuration fingerprint.

PRIMARY-A requires a host capable of issuing the raw control trigger while its own Bulk OUT payload is still outstanding. This is a self-imposed timing race and is a required capability, not an assumed property.

Reset/disconnect handling is a separate PRIMARY-A branch. It must not inherit the endpoint-stop EPDIS predicate when the source path does not execute `dwc2_hsotg_ep_stop_xfr()`.

## Preflight

1. Boot the exact frozen observer image.
2. Read running kernel facts; do not infer them from the command line:
   - `g_dma=1`
   - `g_dma_desc=0`
   - ABI v9 / header 112 / record 80
   - `snapshot_atomic=1`
   - `lost=0`
3. Freeze the epoch from the files that will actually execute.
4. Verify host endpoint identity and device holder endpoint identity match.
5. Run the two-arm re-arm discriminator and record whether `USBDEVFS_RESETEP` is required.
6. Establish sensitivity from observer counters, usbmon and holder evidence.
7. For reset/disconnect work, capture the raw controller signature `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` from the same boot/configuration epoch before making any hardware-contract statement. `GSNPSID` alone is insufficient to select a load-bearing DMA/reset contract.

## Per-attempt validity

A valid attempt requires both host and gadget-side arms:

```text
host Bulk OUT URB outstanding at trigger
AND
device holder pending-read depth >= frozen floor
AND
exact raw EP0 control tuple
AND
no foreign reset/disconnect contamination in the measurement window
AND
wire and holder witnesses agree
```

Host completion status after the trigger is not used as a validity filter.

## R1A load-bearing observation set

Every load-bearing event must carry explicit lineage:

```text
request_generation
mapping_generation
program_generation
endpoint
```

`mapping_generation` increments at each successful map. `program_generation` is separate and increments only at the `DOEPCTL.EPENA` write that hands the active OUT request to hardware. A `DOEPDMA` write is recorded as an associated field but does not increment the generation. `dma_addr` is diagnostic only.

The observer also maintains `epint_generation[endpoint]`, incremented at entry to `dwc2_hsotg_epint()` for the relevant OUT endpoint.

### Measurement path must not modify DOEPINT

`DXEPINT_EPDISBLD` is W1C. The measurement code is read-only with respect to `DOEPINT`; it must never clear or set that register merely to observe it.

Immediately before the existing driver EPDIS write, record `EPDIS_ASSERT` with raw:

```text
DOEPCTL
DOEPINT
DOEPTSIZ
request_generation
mapping_generation
program_generation
epint_generation
```

Any existing driver-side W1C clear of `EPDISBLD` between this PRE observation and the RESULT observation must be observed/attributed. If such a clear occurs and cannot itself be tied to a positive terminal result for the same lineage, the attempt is `R1A_AMBIGUOUS`.

### Do not perturb the wait

The measurement patch must not add register reads, tracepoints, branches, delays, counters, or other work inside the polling body of `dwc2_hsotg_wait_bit_set()` or otherwise alter the number/timing of its iterations. Record only immediately before the existing EPDIS action and immediately after the natural wait returns.

No instrumentation change is acceptable if it changes:

```text
poll cadence
poll count
timeout duration
wait return semantics
ordering of the existing EPDIS / W1C / unmap path
```

### Completion witness is the completion path, not a register absence

Do not use a late read of `DOEPINT.XferCompl` to prove absence of completion. The load-bearing witness is an event emitted on the same request's completion path with request/mapping/program lineage attached.

A same-lineage completion-path event before U is terminal and yields `R1A_DEAD` for that attempt. Absence is usable only if the completion event stream is complete and `lost == 0`.

### XFRSIZ is supporting context only

Capture `DOEPTSIZ.XFERSIZE` both before EPDIS and at RESULT. The value is asynchronous to controller progress and may remain positive after a short OUT transfer is effectively complete. Store:

```text
xfrsiz_pre
xfrsiz_result
xfrsiz_delta = xfrsiz_pre - xfrsiz_result
```

No single value or positive residual is a proof condition.

## Four-state EPDIS_RESULT

The observer must classify the endpoint-disable result as exactly one of:

```text
fresh_ack
timeout_then_ack_before_U
timeout_no_ack
ambiguous
```

Definitions:

- `fresh_ack`: `EPDISBLD` was known clear immediately before EPDIS and a fresh assertion is observed before the natural wait deadline and before U.
- `timeout_then_ack_before_U`: the driver's natural wait timed out, but a fresh assertion is observed after the timeout and before U.
- `timeout_no_ack`: the natural wait timed out, no fresh assertion is observed before U, and `epint_generation` is unchanged from `WAIT_RETURN` to `PRE_U`.
- `ambiguous`: stale-high PRE state, intervening/unattributed W1C clear, a changed `epint_generation` in the `WAIT_RETURN -> PRE_U` interval, generation mismatch, event loss, or any inability to distinguish a fresh assertion.

Both `fresh_ack` and `timeout_then_ack_before_U` kill R1A for that linked attempt. A warning emitted by the driver's timeout path is therefore never classified as R1A success without checking for a late acknowledgement before U.

### WAIT_RETURN -> PRE_U cleanliness

At the natural wait return, record:

```text
WAIT_RETURN.epint_generation
WAIT_RETURN.DOEPINT
WAIT_RETURN.DOEPTSIZ
```

At the last read-only observation before U, record:

```text
PRE_U.epint_generation
PRE_U.DOEPINT
PRE_U.DOEPTSIZ
```

If the two `epint_generation` values differ, `timeout_no_ack` cannot be promoted; the attempt is `R1A_AMBIGUOUS`. This prevents an endpoint-interrupt handler from asserting/clearing a witness invisibly between the two samples.

## Endpoint-stop R1A_PROVEN

A linked PRIMARY-A endpoint-stop attempt may be classified `R1A_PROVEN` only when all frozen conditions in `EVIDENCE-LADDER.md` hold, including:

```text
MAP -> PROGRAMMED for one lineage
host Bulk OUT outstanding at trigger
request_generation unchanged
mapping_generation unchanged
program_generation unchanged after the load-bearing PROGRAMMED event
EPDISBLD clear immediately before EPDIS
EPDIS_RESULT == timeout_no_ack
WAIT_RETURN.epint_generation == PRE_U.epint_generation
no same-lineage completion-path event before U
UNMAP_BEGIN -> UNMAP_DONE on the same lineage
no intervening map or endpoint re-program event
lost == 0
```

`EPENA`, `xfrsiz_pre`, `xfrsiz_result`, and `xfrsiz_delta` are recorded as SUPPORT only.

This classification means software proceeded to unmap the same request/mapping/program lineage without an observed same-lineage completion and without a fresh positive controller acknowledgement that endpoint disable completed. It is not a direct hardware-ownership bit and must not be described as one.

## Reset/disconnect PRIMARY-A branch

For a reset/disconnect branch in which source flow reaches `dwc2_hsotg_disconnect()` and request retirement without `dwc2_hsotg_ep_stop_xfr()`:

```text
EPDIS_ASSERT = NOT_REACHED
WAIT_RETURN = NOT_REACHED
EPDIS_RESULT = NOT_APPLICABLE
```

These missing events are expected and do not make the instrumentation incomplete.

The source ordering matters for instrumentation design: the top-level gadget IRQ handles `USBRST/RESETDET` and calls `dwc2_hsotg_disconnect()` before it later services `OEPINT/IEPINT` from the same IRQ snapshot, while the same `hsotg->lock` is held. `kill_all_requests()` clears `ep->req` before completing queued requests. Therefore a completion that is pending or becomes pending during reset/kill can be lost to a normal `XFERCOMPL_PATH` hook that dereferences `hs_ep->req` only later. The reset branch must preserve active lineage before `disconnect()`.

### Databook gate: `K_hw`

Do not use product pages, old Raspberry Pi source comments, or a generic DWC2 implementation as load-bearing hardware evidence. They may be retained as `WEAK_SIGNAL` only.

After reading the running `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` tuple, select a databook/revision only if its core revision and applicable synthesized configuration match the observed signature. A revision-only match is insufficient. Then classify exactly one result:

```text
explicit text says reset terminates/quiesces pending device DMA
    -> K_hw = TERMINATES_PENDING_DMA
    -> RESET BRANCH = DEAD within that contract scope

explicit text says reset does not terminate pending DMA,
or requires software SNAK/disable/quiesce
    -> K_hw = ABSENT
    -> reset itself is not a hardware quiescence guarantee

no explicit matched text
    -> K_hw = UNDETERMINED
    -> no evidence-ladder movement
```

`K_hw = UNDETERMINED` is expected and is not evidence for either side.

### Reset-safe runtime fallback when `K_hw = UNDETERMINED`

Use the measurement observer itself rather than inferring from documentation silence. The reset-capable observer must add a `reset_generation` and preserve the active eligible OUT lineage before `dwc2_hsotg_disconnect()` retires it.

For that same lineage capture:

```text
PROGRAMMED.epint_generation
RESET_ENTRY:
  reset_generation
  request_generation
  mapping_generation
  program_generation
  endpoint
  epint_generation
  raw DOEPINT
  raw DOEPTSIZ

PRE_U:
  same reset/request/map/program/endpoint lineage
  epint_generation
  raw DOEPINT
  raw DOEPTSIZ

UNMAP_DONE:
  same reset/request/map/program/endpoint lineage
  epint_generation
  raw DOEPINT
  raw DOEPTSIZ
```

The reset observer must not write `DOEPINT`, add a stop/NAK, change IRQ ordering, or modify map/unmap behavior.

`UNMAP_DONE` is post-U and is register-only apart from stable lineage metadata. Its mapping/request-payload slots must be zero sentinels (`dma_addr`, `program_dma`, `length`, `actual`, `result`, `status`, `dma_mapped` all zero). After the real unmap returns, the observer may read only stable lineage/endpoint bookkeeping and the raw `DOEPCTL` / `DOEPINT` / `DOEPTSIZ` MMIO needed for the reset discriminator; it must not read `req->dma`/`req->buf`, touch the request buffer, call `dma_sync_*`, remap, or add a memory-side witness.

### Mandatory three-arm reset discriminator

The reset campaign order is fixed:

```text
controller signature
    -> CTRL-IDLE validity/pass
    -> CTRL-COMPLETED validity/pass
    -> CAMPAIGN-LIVE
```

Run and preserve all three arms under the same observer/controller/configuration fingerprint:

```text
CTRL-IDLE
  no eligible live OUT transfer at reset
  detects reset-synthesized/reasserted XferCompl

CTRL-COMPLETED
  same transfer class completes naturally first
  positive natural completion witness precedes reset
  RESET_ENTRY.XferCompl = 0
  reset follows after a recorded, pre-frozen interval
  proves the completion bit was actually clear before reset,
  then tests whether a fresh 0 -> 1 can appear anyway

CAMPAIGN-LIVE
  same transfer class is positively outstanding at RESET_ENTRY
  tests the surviving reset branch
```

`CTRL-COMPLETED` is valid only when **both** its positive natural completion witness and `RESET_ENTRY.XferCompl=0` are present. If the bit is still high at `RESET_ENTRY`, or the completion witness is absent, the arm did not test the intended cleared-before-reset state: mark it `CONTROL_INVALID`, recalibrate/repeat it, and do not count it as clean. A valid `CTRL-COMPLETED` that later produces a new post-reset `0 -> 1` makes the campaign transition non-discriminating and forces `R1A_AMBIGUOUS`. Any post-reset `0 -> 1` in a valid `CTRL-IDLE` has the same effect. Freeze the control denominators, completed-to-reset interval, and completion witness before campaign execution.

**Do not start or promote `CAMPAIGN-LIVE` if either control arm has not first produced a valid attempt.** Invalid controls stop the campaign gate; they are never converted into negative evidence.

### Endpoint-safe event joining

Do not join reset observations by timestamp/order alone. `kill_all_requests()` processes endpoints sequentially while the same controller lock is held, so another endpoint can generate events between a candidate endpoint's observations. A load-bearing reset transition must join:

```text
RESET_ENTRY
PRE_U
UNMAP_DONE
```

only when the complete tuple matches exactly:

```text
reset_generation
request_generation
mapping_generation
program_generation
endpoint
```

The trace event already carries `endpoint`; analysis must use it. `PRE_U.epint_generation` and `UNMAP_DONE.epint_generation` are compared only after that full endpoint+lineage join succeeds.

Reset-specific interpretation is frozen as follows:

```text
normal same-lineage XFERCOMPL_PATH before U
    -> R1A_DEAD

RESET_ENTRY.XferCompl = 0
and PRE_U.XferCompl = 1
and same reset/request/map/program/endpoint lineage
and unchanged epint_generation
    -> fresh terminal completion before U
    -> R1A_DEAD

PRE_U.XferCompl = 0
and UNMAP_DONE.XferCompl = 1
and same reset/request/map/program/endpoint lineage
and unchanged epint_generation
and CTRL-IDLE valid+clean
and CTRL-COMPLETED valid+clean
    -> RESET_POST_U_COMPLETION_PROGRESS
    -> positive evidence that software unmapped before the controller's terminal completion signal
    -> eligible for the reset-specific R1A promotion predicate
    -> NOT D_issue and NOT D_commit by itself

DOEPTSIZ changes across PRE_U -> UNMAP_DONE without the fresh XferCompl transition
    -> SUPPORT only

no post-reset progress observed
    -> NOT_OBSERVED for this configuration
    -> does not prove reset globally quiesces DMA
```

If `XferCompl` is already high at `RESET_ENTRY`, do not call it fresh merely because it is high. Without an independently attributable completion-path witness, classify the attempt `AMBIGUOUS` unless a stricter lineage rule frozen before the run can prove that the assertion arose after the current `PROGRAMMED` handoff.

The added reset-entry MMIO snapshots delay U slightly and therefore bias against observing an unfinished transfer at U rather than creating one; nevertheless the observer must record that overhead and never describe the instrumented timing as identical to an uninstrumented kernel.

## R1A_DEAD

A linked endpoint-stop attempt is `R1A_DEAD` if either positive terminal condition occurs before U:

```text
same-lineage completion-path event
```

or:

```text
EPDIS_RESULT == fresh_ack
```

or:

```text
EPDIS_RESULT == timeout_then_ack_before_U
```

For reset/disconnect, `R1A_DEAD` is produced by an exact matched-databook `K_hw = TERMINATES_PENDING_DMA` guarantee, a normal same-lineage completion-path event before U, or a reset-safe fresh `XferCompl` transition before U under complete lineage/no-handler/no-reprogram controls.

This symmetry is mandatory. If the observer cannot distinguish PROVEN from DEAD under the frozen rules, the result is `R1A_AMBIGUOUS` and cannot be promoted.

## Snapshots / denominator

Use three observer snapshots:

```text
S0  after re-arm preflight, before sensitivity
S1  after sensitivity, before campaign
S2  after campaign
```

Sensitivity and campaign denominators are derived from counter deltas; operator-entered counts are not trusted.

Only campaign-slice records are eligible:

```text
records[S1.count:S2.count]
```

`B_valid == 0` is always ineligible for a negative result.

## Batch handling

- Any attempt that fired the campaign trigger but is invalid makes the batch unusable for negative aggregation unless attribution proves it contributed no candidate.
- Foreign matching controls/teardowns make the batch ineligible.
- `lost > 0`, non-atomic snapshots, reset-generation changes, witness mismatch or epoch mismatch all fail closed.
- stale PRE `EPDISBLD`, any unattributed W1C clear between PRE and RESULT, changed `epint_generation` in `WAIT_RETURN -> PRE_U`, missing completion-path coverage, or lineage mismatch makes the linked attempt ambiguous.
- on reset/disconnect, failure to preserve the active lineage before `disconnect()`, failure of the full reset/request/map/program/endpoint join, or ambiguity about a pending `XferCompl` makes the attempt ineligible for promotion.
- `CTRL-IDLE` and `CTRL-COMPLETED` must each be valid under their frozen predicates before `CAMPAIGN-LIVE` begins; `CONTROL_INVALID` stops the reset campaign gate and is not a clean control.

## Required artifacts

- S0 / S1 / S2 observer dumps;
- campaign-only usbmon capture;
- holder event log with session and boot identity;
- host harness log / manifest;
- per-attempt request/mapping/program lineage;
- associated `DOEPDMA` value for each `program_generation`;
- `EPDIS_ASSERT` raw `DOEPCTL` / `DOEPINT` / `DOEPTSIZ`;
- completion-path events for the linked request;
- PRE/RESULT `XFRSIZ` plus delta;
- `WAIT_RETURN` and `PRE_U` endpoint-interrupt generations;
- any observed W1C clear event between PRE and RESULT;
- four-state `EPDIS_RESULT`;
- `UNMAP_BEGIN` / `UNMAP_DONE` for the same lineage;
- reset branch: raw `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` controller signature, selected databook identity/applicability/result, `K_hw`, valid `CTRL-IDLE`, valid `CTRL-COMPLETED` with prior natural completion witness and `RESET_ENTRY.XferCompl=0`, `CAMPAIGN-LIVE`, `reset_generation`, exact endpoint, `RESET_ENTRY`, reset-safe `PRE_U`, and register-only reset-safe `UNMAP_DONE` raw `DOEPCTL`/`DOEPINT`/`DOEPTSIZ`;
- exact image/tool hashes and epoch block;
- final gate JSON and generated verdict;
- SHA256 for every artifact.

## Instrumentation semantic review gate

Before any hardware epoch, the measurement patch must pass all six checks:

```text
1  no added DOEPINT write
2  no changed teardown ordering
3  no extra map/unmap
4  no hidden endpoint re-programming
5  no new runtime claim encoded in instrumentation
6  no change in natural wait timing/cadence/iteration semantics
```

For reset-capable instrumentation, add these fail-closed checks without renumbering the base six:

```text
RESET-A  active request lineage is captured before disconnect/kill
RESET-B  no SNAK/EPDIS/quiesce action is added by measurement
RESET-C  reset IRQ ordering is unchanged
RESET-D  UNMAP_DONE register snapshot occurs only after the real unmap returns
RESET-E  UNMAP_DONE has zero mapping/request-payload reads and emits lineage + raw MMIO only
RESET-F  idle-reset and completed-then-reset controls are both valid before campaign promotion
RESET-G  reset transitions are joined by identical reset/request/map/program/endpoint tuples, never time alone
```

Failure of any item blocks the instrument regardless of whether it compiles.

## Interpretation

`R1A_PROVEN` closes only the observable branch-specific PRIMARY-A statement defined above for its linked attempt. It does not by itself prove real post-U device access, `D_issue`, `D_commit`, or security impact.

`UNMAP_DONE` is an observation point. `same_mapping_generation`, `same program_generation`, and `NO_REMAP` are attribution controls. They are not vertical proof steps.

PRIMARY-B (`dequeue` on isochronous DDMA) is a separate campaign with separate trigger/preconditions and does not inherit PRIMARY-A evidence.
