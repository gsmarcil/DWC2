# Delivery comparison note

The user-supplied `r1a-harness-spec-v3.tar.gz` received in this chat has outer
SHA-256:

`b2776f7c8008941d36530c1733daca8a60a5f736c6146cffbd26e4bc291c2889`

Its internal integrity passes, but it contains only six specification/audit
files. Its `R1A-HARNESS-SPEC.md` is byte-identical to the previously shipped v4
host spec and still labels itself `Specification v1` with the obsolete top-level
trust-path diagram `manifest v1 -> manifest_to_p4.py -> r1_gate_v9.py`.

v4.1 corrects only that delivery/specification inconsistency and adds a unified
top-level verifier and duplicate identity gate. The audited measurement logic
remains the v4 logic.
