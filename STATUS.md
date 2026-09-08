# Status snapshot — 2026-09-08

```text
SOURCE PATH / TEARDOWN ORDER       SOURCE-PROVEN
CURRENT REPOSITORY BASELINE        VERIFIED / CANONICAL v4.2 IMPORT
PRE-RUNTIME TOOLCHAIN              REPRODUCIBLE / VERIFIED (RUNTIME NOT EXECUTED)
R1A REAL DWC2 RUNTIME              NOT EXECUTED
REAL UNMAP IN TESTED ATTEMPT       NOT PROVEN
D_issue                            UNKNOWN
D_commit                           UNKNOWN
SECURITY BOUNDARY IMPACT           UNKNOWN
FINAL SEVERITY                     UNRESOLVED
```

The checked-in `baseline/` directory was restored byte-for-byte from the
independently authenticated `R1A-EVIDENCE-PIPELINE-v4.2.tar.gz` archive:

```text
archive size     303278 bytes
archive SHA256   d1d754076039aedf9756883f972a4f77014c043a6b7c1e0e14b3ebaae01eb563
pinned paths     89/89 matching and tracked
```

The fragment audit and closure evidence are recorded in
[`docs/BASELINE-STATUS.md`](docs/BASELINE-STATUS.md) and
[`docs/CANONICAL-IMPORT-RECEIPT-v4.2.md`](docs/CANONICAL-IMPORT-RECEIPT-v4.2.md).

Repository readiness is therefore fail-closed behind:

```sh
./VERIFY-REPOSITORY.sh
```

The canonical import passes this gate. Runtime was not executed by the import.

Next actions, in order:

1. keep `./VERIFY-REPOSITORY.sh` passing from clean checkouts;
2. bind the imported `r1a-device/r1a_ffs_out_v2.c` source and its built harness into the next expanded epoch before accepting negative runtime evidence;
3. import/reverify the expanded predicate set;
4. proceed toward real DWC2 runtime qualification.
