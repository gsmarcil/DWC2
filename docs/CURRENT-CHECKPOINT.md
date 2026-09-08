# Current repository checkpoint

```text
repository baseline     VERIFIED / CANONICAL v4.2
baseline SHA manifest   89/89 PRESENT AND MATCHING
validator source        PRESENT
host canonical source   PRESENT
device legacy source    PRESENT / INCOMPATIBLE WITH HOLDER MERGER
baseline sub-gate       PASS
holder campaign gate    BLOCKED / EXPECTED EXIT 1
runtime R1A             NOT EXECUTED
```

The prior incomplete checkpoint is superseded by the canonical archive import.
Future baseline drift must be repaired only from the same authenticated archive,
never by editing pinned files or regenerating the manifest.

The campaign gate is blocked for a separate reason: no checked-in device source
can emit the active holder-event schema. See `HOLDER-PRODUCER-CONTRACT.md`.
