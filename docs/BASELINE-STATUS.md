# Baseline status — VERIFIED / CANONICAL v4.2 IMPORT

The checked-in `baseline/` directory is a byte-identical import of the complete
v4.2 pre-runtime package.

```text
archive                             R1A-EVIDENCE-PIPELINE-v4.2.tar.gz
archive size                        303278 bytes
archive SHA256                      d1d754076039aedf9756883f972a4f77014c043a6b7c1e0e14b3ebaae01eb563
pinned paths                        89
pinned paths present/matching       89/89
fresh-extract package VERIFY        PASS (runtime not executed)
repository completeness gate        PASS
```

The detailed import evidence is in
[`CANONICAL-IMPORT-RECEIPT-v4.2.md`](CANONICAL-IMPORT-RECEIPT-v4.2.md).

## Historical fragment — SUPERSEDED

Before canonical import, the repository carried only 9 of the 89 pinned paths;
6 matched and 3 did not. The mismatching fragment files were:

```text
baseline/pipeline/freeze_epoch.py
baseline/pipeline/r1_gate_v9_1.py
baseline/pipeline/usbmon_verify.py
```

That state was an assembly/provenance defect. It was closed by whole-package
replacement from the authenticated archive, never by editing those files or
regenerating `SHA256SUMS`.

## Repository gate

`./VERIFY-REPOSITORY.sh` checks:

1. every path in `baseline/SHA256SUMS` exists and hashes correctly;
2. every pinned path is tracked by Git;
3. no pinned path is excluded by `.gitignore`;
4. the validator/freezer exposes and resolves the local `EPOCH_ARTIFACTS` contract;
5. the canonical host and device harness source locations exist.

The gate must continue to fail closed on any future drift.

## Current evidentiary boundary

```text
pre-runtime v4.2 baseline            VERIFIED / REPRODUCIBLE
R1A runtime                          NOT EXECUTED
real UNMAP_DONE                      NOT PROVEN
R2 / D_issue                         UNKNOWN
R3 / D_commit                        UNKNOWN
security impact                      UNKNOWN
```

The canonical device source is present, but its exact built harness must still
be bound into the next expanded epoch. The historical v4.2 epoch is unchanged.
