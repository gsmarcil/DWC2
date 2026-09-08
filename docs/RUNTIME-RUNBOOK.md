# R1A runtime runbook

## Campaign order

Run R1A `SET_CONFIGURATION(0)` first. Escalate to nonzero configuration/interface branches only if needed and only under their own frozen configuration fingerprint.

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
no reset/disconnect contamination in the measurement window
AND
wire and holder witnesses agree
```

Host completion status after the trigger is not used as a validity filter.

## Snapshots / denominator

Use three observer snapshots:

```text
S0  after re-arm preflight, before sensitivity
S1  after sensitivity, before campaign
S2  after campaign
```

Sensitivity and campaign denominators are derived from counter deltas; operator-entered counts are not trusted.

Only timeout records in the campaign slice are eligible:

```text
records[S1.count:S2.count]
```

`B_valid == 0` is always ineligible for a negative result.

## Batch handling

- Any attempt that fired the campaign trigger but is invalid makes the batch unusable for negative aggregation unless attribution proves it contributed no candidate.
- Foreign matching controls/teardowns make the batch ineligible.
- `lost > 0`, non-atomic snapshots, reset-generation changes, witness mismatch or epoch mismatch all fail closed.

## Required artifacts

- S0 / S1 / S2 observer dumps;
- campaign-only usbmon capture;
- holder event log with session and boot identity;
- host harness log / manifest;
- exact image/tool hashes and epoch block;
- final gate JSON and generated verdict;
- SHA256 for every artifact.

## Interpretation

A positive timeout closes R1A only for its linked attempt. It does not by itself prove U, `D_issue`, `D_commit`, or security impact.
