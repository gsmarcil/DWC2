# R1A device source — legacy/incompatible producer

This directory is the canonical repository location for the gadget-side R1A harness.

## Required source

The preserved device-side source is:

```text
r1a_ffs_out_v2.c
```

It implements the FunctionFS Bulk-OUT workload and writes a one-shot summary via
`--artifact`. It does **not** implement the event-log witness consumed by the
active `baseline/pipeline/holder_merge.py`.

For an expanded predicate/epoch definition that includes `device_harness`, the
actual compatible producer becomes an epoch artifact. This legacy source cannot
fill that role merely because it occupies the canonical path.

## Current repository status

The source is present as `r1a_ffs_out_v2.c`, copied byte-for-byte from the
pre-existing uploaded source artifact. Its SHA256 is:

```text
83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d6116958f126118e
```

The hash records identity, not capability. Before the next evidence epoch is
frozen, the original producer matching the merger contract and its exact built
harness must be imported and pinned.

Until expanded-epoch binding is complete:

```text
legacy device source in repository     PRESENT / SHA256 RECORDED
compatible holder producer             MISSING
future expanded epoch self-contained   NOT YET
existing v4.2 baseline                 VERIFIED / HISTORICAL PRE-RUNTIME EPOCH UNCHANGED
```

## Holder witness contract

The device harness is distinct from the host `usbmon` witness:

- `usbmon` establishes the host-side outstanding-URB condition;
- a compatible device producer would establish the gadget-side
  queued-request/holder condition.

Neither witness substitutes for the other.

The current source has no `--event-log` and emits none of
`event:R1A_HOLDER`, `phase:campaign`, `pending_reads`, `session_id`, `boot_id`,
or `device_seq`. `verify_holder_contract.py` therefore rejects it while
`holder_merger` is active.

## Rule

Do not create a placeholder implementation or adapt the incompatible v3.3
format and call it canonical. Import the original matching source, verify it
byte-for-byte, prove its event output round-trips through `holder_merge.py`, then
make the source/binary identities part of the new epoch.
