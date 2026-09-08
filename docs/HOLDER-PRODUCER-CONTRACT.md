# Holder producer contract — BLOCKED

## Closure gate

```text
CLAIM            The checked-in device source can produce the holder witness
                 consumed by the active v4.2 holder_merger.
SUCCESS ARTIFACT verify_holder_contract.py exits 0 and reports
                 HOLDER_PRODUCER_CONTRACT: PASS.
FASTEST PATH     baseline/pipeline/holder_merge.py ->
                 r1a-device/r1a_ffs_out_v2.c
STOP CONDITION   Any required interface, sentinel, or field is absent from the
                 producer's executable C string literals.
```

The claim is currently denied. `holder_merger` is present in the literal
`EPOCH_ARTIFACTS` keyset, but the preserved source at
`r1a-device/r1a_ffs_out_v2.c` only emits a one-shot `--artifact` summary.

## Consumer-to-producer matrix

| Merger requirement | Consumer | Current producer |
|---|---:|---:|
| `--event-log` input/output path | present | absent |
| `event: R1A_HOLDER` | required | absent |
| `phase: campaign` | required | absent |
| `pending_reads` | required | absent |
| `session_id` | required | absent |
| `boot_id` | required | absent |
| `device_seq` | required | absent |

The source SHA256
`83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d6116958f126118e`
is preserved as a legacy source identity only. It is not a compatible holder
producer and must not be pinned as `device_harness` in an expanded epoch.

The separately described v3.3-format revision is also not admissible: a single
`session_tag` record does not satisfy the v4.2 merger's per-event
`session_id`/`boot_id`, sentinel, phase, and sequence contract. It was therefore
not imported or adapted.

## Executable controls

```sh
python3 verify_holder_contract.py
python3 verify_holder_contract_selftest.py
./VERIFY-REPOSITORY.sh
```

The selftest contains one compatible producer fixture and fail-closed mutations
for every required token, inactive-keyset behavior, consumer drift, and the
current legacy source. A future structural PASS is only an admission gate: the
actual built producer must still generate JSONL that round-trips through
`holder_merge.py` with matching session/boot identity before runtime evidence is
accepted.

## Duplicate cleanup

The unpinned root copies `r1a_host.c`, `r1a_ffs_out_v2.c`, and
`r1a_manifest.py` were byte-identical duplicates and had no path consumers.
They were removed; their history remains recoverable from Git. Canonical paths
are now `r1a-host/`, `r1a-device/`, and the authenticated `baseline/` package.
