# Status snapshot — 2026-09-10

```text
SOURCE PATH / TEARDOWN ORDER       SOURCE-PROVEN
CURRENT REPOSITORY BASELINE        VERIFIED / CANONICAL v4.2 IMPORT
PRE-RUNTIME TOOLCHAIN              REPRODUCIBLE / VERIFIED
HOLDER PRODUCER CONTRACT           PASS / G1 CLOSED PRE-RUNTIME
OVERALL REPOSITORY GATE            PASS
R1A REAL DWC2 RUNTIME              NOT EXECUTED
REAL UNMAP IN TESTED ATTEMPT       NOT PROVEN
D_issue                            UNKNOWN
D_commit                           UNKNOWN
SECURITY BOUNDARY IMPACT           UNKNOWN
FINAL SEVERITY                     UNRESOLVED
```

The checked-in `baseline/` directory remains the byte-identical canonical v4.2
import. G1 changes the next-campaign producer/tooling around that baseline; it
does not rewrite the authenticated baseline bytes.

Repository and campaign readiness are fail-closed behind:

```sh
./VERIFY-REPOSITORY.sh
```

The PREHW G1 verification built the canonical holder producer and exercised the
full producer/consumer contract with discriminating controls. Observed result:

```text
holder_producer_contract           PASS
holder_contract_selftest           PASS   2 positive, 10 fail-closed
holder_log_guard_selftest          PASS   15/15
holder_roundtrip                   PASS   18/18
REPOSITORY_BASELINE                PASS
SOURCE_FOUNDATION                  PASS
HOLDER_CAMPAIGN_READINESS          PASS
REPOSITORY_GATE                    PASS
```

The exact pre-holder source is retained under `r1a-device/legacy/` as a pinned
negative control rather than being confused with the canonical producer.

No runtime claim moved. G1 establishes only that the first hardware epoch will
not be blocked by a known producer/merger schema mismatch.

Next executable work, in order:

1. freeze the green pre-hardware code point as `EPOCH-PREHW-1` without pretending
   that the runtime epoch freezer can manufacture missing hardware artifacts;
2. prepare a separate measurement-only DWC2 instrumentation branch with stable
   request/map identity and `UNMAP_BEGIN`/`UNMAP_DONE` trace events;
3. prepare the temporal-sentinel gadget for a possible `D_commit` measurement;
4. build the affected-surface source matrix for maintained kernel lines and
   relevant gadget/DMA topologies;
5. when Pi Zero 2 W arrives, collect PI-FB1 + PI-FB2 before attempting R1A.
