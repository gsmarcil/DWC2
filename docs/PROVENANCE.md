# Provenance and epoch discipline

## Frozen baseline

The current repository baseline is the pre-runtime v4.2 provenance/freeze package.

Kernel observer baseline:

```text
pin: f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
observer: r3
ABI: v9 / header 112 / record 80
```

## Epoch rule

Any load-bearing change to observer, parser, gate, host harness, device harness, validator, witness tools, verdict generator, image or other artifact in the active `EPOCH_ARTIFACTS` set creates a new evidence epoch.

Negative evidence never carries forward across epochs.

A positive observation from an old/modified tool remains historically interesting but does not close the active R1 claim until reproduced in the active frozen epoch.

## Source of truth

The epoch keyset is defined by the active validator. The freezer hashes the exact runtime-resolved local modules plus required external artifacts. The host consumes the resulting epoch JSON directly.

Manual retyping of hash values is outside the frozen path.

An epoch artifact must also be repository-resolvable. A key such as `device_harness` is insufficient by itself: the exact tested source/binary provenance that produced the holder witness must be present and byte-verifiable from the canonical repository.

## Device harness boundary

The gadget-side FunctionFS holder source belongs under:

```text
r1a-device/r1a_ffs_out_v2.c
```

In the intended expanded predicate set, `device_harness` is load-bearing because the negative R1A result depends on the holder witness. The source therefore must be imported and pinned before that epoch is frozen.

The current v4.2 baseline preserved in this repository predates that expanded keyset and does not itself contain the canonical device-harness source. This mismatch is explicitly tracked as pending provenance work rather than silently treated as closed.

## Historical note

A more expanded predicate set (described during development as v3.2/v3.3) was discussed separately, including larger denominator/binding matrices and the device-harness epoch artifact. Its complete canonical artifact is not yet part of the current repository snapshot, so this repository does not claim those additional predicates as independently frozen here.

They should be promoted only after the original archive/source set is imported, hash-verified, and made self-contained under the repository policy.