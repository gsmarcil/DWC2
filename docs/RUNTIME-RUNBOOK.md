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

The observer must bind every load-bearing sample to explicit `request_id` and monotonically increasing `mapping_generation`. DMA address equality is diagnostic only and never substitutes for generation identity.

For the active OUT request, capture before the endpoint-disable action:

```text
DOEPCTL        including EPENA
DOEPINT        including XferCompl and EPDISBLD state
DOEPTSIZ       including residual XFRSIZ
request_id
mapping_generation
```

Then record the endpoint-disable action and whether a **fresh** `EPDISBLD` acknowledgement occurs. A level that was already set in the pre-disable snapshot is not a fresh acknowledgement.

### PROVEN

A linked attempt may be classified `R1A_PROVEN` only when all frozen conditions in `EVIDENCE-LADDER.md` hold, including:

```text
MAP -> PROGRAMMED for same request/map generation
pre-stop EPENA == 1
pre-stop residual XFRSIZ > 0
no same-request XferCompl before U
EPDISBLD clear before EPDIS assertion
natural wait for fresh EPDISBLD times out
UNMAP_BEGIN -> UNMAP_DONE on same mapping generation
no intervening re-programming
lost == 0
```

This classification means software proceeded to unmap an incompletely transferred same-generation request without a fresh positive controller acknowledgement that endpoint disable completed. It is not a direct hardware-ownership bit and must not be described as one.

### SUPPORTED only

`EPENA=1`, no `XferCompl`, residual `XFRSIZ`, or a timeout may each support R1A, but none is sufficient alone. A pre-set/stale `EPDISBLD` makes the acknowledgement path ambiguous.

### DEAD

A linked attempt is `R1A_DEAD` if a positive terminal condition is observed before U:

```text
same-request XferCompl before U
```

or

```text
EPDISBLD was clear before EPDIS assertion
AND a fresh EPDISBLD transition is observed after EPDIS assertion
AND before U
AND no intervening re-programming/map generation occurred
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
- A stale pre-existing `EPDISBLD`, missing pre-stop register snapshot, or missing request/map identity makes the linked attempt ambiguous.

## Required artifacts

- S0 / S1 / S2 observer dumps;
- campaign-only usbmon capture;
- holder event log with session and boot identity;
- host harness log / manifest;
- per-attempt `request_id` + `mapping_generation` lineage;
- pre-stop `DOEPCTL` / `DOEPINT` / `DOEPTSIZ` snapshot;
- fresh-vs-stale endpoint-disable acknowledgement result;
- exact image/tool hashes and epoch block;
- final gate JSON and generated verdict;
- SHA256 for every artifact.

## Interpretation

`R1A_PROVEN` closes only the observable PRIMARY-A statement defined above for its linked attempt. It does not by itself prove real post-U device access, `D_issue`, `D_commit`, or security impact.

`UNMAP_DONE` is an observation point. `same_mapping_generation` and `NO_REMAP` are attribution controls. They are not vertical proof steps.

PRIMARY-B (`dequeue` on isochronous DDMA) is a separate campaign with separate trigger/preconditions and does not inherit PRIMARY-A evidence.
