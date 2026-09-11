# Repository completeness gate — superseded red-state specification

**This file no longer describes the current gate.** It specified the expected
output while the compatible holder producer was still missing. That condition
is closed: the canonical producer is imported and the gate exits 0. For the
live verdict see `GATE-STATE.md`, which is machine-checked against what
`VERIFY-REPOSITORY.sh` actually computes.

The block below is retained as the historical acceptance criterion for the red
state, and as the specification the checker was written against. It is kept out
of the machine-checked declaration set deliberately, because it is a record of a
past expectation rather than a claim about today.

With the canonical v4.2 baseline intact but the compatible holder producer
missing, `./VERIFY-REPOSITORY.sh` was required to exit 1 and report:

```text
baseline_manifest_present          PASS
baseline_sha256_complete           PASS
baseline_pins_tracked              PASS
baseline_pins_not_ignored          PASS
epoch_validator_present            PASS
epoch_freezer_present              PASS
epoch_keyset_parse                 PASS
epoch_local_resolution             PASS
host_source                        PASS
device_source                      PASS
holder_producer_contract           FAIL
REPOSITORY_BASELINE: PASS
HOLDER_CAMPAIGN_READINESS: BLOCKED / PRODUCER INCOMPATIBLE
REPOSITORY_GATE: FAIL
```

The checker must identify all current producer gaps: `--event-log`,
`event:R1A_HOLDER`, `phase:campaign`, `pending_reads`, `session_id`, `boot_id`,
and `device_seq`. A baseline check failure is a completeness regression; this
campaign-readiness failure is instead closed only by importing the original
compatible producer and binding its exact built artifact.
