# Gate state

The canonical v4.2 baseline sub-gate is green. The overall repository gate is
intentionally red because `holder_merger` is active while the preserved device
source cannot produce its required JSONL event contract.

```text
REPOSITORY_BASELINE: PASS
HOLDER_CAMPAIGN_READINESS: BLOCKED / PRODUCER INCOMPATIBLE
REPOSITORY_GATE: FAIL
```

This red state blocks evidence-bearing holder campaigns; it is not a request to
re-import or edit the authenticated `baseline/` bytes.
