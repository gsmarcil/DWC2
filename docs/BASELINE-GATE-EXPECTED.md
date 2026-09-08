# Repository completeness gate — expected current result

`VERIFY-REPOSITORY.sh` is intentionally expected to fail until the canonical baseline and harness sources are re-imported.

The current failure is evidence of repository incompleteness, not a tooling regression.

Expected blockers include at least:

- missing files pinned by `baseline/SHA256SUMS`;
- hash mismatches for committed files that were not imported byte-for-byte;
- missing `baseline/pipeline/r1a_manifest.py`;
- unresolved local epoch contract;
- missing canonical `r1a-host/r1a_host.c`;
- missing canonical `r1a-device/r1a_ffs_out_v2.c`.

Do not weaken the gate to make the current tree pass. Import canonical bytes instead.
