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

Any load-bearing change to observer, parser, gate, harness, validator, witness tools, verdict generator, image or other artifact in the frozen `EPOCH_ARTIFACTS` set creates a new evidence epoch.

Negative evidence never carries forward across epochs.

A positive observation from an old/modified tool remains historically interesting but does not close the active R1 claim until reproduced in the active frozen epoch.

## Source of truth

The epoch keyset is defined by the validator. The freezer hashes the exact Python modules resolved by the runtime gate via `module.__file__`, plus required external artifacts. The host consumes the resulting epoch JSON directly.

Manual retyping of hash values is outside the frozen path.

## Historical note

A more expanded predicate set (described during development as v3.2/v3.3) was discussed separately, including larger denominator/binding matrices. Its complete artifact was not part of the current repository snapshot, so this repository does not claim those additional predicates as independently frozen here. They should be imported only after their archive is available and reverified.
