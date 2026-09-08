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
8. only after PASS may `STATUS.md` promote the checked-in tree to a verified baseline.

## Completion state

```text
A. repository status corrected to INCOMPLETE                 COMPLETE
B. completeness gate committed                               COMPLETE
C. canonical baseline imported byte-for-byte                 COMPLETE
D. completeness gate PASS recorded                           COMPLETE
E. original r1a_ffs_out_v2.c placed at canonical path        COMPLETE
F. expanded predicate/epoch set imported and reverified      PENDING
G. real DWC2 runtime qualification                            PENDING
```

## Ordering rule

Do not combine these steps into one unreviewable repair commit. The intended order is:

```text
A. repository status corrected to INCOMPLETE
B. completeness gate committed
C. canonical baseline imported byte-for-byte
D. completeness gate PASS recorded
E. original r1a_ffs_out_v2.c imported and pinned
F. expanded predicate/epoch set imported and reverified
G. real DWC2 runtime qualification
```

The historical v4.2 audit/archive hashes identify the source archive, but
historical PASS text never substitutes for checking the bytes committed to
GitHub. The current import receipt records those checks.
