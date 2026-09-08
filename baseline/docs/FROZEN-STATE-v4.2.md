# DWC2 R1A — unified pre-runtime freeze v4.2

Date: 2026-09-08
Kernel pin: `torvalds/linux@f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8`

## Meaning of v4.2

v4.2 is a provenance/freeze revision over the v4.1 measurement predicates.
It does not intentionally change the DWC2 observer ABI v9, the frozen
`r1_gate_v9.py`, the R1 predicate, the usbmon/holder witness semantics, or the
S0/S1/S2 denominator rule.

It closes one remaining provenance gap: the epoch is now generated from the
files that the runtime path actually loads, and the host consumes that epoch
block directly. No operator retypes sha256 values in the frozen path.

```text
r1a_manifest.py::EPOCH_ARTIFACTS       artifact-key authority
                 |
r1_gate_v9_1.py runtime module.__file__ paths
                 |
        freeze_epoch.py
                 |
              epoch.json
                 |
        r1a_host --epoch-json
                 |
             manifest v2
```

The freezer rejects a new sibling module import that is not epoch-pinned,
missing external artifacts, modules resolved outside the package, unsafe epoch
IDs, and drift between the gate runtime map and the validator keyset.

The host rejects mixing `--epoch-json` with manual epoch/hash flags, duplicate
plain-string epoch keys, malformed hashes, and a harness digest that does not
match `/proc/self/exe`.

Because `r1_gate_v9_1.py`, `r1a_host`, and the packaging/provenance tools changed,
v4.2 is a new evidence epoch. Negative counts from v4.1 or any other epoch do
not carry forward.

## Runtime boundary

```text
R1A runtime             NOT EXECUTED
R2 / D_issue            UNKNOWN
R3 / D_commit           UNKNOWN
security impact         UNKNOWN
```

A pre-runtime PASS proves tooling/evidence plumbing only.
