# R1A runtime runbook

## Campaign order

Run PRIMARY-A R1A `SET_CONFIGURATION(0)` first. Escalate to nonzero configuration/interface branches only if needed and only under their own frozen configuration fingerprint.

PRIMARY-A requires a host capable of issuing the raw control trigger while its own Bulk OUT payload is still outstanding. This is a self-imposed timing race and is a required capability, not an assumed property.

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

`mapping_generation` increments at each successful map. `program_generation` is separate and increments each time the active OUT request is programmed into the endpoint/DMA state for that lineage. `dma_addr` is diagnostic only.

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
```

Any existing driver-side W1C clear of `EPDISBLD` between this PRE observation and the RESULT observation must be observed/attributed. If such a clear occurs and cannot itself be tied to a positive terminal result for the same lineage, the attempt is `R1A_AMBIGUOUS`.

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
- `timeout_no_ack`: the natural wait timed out and no fresh assertion is observed before U.
- `ambiguous`: stale-high PRE state, intervening/unattributed W1C clear, generation mismatch, event loss, or any inability to distinguish a fresh assertion.

Both `fresh_ack` and `timeout_then_ack_before_U` kill R1A for that linked attempt. A warning emitted by the driver's timeout path is therefore never classified as R1A success without checking for a late acknowledgement before U.

## R1A_PROVEN

A linked PRIMARY-A attempt may be classified `R1A_PROVEN` only when all frozen conditions in `EVIDENCE-LADDER.md` hold, including:

```text
MAP -> PROGRAMMED for one lineage
host Bulk OUT outstanding at trigger
request_generation unchanged
mapping_generation unchanged
program_generation unchanged after the load-bearing PROGRAMMED event
EPDISBLD clear immediately before EPDIS
EPDIS_RESULT == timeout_no_ack
no same-lineage completion-path event before U
UNMAP_BEGIN -> UNMAP_DONE on the same lineage
no intervening map or endpoint re-program event
lost == 0
```

`EPENA`, `xfrsiz_pre`, `xfrsiz_result`, and `xfrsiz_delta` are recorded as SUPPORT only.

This classification means software proceeded to unmap the same request/mapping/program lineage without an observed same-lineage completion and without a fresh positive controller acknowledgement that endpoint disable completed. It is not a direct hardware-ownership bit and must not be described as one.

## R1A_DEAD

A linked attempt is `R1A_DEAD` if either positive terminal condition occurs before U:

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
- stale PRE `EPDISBLD`, any unattributed W1C clear between PRE and RESULT, missing completion-path coverage, or lineage mismatch makes the linked attempt ambiguous.

## Required artifacts

- S0 / S1 / S2 observer dumps;
- campaign-only usbmon capture;
- holder event log with session and boot identity;
- host harness log / manifest;
- per-attempt request/mapping/program lineage;
- `EPDIS_ASSERT` raw `DOEPCTL` / `DOEPINT` / `DOEPTSIZ`;
- completion-path events for the linked request;
- PRE/RESULT `XFRSIZ` plus delta;
- any observed W1C clear event between PRE and RESULT;
- four-state `EPDIS_RESULT`;
- `UNMAP_BEGIN` / `UNMAP_DONE` for the same lineage;
- exact image/tool hashes and epoch block;
- final gate JSON and generated verdict;
- SHA256 for every artifact.

## Interpretation

`R1A_PROVEN` closes only the observable PRIMARY-A statement defined above for its linked attempt. It does not by itself prove real post-U device access, `D_issue`, `D_commit`, or security impact.

`UNMAP_DONE` is an observation point. `same_mapping_generation`, `same program_generation`, and `NO_REMAP` are attribution controls. They are not vertical proof steps.

PRIMARY-B (`dequeue` on isochronous DDMA) is a separate campaign with separate trigger/preconditions and does not inherit PRIMARY-A evidence.
