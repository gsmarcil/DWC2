# R1A device harness

This directory is the canonical repository location for the gadget-side R1A harness.

## Required source

The load-bearing device-side source is:

```text
r1a_ffs_out_v2.c
```

It is responsible for the FunctionFS Bulk-OUT holder witness used to establish that a gadget-side request remains queued during the host-triggered teardown attempt.

For the expanded predicate/epoch definition that includes `device_harness`, this source is an **epoch artifact**. A negative campaign therefore depends on the exact source bytes that produced the device-side holder log.

## Current repository status

The exact canonical `r1a_ffs_out_v2.c` bytes are **not yet present in this repository snapshot**. They must not be reconstructed from prose or reimplemented from memory.

Before the next evidence epoch is frozen, the original source must be imported here and its SHA256 pinned by the epoch freezer/validator contract.

Until that import is complete:

```text
device_harness source in repository    NOT PRESENT
future expanded epoch self-contained   NOT YET
existing v4.2 baseline                 unchanged / historical pre-runtime baseline
```

## Holder witness contract

The device harness is distinct from the host `usbmon` witness:

- `usbmon` establishes the host-side outstanding-URB condition;
- the device harness establishes the gadget-side queued-request/holder condition.

Neither witness substitutes for the other.

The imported source must remain tied to the event-log format consumed by `holder_merge.py`, including the session/boot binding required by the active manifest contract.

## Rule

Do not create a placeholder implementation and call it canonical. Import the original tested source, verify it byte-for-byte, then make the resulting hash part of the new epoch.