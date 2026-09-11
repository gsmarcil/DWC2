# Canonical v4.2 Base64 transport manifest

This directory is the lossless transport encoding of the current
privacy-redacted publication derivative of `R1A-EVIDENCE-PIPELINE-v4.2.tar.gz`.

```text
encoding             RFC 4648 Base64, no line wrapping
part order           bytewise lexical order
regular part size    20000 encoded bytes except the final part
part count           20
final part size      18624 encoded bytes
encoded size         398624 bytes
decoded size         298967 bytes
archive SHA256       fbe578b28649fda589fa630495e84a855e4a8149eb921ca087c48d42cdd76ce4
```

The source archive identity and bounded privacy transformation are
recorded in `../PRIVACY-REDACTION-RECEIPT.txt`.

Reassemble and authenticate before extraction:

```sh
LC_ALL=C cat part-* | base64 -d > R1A-EVIDENCE-PIPELINE-v4.2.tar.gz
cp ../R1A-EVIDENCE-PIPELINE-v4.2.sha256.txt .
sha256sum -c R1A-EVIDENCE-PIPELINE-v4.2.sha256.txt
```

After the checksum passes, extract into a clean temporary directory and
run the package's own `sha256sum -c SHA256SUMS` and `./VERIFY.sh` gates.
