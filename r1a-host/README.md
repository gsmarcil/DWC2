# R1A host harness

This directory is the canonical repository location for the host-side R1A harness used by the next unified evidence epoch.

The historical/frozen v4.2 host source is anchored by `baseline/SHA256SUMS`; the exact source should be promoted here only by byte-verifiable import from the canonical frozen artifact or the newer independently verified package.

The host and device harnesses are peers:

```text
r1a-host/    host usbfs control/Bulk-OUT harness
r1a-device/  gadget FunctionFS holder harness
```

Both become load-bearing when named by the active `EPOCH_ARTIFACTS` contract. Neither may be reconstructed from prose or silently replaced by a functionally similar implementation.