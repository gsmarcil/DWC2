# R1A host harness

This directory is the canonical repository location for the host-side R1A harness used by the next unified evidence epoch.

The historical/frozen v4.2 host source was promoted here byte-for-byte from the
canonical frozen artifact. It matches `baseline/host/r1a_host.c` and is anchored
by `baseline/SHA256SUMS`:

```text
90dc62f6647212a4e17b34517b33da33ae04cd670fc3d886d4238f5c78ab46ef
```

The intended host and device harnesses are peers:

```text
r1a-host/    host usbfs control/Bulk-OUT harness
r1a-device/  legacy gadget source; compatible holder producer still missing
```

Both become load-bearing when named by the active `EPOCH_ARTIFACTS` contract.
The current device file is not contract-compatible and must not be promoted by
path presence alone. Neither source may be reconstructed from prose or silently
replaced by a functionally similar implementation.
