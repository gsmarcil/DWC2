# Current baseline import blockers

This file records blockers that must be removed by canonical import, not by editing the fragment in place.

Current blockers include:

- `baseline/SHA256SUMS` references files that are absent from the repository;
- some files currently present under `baseline/` do not match the pinned hashes;
- `baseline/pipeline/r1a_manifest.py` is absent, so `EPOCH_ARTIFACTS` cannot currently be read from the canonical validator;
- the local epoch resolver therefore cannot close from the checked-in tree;
- `r1a-host/r1a_host.c` is not yet imported into its canonical repository location;
- `r1a-device/r1a_ffs_out_v2.c` is not yet imported into its canonical repository location;
- historical evidence logs pinned by the old manifest conflict with the current broad `*.log` ignore rule and must be handled explicitly during canonical import rather than silently omitted.

The remedy is the procedure in `docs/BASELINE-REIMPORT.md`.
