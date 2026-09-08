# Repository completeness gate — expected current result

With the canonical v4.2 baseline intact but the compatible holder producer
missing, `./VERIFY-REPOSITORY.sh` must exit 1 and report:

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
