# R1A device source — holder-witness producer

This directory is the canonical repository location for the gadget-side R1A harness.

## Canonical source

The active source is:

```text
r1a_ffs_out_v2.c
```

This file is the holder-witness producer admitted for the next pre-hardware
campaign epoch. It is not represented as a recovered copy of the old producer.
The exact pre-holder source remains preserved separately as:

```text
legacy/r1a_ffs_out_v2.c.pre-holder
```

with SHA256:

```text
83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d6116958f126118e
```

The active producer's source is admitted by executable repository gates.
Structural and synthetic round-trip tests do **not** substitute for execution on
a real DWC2 UDC.

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

For campaign records, `pending_reads` has exactly this lower-bound meaning:

```text
eshutdown_kills_at_or_before_cutoff_excluding_sync_submit_failures
```

Only `-ESHUTDOWN` completions assigned to requests killed on the endpoint queue
at or before the episode cutoff raise the count. Unresolved reads,
post-cutoff kills, and synchronous/prequeue submit failures are excluded.

## Current evidence state

```text
canonical holder producer source    ADMITTED BY PRE-RUNTIME GATES
legacy pre-holder source             PRESERVED / HASH-PINNED
holder contract self-test            PASS / REQUIRED BY REPOSITORY GATE
fixture-log guard self-test           PASS / REQUIRED BY REPOSITORY GATE
producer -> frozen merger round-trip PASS / 18 OF 18 CONTROLS
real DWC2 board runtime               NOT EXECUTED
```

The pre-hardware CI verification built the producer with warnings-as-errors and
ran the real producer-to-frozen-merger round trip. That proves format, identity
binding, namespace separation, and counting rules only. It does not prove queue
depth, timeout reachability, unmap, `D_issue`, or `D_commit` on hardware.

## Rule

Do not promote a board-negative or memory-safety claim from these controls.
The next load-bearing transition requires real DWC2 runtime evidence, bounded by
the exact observer/producer epoch that generated it.
