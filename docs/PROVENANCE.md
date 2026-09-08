# Provenance and epoch discipline

## Baseline state

The GitHub `baseline/` directory is a byte-identical import of the complete v4.2
pre-runtime package. The independently supplied archive identity is:

```text
d1d754076039aedf9756883f972a4f77014c043a6b7c1e0e14b3ebaae01eb563  R1A-EVIDENCE-PIPELINE-v4.2.tar.gz
size: 303278 bytes
```

The archive's own 89-path `SHA256SUMS`, fresh-extract `VERIFY.sh`, and the
repository completeness gate all pass. See
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

A clean-checkout PASS remains required to retain the `VERIFIED` state.

## Epoch rule

Any load-bearing change to observer, parser, gate, host harness, device harness, validator, witness tools, verdict generator, image or other artifact in the active `EPOCH_ARTIFACTS` set creates a new evidence epoch.

Negative evidence never carries forward across epochs.

A positive observation from an old/modified tool remains historically interesting but does not close the active R1 claim until reproduced in the active frozen epoch.

## Source of truth

The epoch keyset is defined by the active validator. The freezer hashes the exact runtime-resolved local modules plus required external artifacts. The host consumes the resulting epoch JSON directly.

Manual retyping of hash values is outside the frozen path.

An epoch artifact must also be repository-resolvable. A key such as `device_harness` is insufficient by itself: the exact tested source/binary provenance that produced the holder witness must be present and byte-verifiable from the canonical repository.

The repository completeness gate first verifies the imported baseline bytes against `baseline/SHA256SUMS`, then requires the validator/freezer local epoch contract to resolve from checked-in files. Missing canonical sources are a hard failure, not an invitation to reconstruct them from documentation.

## Device harness boundary

The gadget-side FunctionFS holder source belongs under:

```text
r1a-device/r1a_ffs_out_v2.c
```

In the intended expanded predicate set, `device_harness` is load-bearing because
the negative R1A result depends on the holder witness. The source is now imported
at the canonical path, but it still must be pinned with the built harness and
other external artifacts when the expanded epoch is frozen.

The historical v4.2 package predates that expanded keyset and does not itself
contain the canonical device-harness source. The separate source import does not
rewrite the historical v4.2 epoch.

## Historical note

A more expanded predicate set (described during development as v3.2/v3.3) was discussed separately, including larger denominator/binding matrices and the device-harness epoch artifact. Its complete canonical artifact is not yet part of the current repository snapshot, so this repository does not claim those additional predicates as independently frozen here.

They should be promoted only after the original archive/source set is imported, hash-verified, and made self-contained under the repository policy.
