# Canonical v4.2 import receipt

Date: 2026-09-08 UTC

## Imported archive

```text
name      R1A-EVIDENCE-PIPELINE-v4.2.tar.gz
size      303278 bytes
SHA256    d1d754076039aedf9756883f972a4f77014c043a6b7c1e0e14b3ebaae01eb563
```

The checksum came from the separately retained
`R1A-EVIDENCE-PIPELINE-v4.2.sha256.txt` companion artifact. The first three
previously staged Base64 chunks also matched the same archive byte-for-byte.
The entire transport was regenerated from the authenticated archive as 21
ordered Base64 parts and reassembled to byte identity before import.

## Import gates

```text
external archive SHA256                         PASS
archive member path-safety check                PASS
archive SHA256SUMS identity vs baseline         PASS
fresh-extract internal SHA256SUMS               89/89 PASS
fresh-extract ./VERIFY.sh                       PASS (runtime not executed)
baseline bytes after import                     89/89 PASS
canonical host source byte identity             PASS
legacy device source copy identity              PASS
./VERIFY-REPOSITORY.sh at import commit         REPOSITORY_BASELINE: PASS
```

The host source was imported from the canonical v4.2 archive. The device source
was copied byte-for-byte from the pre-existing uploaded root artifact (retained
in Git history); it is not retroactively part of the historical v4.2 epoch.

A post-import capability audit established that this device revision is not the
holder-event producer consumed by `baseline/pipeline/holder_merge.py`. The
current overall repository gate therefore exits nonzero while retaining
`REPOSITORY_BASELINE: PASS`. See
[`HOLDER-PRODUCER-CONTRACT.md`](HOLDER-PRODUCER-CONTRACT.md).

## Runtime boundary

```text
R1A runtime             NOT EXECUTED
real UNMAP_DONE         NOT PROVEN
R2 / D_issue            UNKNOWN
R3 / D_commit           UNKNOWN
security impact         UNKNOWN
```

This receipt closes repository assembly/provenance for the v4.2 baseline only.
