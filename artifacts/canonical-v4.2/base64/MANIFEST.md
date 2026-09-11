# Canonical v4.2 Base64 transport manifest

This directory is a lossless transport encoding of the independently identified
archive `R1A-EVIDENCE-PIPELINE-v4.2.tar.gz`.

```text
encoding             RFC 4648 Base64, no line wrapping
part order           part-00 through part-20, bytewise lexical order
regular part size    20000 encoded bytes (part-00 through part-19)
final part size      4372 encoded bytes (part-20)
encoded size         404372 bytes
decoded size         303278 bytes
archive SHA256       d1d754076039aedf9756883f972a4f77014c043a6b7c1e0e14b3ebaae01eb563
```

The independently supplied checksum is retained one directory above as
`R1A-EVIDENCE-PIPELINE-v4.2.sha256.txt`. The companion audit record is
`R1A-EVIDENCE-PIPELINE-v4.2-AUDIT.txt`.

Reassemble and authenticate before extraction:

```sh
LC_ALL=C cat part-* | base64 -d > R1A-EVIDENCE-PIPELINE-v4.2.tar.gz
cp ../R1A-EVIDENCE-PIPELINE-v4.2.sha256.txt .
sha256sum -c R1A-EVIDENCE-PIPELINE-v4.2.sha256.txt
```

After the external checksum passes, extract into a clean temporary directory and
run the package's own `sha256sum -c SHA256SUMS` and `./VERIFY.sh` gates.
