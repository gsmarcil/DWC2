# Baseline status — INCOMPLETE / PENDING RE-IMPORT

> The checked-in `baseline/` directory is **not an executable frozen baseline**.
> It is an incomplete fragment whose own checksum manifest describes a larger
> package than the repository currently carries. Nothing in `baseline/` may be
> used to anchor a new evidence epoch until the canonical package is restored
> whole and the repository completeness gate passes.

## Current fragment

The current `baseline/SHA256SUMS` pins 89 package paths. Repository review found:

```text
pinned paths                         89
pinned paths currently present        9
present and matching their pin        6
present but not matching their pin    3
```

The three present-but-mismatching files are:

```text
baseline/pipeline/freeze_epoch.py
baseline/pipeline/r1_gate_v9_1.py
baseline/pipeline/usbmon_verify.py
```

This is an assembly/provenance defect. The correct response is **not** to edit
those files until they happen to match a digest, and not to regenerate
`SHA256SUMS` from the fragment. Either action would manufacture a new
self-consistent snapshot that is not the previously verified archive.

## Why it cannot execute as a baseline

The fragment does not contain the complete package required by its own pin
list. In particular, load-bearing validator/test/harness files are missing.
The repository therefore cannot currently reproduce the historical clean-room
verification results from `main` alone.

Repository readiness is fail-closed behind:

```sh
./VERIFY-REPOSITORY.sh
```

That gate checks:

1. every path in `baseline/SHA256SUMS` exists and hashes correctly;
2. every pinned path is actually tracked by Git, not merely copied into a
   developer working tree;
3. no pinned path is excluded by the active `.gitignore` policy;
4. the checked-in validator/freezer can expose and resolve the active local
   `EPOCH_ARTIFACTS` contract;
5. the canonical host and device harness source locations exist.

The `.gitignore` conflict observed in the earlier fragment review has already
been corrected by explicit negations for the four pinned build logs. The gate
retains a mechanical check so that this cannot regress silently.

## Historical verification vs current-tree reproducibility

Earlier clean-room runs verified specific frozen artifacts. Those statements
remain historical evidence about the artifacts that were actually tested.
They do **not** mean this GitHub fragment is currently reproducible.

Current terminology:

```text
historically verified artifacts      RETAINED AS HISTORICAL EVIDENCE
checked-in baseline                   INCOMPLETE / RE-IMPORT REQUIRED
current-tree reproducibility          NOT ESTABLISHED
R1A runtime                           NOT EXECUTED
```

## Required order

```text
1. keep the fragment declared incomplete
2. restore baseline/ whole from a hash-verified canonical archive
3. ./VERIFY-REPOSITORY.sh must PASS from a clean checkout
4. import the original tested r1a-device/r1a_ffs_out_v2.c and pin it
5. freeze the expanded epoch/predicate set
6. only then proceed to real DWC2 runtime qualification
```

Step 2 is a **restore**, not a repair. Missing or mismatching epoch sources must
never be synthesized from documentation, prior chat text, or memory.
