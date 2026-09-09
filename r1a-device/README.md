# R1A device source — holder-witness producer

This directory is the canonical repository location for the gadget-side R1A harness.

## Canonical source

The active source is:

```text
r1a_ffs_out_v2.c
```

This file is **new holder-witness producer source** introduced by the holder-producer
delivery. It is not a restored or recovered copy of an earlier matching producer.
The pre-holder source is preserved separately as:

```text
legacy/r1a_ffs_out_v2.c.pre-holder
```

with SHA256:

```text
83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d6116958f126118e
```

The active producer's source hash is admitted only by the repository/application
gates. Structural self-tests and round-trip fixtures do **not** substitute for
runtime execution on a real DWC2 UDC.

## Holder witness contract

The device harness is distinct from the host `usbmon` witness:

- `usbmon` establishes the host-side outstanding-URB condition;
- the holder producer establishes the gadget-side queued-request/holder condition.

The producer emits the JSONL contract consumed by
`baseline/pipeline/holder_merge.py`. Campaign records are deliberately distinct
from synthetic self-test records:

```text
campaign: event=R1A_HOLDER          phase=campaign
fixture:  event=R1A_HOLDER_SELFTEST phase=selftest  synthetic=true
```

For campaign records, `pending_reads` has exactly this meaning:

```text
eshutdown_kills_at_or_before_cutoff_excluding_sync_submit_failures
```

The lower bound counts only `-ESHUTDOWN` completions assigned to requests killed
on the endpoint queue at or before the episode cutoff. Unresolved reads,
post-cutoff kills, and synchronous/prequeue submit failures are excluded.

## Current evidence state

```text
canonical holder producer source    ADMITTED BY PRE-RUNTIME GATES
legacy pre-holder source             PRESERVED / HASH-PINNED
holder contract self-test            REQUIRED BY REPOSITORY GATE
fixture-log guard self-test           REQUIRED BY REPOSITORY GATE
producer -> frozen merger round-trip REQUIRED BY REPOSITORY GATE
real DWC2 board runtime               NOT EXECUTED
```

## Rule

Do not promote a board-negative claim from structural controls alone. The next
load-bearing transition requires real DWC2 runtime evidence, and any runtime
claim remains bounded by the exact observer/producer epoch that generated it.
