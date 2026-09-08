# Canonical baseline re-import procedure

The historical fragment has been replaced by the complete canonical v4.2
archive. This procedure remains authoritative for verifying the current import
or recovering from future drift; individual pinned files must not be edited until
hashes happen to pass.

## Required procedure

1. obtain the original frozen archive whose identity is independently known;
2. verify the archive SHA256 before extraction;
3. extract it into a clean temporary directory;
4. verify the archive's own `SHA256SUMS`/`VERIFY.sh` there;
5. replace the repository `baseline/` from those canonical bytes as one import operation;
6. do not normalize, reformat, regenerate, or hand-copy load-bearing files during import;
7. run `./VERIFY-REPOSITORY.sh` from a clean checkout;
8. only after `REPOSITORY_BASELINE: PASS` may `STATUS.md` promote the
   checked-in baseline; overall campaign readiness may remain blocked by a
   repository-external producer contract.

## Completion state

```text
A. repository status corrected to INCOMPLETE                 COMPLETE
B. completeness gate committed                               COMPLETE
C. canonical baseline imported byte-for-byte                 COMPLETE
D. baseline integrity PASS recorded                          COMPLETE
E. legacy r1a_ffs_out_v2.c identity preserved                COMPLETE
E2. compatible holder-event producer imported                BLOCKED / MISSING
F. expanded predicate/epoch set imported and reverified      PENDING
G. real DWC2 runtime qualification                            PENDING
```

## Ordering rule

Do not combine these steps into one unreviewable repair commit. The intended order is:

```text
A. repository status corrected to INCOMPLETE
B. completeness gate committed
C. canonical baseline imported byte-for-byte
D. baseline integrity PASS recorded
E. compatible r1a_ffs_out_v2.c imported, exercised and pinned
F. expanded predicate/epoch set imported and reverified
G. real DWC2 runtime qualification
```

The historical v4.2 audit/archive hashes identify the source archive, but
historical PASS text never substitutes for checking the bytes committed to
GitHub. The current import receipt records those checks.
