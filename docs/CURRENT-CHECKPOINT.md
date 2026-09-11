# Current repository checkpoint

## Machine-checked gate verdict

These four keys are compared against the computed verdict of
`VERIFY-REPOSITORY.sh` by `verify_status_sync.py` and fail closed on drift.

```text
REPOSITORY_BASELINE: PASS
SOURCE_FOUNDATION: PASS
HOLDER_CAMPAIGN_READINESS: PASS
REPOSITORY_GATE: PASS
```

## Component state

```text
repository baseline     VERIFIED / CANONICAL v4.2
baseline SHA manifest   89/89 PRESENT AND MATCHING
validator source        PRESENT
host canonical source   PRESENT
canonical device source PRESENT / EMITS HOLDER CONTRACT
legacy device source    PRESERVED / INTENTIONALLY INCOMPATIBLE
baseline sub-gate       PASS
holder campaign gate    PASS / PRE-RUNTIME ONLY
runtime R1A             NOT EXECUTED
```

The prior incomplete checkpoint is superseded by the canonical archive import.
Future baseline drift must be repaired only from the same authenticated archive,
never by editing pinned files or regenerating the manifest.

## Evidence ceiling

The campaign gate is green at the pre-runtime layer only. It proves the
canonical producer can be built and that its record format, namespace, identity
binding, counting rule, and fail-closed controls are compatible with the frozen
evidence pipeline. See `HOLDER-PRODUCER-CONTRACT.md`.

No source, fixture, or round-trip result behind this green gate may be restated
as a board result. Runtime R1A remains unexecuted, and every rung above it
(`D_issue`, `D_commit`, security-boundary impact) remains UNKNOWN. The next
evidence promotion is hardware-bound.

## History

This checkpoint previously recorded `holder campaign gate BLOCKED / EXPECTED
EXIT 1` and named the legacy device source as the blocker. That description
outlived its condition: the compatible producer was imported, the legacy source
moved to `r1a-device/legacy/` as a negative control, and the gate went green.
