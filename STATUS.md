# Status snapshot — 2026-09-08

```text
SOURCE PATH / TEARDOWN ORDER       SOURCE-PROVEN
CURRENT REPOSITORY BASELINE        INCOMPLETE / RE-IMPORT REQUIRED
PRE-RUNTIME TOOLCHAIN              HISTORICALLY VERIFIED, NOT REPRODUCIBLE FROM CURRENT TREE
R1A REAL DWC2 RUNTIME              NOT EXECUTED
REAL UNMAP IN TESTED ATTEMPT       NOT PROVEN
D_issue                            UNKNOWN
D_commit                           UNKNOWN
SECURITY BOUNDARY IMPACT           UNKNOWN
FINAL SEVERITY                     UNRESOLVED
```

The checked-in `baseline/` directory is currently a fragment, not a verified executable baseline. `baseline/SHA256SUMS` pins a larger canonical package than the files presently committed, and some committed files do not match those pinned bytes.

Repository readiness is therefore fail-closed behind:

```sh
./VERIFY-REPOSITORY.sh
```

A PASS is required before the repository may again describe its checked-in pre-runtime tooling as a verified baseline.

Next actions, in order:

1. re-import the canonical baseline from a hash-verified archive; do not repair it by editing or reconstructing files from prose;
2. make `./VERIFY-REPOSITORY.sh` pass from a clean checkout;
3. import and pin the original tested `r1a-device/r1a_ffs_out_v2.c` before freezing the expanded epoch that contains `device_harness`;
4. only then import/reverify the expanded predicate set and proceed toward real DWC2 runtime qualification.
