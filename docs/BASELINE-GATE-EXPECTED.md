# Repository completeness gate — expected current result

After canonical v4.2 import, `./VERIFY-REPOSITORY.sh` must exit zero and report:

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
REPOSITORY_BASELINE: PASS
```

Any deviation is a new completeness regression. Do not weaken the gate; restore
the affected bytes from authenticated canonical artifacts.
