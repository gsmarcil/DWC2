# Baseline import blockers — SUPERSEDED / CLOSED

The former assembly blockers were closed by importing the authenticated v4.2
archive as one byte-identical unit.

```text
missing/mismatching baseline paths    CLOSED — 89/89 match
validator/freezer resolution           CLOSED — PASS
pinned log ignore conflict             CLOSED — no pinned path ignored
canonical host source location         CLOSED — present
legacy device source location          CLOSED — preserved
baseline integrity sub-gate            CLOSED — PASS
```

Closure evidence is retained in
[`CANONICAL-IMPORT-RECEIPT-v4.2.md`](CANONICAL-IMPORT-RECEIPT-v4.2.md).

The compatible holder-event producer remains missing. This is a campaign
readiness blocker, not a baseline-import blocker: the overall repository gate
fails closed while the authenticated v4.2 baseline remains verified. It does
not rewrite historical v4.2.
