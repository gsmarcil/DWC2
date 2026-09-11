# Gate state

This file is the machine-checked declaration of the repository gate verdict.
`verify_status_sync.py` compares every key below against what
`VERIFY-REPOSITORY.sh` actually computes and fails closed on any disagreement,
in either direction. Do not edit these values by hand to express an intent;
they record a result.

```text
REPOSITORY_BASELINE: PASS
SOURCE_FOUNDATION: PASS
HOLDER_CAMPAIGN_READINESS: PASS
REPOSITORY_GATE: PASS
```

## What the green gate does and does not mean

The canonical v4.2 baseline sub-gate is green, and the holder producer contract
closed at the pre-runtime layer: the canonical producer at
`r1a-device/r1a_ffs_out_v2.c` emits the JSONL event contract consumed by the
frozen `holder_merge.py`, and its output survives the repository guard, the
frozen merger, and the frozen manifest validator.

The gate being green authorises a pre-hardware campaign epoch. It is **not**
runtime evidence and promotes nothing on the evidence ladder:

```text
producer compatibility        PRE-RUNTIME PROVEN
real DWC2 holder depth        NOT PROVEN
R1A timeout/reachability      NOT EXECUTED
same-request UNMAP_DONE       NOT PROVEN
D_issue                       UNKNOWN
D_commit                      UNKNOWN
security-boundary impact      UNKNOWN
```

The preserved pre-holder source is retained as a permanent negative control and
remains intentionally incompatible with the holder merger. A green gate is never
a reason to alter authenticated `baseline/` bytes outside the repository policy.

## Executable controls

```sh
./VERIFY-REPOSITORY.sh
python3 verify_status_sync_selftest.py
```

`verify_status_sync.py` is not run by hand: the gate supplies it with the
verdict it computed, and running it standalone requires restating that verdict.
The selftest drives it over fixture trees and is the check to run when changing
the guard itself.

The guard rejects, in both directions:

```text
a declared key that disagrees with the computed verdict
a declaration file that omits a required key
a file declaring the same key twice with different values
a missing declaration file
a missing producer source
a producer digest printed under the wrong source path
a producer digest cited with no source path at all
a producer digest cited beside a same-named file in another directory
an incomplete verdict tuple
```

The same digest cited correctly still passes, including a path written relative
to the citing document's own directory, so the rejections above discriminate
rather than reject everything.

Two properties are load-bearing and are pinned by their own controls, because
losing either would invert the check while leaving it green:

```text
path matching is on segment boundaries, never substrings
the documents are measured against the evidence verdict, not the guard's own
```

The first matters because the canonical basename `r1a_ffs_out_v2.c` is a prefix
of the preserved `r1a_ffs_out_v2.c.pre-holder`. Under substring matching the
canonical digest printed under the legacy path finds its own basename inside the
legacy filename and passes, which is exactly the misattribution being hunted.

The second matters because a defect in the guard would otherwise flip the
verdict the documents are compared against and report every truthful document as
stale, burying the real cause.

`baseline/` is excluded from this status-document digest-attribution scan. It is
authenticated imported evidence governed separately by the baseline and
privacy-redaction rules in `REPOSITORY-POLICY.md`; this guard targets mutable
repository documentation. The exclusion is itself tested: the same text outside
that tree must still be caught.

## History

This file previously declared `HOLDER_CAMPAIGN_READINESS: BLOCKED / PRODUCER
INCOMPATIBLE` and `REPOSITORY_GATE: FAIL`. Those declarations outlived the
condition that produced them: the compatible producer was imported and the
executable gate went green, but nothing compared the declaration against the
computation, so the red state persisted silently. `verify_status_sync.py` now
closes that drift direction.
