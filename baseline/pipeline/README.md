# DWC2 R1A evidence pipeline v4.2

<!-- R1A_CONTRACT {"manifest_version":2,"gate_entry":"r1_gate_v9_1.py","gate_manifest_arg":"--manifest","gate_harness_arg":"absent","legacy_bridge_trusted":false,"epoch_artifacts":["image","observer_patch","dwc2_r1_v9","r1_gate_v9","r1_gate_v9_1","harness","manifest_validator","usbmon_verifier","holder_merger","verdict_generator"],"host_epoch_arg":"--epoch-json"} -->

This package closes the userspace evidence chain around the unchanged kernel
observer ABI v9. It does **not** change the DWC2 observer or `r1_gate_v9.py`.
The original v9 gate is retained byte-for-byte and imported by the binding
wrapper.

## Trust boundaries

The negative path is accepted only when all of these are independently tied:

```text
campaign-only usbmon capture
    -> usbmon_verify.py
holder event log (session_id + boot_id)
    -> holder_merge.py
merged manifest v2
    -> r1a_manifest.py
S2 trace + merged manifest + raw witnesses
    -> r1_gate_v9_1.py
bound gate JSON + the same manifest(s)
    -> r1_verdict.py
```

`r1_gate_v9_1.py` re-runs the manifest validator and re-derives both witnesses
from their raw files. The JSON produced by a bridge is not a trust boundary.

## Campaign window

The host captures three observer snapshots:

```text
S0  after re-arm preflight, before sensitivity
S1  after sensitivity, before campaign
S2  after campaign
```

Sensitivity is derived from S0/S1 header counters, never supplied by the
operator:

```text
Delta causal_sync_count == triggers_issued
Delta setup_<branch>     == triggers_issued
```

The candidate ratio `k` is measured from S0/S1 and the campaign must satisfy:

```text
Delta candidate_<branch>(S1->S2) == k * B_valid
```

`B_valid == 0` is rejected before this equality is considered.

Timeout records are classified only in the campaign slice:

```text
records[S1.count:S2.count]
```

A branch-matching timeout before S1 blocks a negative result as
`PRECAMPAIGN_TIMEOUT_PRESENT`; it is not silently attributed to the campaign.

## Wire witness

The usbmon capture is **campaign-only**. Start it after S1 and stop/wait before
S2. `usbmon_verify.py` replays Bulk OUT URB submit/completion events and samples
the active set at each exact raw control submit. It pairs campaign controls to
attempts by order and rejects missing/extra matching controls.

For `cfgn`, if the campaign control tuple is indistinguishable from the raw
restore tuple, the verifier refuses the run. Use a distinguishable trigger or
one destructive attempt per fresh enumeration epoch.

## Holder witness

The device-side event log is JSONL. Campaign entries must look like:

```json
{"event":"R1A_HOLDER","phase":"campaign",
 "session_id":"s001","boot_id":"...",
 "device_seq":17,"pending_reads":8,"utc":"2026-09-08T12:00:00Z"}
```

Pairing is by order, not by clock. The tool computes and stores the event-log
sha256 and rejects a different session/boot, missing events, extra campaign
teardowns, or depth below the frozen floor.

## Run order

```sh
python3 usbmon_verify.py --manifest session.json --usbmon batch.mon -o session+wire.json
python3 holder_merge.py --manifest session+wire.json --event-log dev-events.jsonl --floor 1 -o session+both.json
python3 r1a_manifest.py session+both.json
python3 r1_gate_v9_1.py --mode cfg0 --min-candidates 50 --manifest session+both.json --json snaps/S2.bin > gate.json
python3 r1_verdict.py --gate gate.json --manifest session+both.json --out verdict.md
```

## Tests without hardware

```sh
python3 witness_selftest.py
python3 pipeline_selftest.py
```

The pipeline selftest runs a clean synthetic session, then separately mutates a
capture, holder session, S2 trace, and manifest and requires the chain to stop
at the expected layer.

## Epoch freeze

The frozen campaign path does not type sha256 values into the host command.
Create the epoch block from actual files:

```sh
python3 freeze_epoch.py --epoch-id E \
  --image /path/to/Image \
  --observer-patch /path/to/observer.patch \
  --harness ../host/r1a_host \
  -o epoch.json
```

`EPOCH_ARTIFACTS` in `r1a_manifest.py` is the only artifact-key authority.
`r1_gate_v9_1.py` exports the exact local paths Python resolved via
`module.__file__`; `freeze_epoch.py` hashes those files and dynamically turns
the remaining epoch keys into required external path arguments. Missing
externals fail closed.

The host consumes the resulting block directly with `--epoch-json`; mixing it
with hand-entered epoch/hash flags is refused.

## Evidence boundary

This package can establish R1A reachability/absence semantics. It does not turn
an R1 result into R2 or R3 evidence. `UNMAP_DONE`, post-unmap DMA attempt, and
memory-side commit remain separate claims.
