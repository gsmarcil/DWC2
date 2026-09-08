# Status snapshot — 2026-09-08

```text
SOURCE PATH / TEARDOWN ORDER       SOURCE-PROVEN
CURRENT REPOSITORY BASELINE        VERIFIED / CANONICAL v4.2 IMPORT
PRE-RUNTIME TOOLCHAIN              REPRODUCIBLE / VERIFIED (RUNTIME NOT EXECUTED)
HOLDER PRODUCER CONTRACT           BLOCKED / LEGACY SOURCE INCOMPATIBLE
OVERALL REPOSITORY GATE            FAIL-CLOSED (EXPECTED)
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

Repository and campaign readiness are fail-closed behind:

```sh
./VERIFY-REPOSITORY.sh
```

The baseline portion reports `REPOSITORY_BASELINE: PASS`. The overall gate now
exits 1 with `HOLDER_CAMPAIGN_READINESS: BLOCKED / PRODUCER INCOMPATIBLE` because
the active `holder_merger` consumes a JSONL schema that the preserved device
source cannot emit. Runtime was not executed by the import.

Next actions, in order:

1. obtain the original producer that emits the active holder JSONL contract;
2. require `verify_holder_contract.py` and the overall repository gate to PASS;
3. pin that source and its exact built harness in the next expanded epoch;
4. import/reverify the expanded predicate set;
5. proceed toward real DWC2 runtime qualification.
