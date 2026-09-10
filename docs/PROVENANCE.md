# Provenance and epoch discipline

## Baseline state

The GitHub `baseline/` directory is a byte-identical import of the complete v4.2
pre-runtime package. The independently supplied archive identity is:

```text
d1d754076039aedf9756883f972a4f77014c043a6b7c1e0e14b3ebaae01eb563  R1A-EVIDENCE-PIPELINE-v4.2.tar.gz
size: 303278 bytes
```

The archive's own 89-path `SHA256SUMS`, fresh-extract `VERIFY.sh`, and the
baseline-integrity sub-gate all pass. See
[`CANONICAL-IMPORT-RECEIPT-v4.2.md`](CANONICAL-IMPORT-RECEIPT-v4.2.md).

Kernel observer lineage:

```text
pin: f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
observer: r3
ABI: v9 / header 112 / record 80
```

Repository completeness is gated by:

```sh
./VERIFY-REPOSITORY.sh
```

`REPOSITORY_BASELINE: PASS` remains required to retain the baseline's
`VERIFIED` state. The overall repository gate additionally checks the current
source-foundation and holder-producer contracts.

## Epoch rule

Any load-bearing change to observer, parser, gate, host harness, device harness, validator, witness tools, verdict generator, image or other artifact in the active `EPOCH_ARTIFACTS` set creates a new evidence epoch.

Negative evidence never carries forward across epochs.

A positive observation from an old/modified tool remains historically interesting but does not close the active R1 claim until reproduced in the active frozen epoch.

## Source of truth

The epoch keyset is defined by the active validator. The freezer hashes the exact runtime-resolved local modules plus required external artifacts. The host consumes the resulting epoch JSON directly.

Manual retyping of hash values is outside the frozen path.

An epoch artifact must also be repository-resolvable. A key such as
`device_harness` is insufficient by itself: the exact tested source/binary
provenance that produced the holder witness must be present, byte-verifiable,
and contract-compatible with the active `holder_merger`.

The repository gate first verifies the imported baseline bytes against
`baseline/SHA256SUMS`, then resolves the validator/freezer contract, checks the
canonical POST-UNMAP source foundation, and finally checks that an active
`holder_merger` has a structurally compatible producer. Missing or incompatible
canonical sources are a hard failure, not an invitation to reconstruct them
from documentation.

## POST-UNMAP source-foundation import

The PRIMARY-A/PRIMARY-B source derivation was originally developed on
`post-unmap-dma-g0`. That branch diverged from `main`, so it is **not** merged as
a whole. Instead, the exact branch-head blobs needed to make the canonical
checkout self-contained are imported into `main` from:

```text
source branch: post-unmap-dma-g0
source head:   47dec94ca77e524cf3c6bb1990062d017f99330c
```

Exact imported Git blobs:

```text
docs/POST-UNMAP-DMA-G0.md               c690a68065344f4c8adb7c85902b1377316a1371
docs/POST-UNMAP-DMA-L2.md               dbaaa287c7c02bc98b0be9ec238ac8f57f993dd1
docs/POST-UNMAP-DMA-G2.5.md             035a1d3bcfb09a60f1690ab4e0a66071e8690704
docs/POST-UNMAP-DMA-OBJECT-GATE.md      511c5d333362de2fe4133d6f51fd383bfa7b04bf
docs/POST-UNMAP-DMA-G2.5-CANDIDATES.md  e935d02aeb9012ef91c6cc5d5dc24d8dce9136f9
tools/dma_api_debug_gate.py              fb17ed9f62c7d2559e139727e0f88227331ece4f
tools/capture_ep_dequeue_object_gate.py  5a287839d292fcc7c456e0cbb557902e2fa897cf
```

The two tool blobs are imported with the ledgers because those ledgers invoke
them directly; importing documentation while leaving its executable dependency
on another branch would reproduce the same structural defect.

The imported source ledgers preserve their own frozen source-stage statements.
For **current execution state**, later canonical documents on `main` control:
`EVIDENCE-LADDER.md`, `RUNTIME-RUNBOOK.md`, `PENDING.md`, current hardware docs,
and `INJURED-SURFACE-TABLE.md`. This precedence rule does not alter the imported
source derivations; it prevents old source-stage status text from overriding a
later runtime specification.

The historical branch remains provenance only after this import. Current
campaigns must resolve `K_sw`, `K_hw`, `PRIMARY-A`, `PRIMARY-B`, G2.5, and their
support tools from `main` without checking out that branch.

## Device harness boundary

The gadget-side FunctionFS holder source belongs under:

```text
r1a-device/r1a_ffs_out_v2.c
```

In the intended expanded predicate set, `device_harness` is load-bearing because
the negative R1A result depends on the holder witness. The historical v4.2
package predates that expanded keyset and does not itself contain the canonical
device-harness source.

The historical fact is frozen explicitly as metadata **outside** `baseline/`:

```text
v4.2:
    device_harness = ABSENT
```

This statement records absence; it does not add an artifact to v4.2. Any newly
authored device harness, producer, observer helper, or runtime witness belongs to
a new evidence epoch with its own bytes and identity. New bytes must never be
attributed retroactively to an earlier evidence epoch.

## Historical note

A more expanded predicate set (described during development as v3.2/v3.3) was discussed separately, including larger denominator/binding matrices and the device-harness epoch artifact. Its complete canonical artifact is not retroactively attributed to the historical v4.2 package.

Current expanded work is admitted only through the current repository contracts and exact artifacts carried on `main`.
