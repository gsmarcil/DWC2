# Holder producer contract — G1 CLOSED

## Closure gate

```text
CLAIM            The checked-in device source can produce the holder witness
                 consumed by the active v4.2 holder_merger.
SUCCESS ARTIFACT verify_holder_contract.py exits 0 and reports
                 HOLDER_PRODUCER_CONTRACT: PASS, and the built producer's real
                 output survives the repository guard and frozen merger.
FASTEST PATH     baseline/pipeline/holder_merge.py ->
                 r1a-device/r1a_ffs_out_v2.c
STOP CONDITION   Any required interface/sentinel/field is absent, or a
                 discriminating control/round-trip fails closed.
```

G1 is closed at the pre-runtime layer. The canonical producer now emits the
holder JSONL contract consumed by the frozen `holder_merge.py`, while the exact
pre-holder source remains preserved under `r1a-device/legacy/` for a permanent
negative control.

This closure is **not runtime evidence**. It proves that the producer can be
built and that its record format, namespace, identity binding, counting rule,
and fail-closed controls are compatible with the frozen evidence pipeline.

## Consumer-to-producer matrix

| Merger requirement | Consumer | Canonical producer |
|---|---:|---:|
| `--event-log` input/output path | present | present |
| `event: R1A_HOLDER` | required | present |
| `phase: campaign` | required | present via explicit phase marker |
| `pending_reads` | required | present / lower-bound semantics |
| `session_id` | required | present / required |
| `boot_id` | required | present / kernel-derived |
| `device_seq` | required | present / monotonic |

The preserved pre-holder source is:

```text
r1a-device/legacy/r1a_ffs_out_v2.c.pre-holder
SHA256 83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d6116958f126118e
```

It remains intentionally incompatible and is checked as such. The canonical
path is no longer allowed to inherit that legacy negative expectation.

## Counting semantics

For campaign records, `pending_reads` is stamped with:

```text
eshutdown_kills_at_or_before_cutoff_excluding_sync_submit_failures
```

The count is deliberately a lower bound. It includes only requests evidenced by
`-ESHUTDOWN` completion and assigned to submissions at or before the teardown
episode cutoff. Unresolved reads, post-cutoff kills, and immediate/prequeue
submission failures are reported separately and cannot raise the holder floor.

A teardown episode may open on the FUNCTIONFS disable indication or the first
qualifying `-ESHUTDOWN`, avoiding dependence on userspace observing a DISABLE
event that can be purged or overtaken by teardown/completion processing.

## Executable controls

```sh
python3 verify_holder_contract.py
python3 verify_holder_contract_selftest.py
python3 holder_log_guard_selftest.py
python3 holder_roundtrip.py
./VERIFY-REPOSITORY.sh
```

The verified pre-hardware run produced:

```text
HOLDER_PRODUCER_CONTRACT: PASS
HOLDER_CONTRACT_SELFTEST: PASS (2 positive, 10 fail-closed controls)
HOLDER LOG GUARD SELFTEST: 15/15 PASS (1 positive, 14 fail-closed)
HOLDER ROUND-TRIP: 18/18 PASS
REPOSITORY_BASELINE: PASS
HOLDER_CAMPAIGN_READINESS: PASS
REPOSITORY_GATE: PASS
```

The round-trip builds `r1a-device/r1a_ffs_out_v2.c` with warnings as errors and
feeds the emitter's output through the repository guard, the frozen holder
merger, and the frozen manifest validator. Synthetic self-test records live
outside the campaign namespace and cannot merge as campaign evidence.

## Evidence ceiling after G1

```text
G1 / producer compatibility          PRE-RUNTIME PROVEN
real DWC2 holder depth               NOT PROVEN
R1A timeout/reachability             NOT EXECUTED
same-request UNMAP_DONE              NOT PROVEN
D_issue                              UNKNOWN
D_commit                             UNKNOWN
security-boundary impact             UNKNOWN
```

The next evidence promotion is hardware-bound. No source or fixture result in
this closure may be rewritten as a board result.
