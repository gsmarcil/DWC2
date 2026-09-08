# r1a_host v4.2 provenance freeze

<!-- R1A_CONTRACT {"manifest_version":2,"gate_entry":"r1_gate_v9_1.py","gate_manifest_arg":"--manifest","gate_harness_arg":"absent","legacy_bridge_trusted":false,"epoch_artifacts":["image","observer_patch","dwc2_r1_v9","r1_gate_v9","r1_gate_v9_1","harness","manifest_validator","usbmon_verifier","holder_merger","verdict_generator"],"host_epoch_arg":"--epoch-json"} -->

Host-side generator for the R1A campaign. It uses Linux usbfs directly
(`USBDEVFS_CONTROL`, `SUBMITURB`, `REAPURBNDELAY`) so a raw teardown can reach
the gadget while Bulk OUT URBs remain outstanding.

## Measurement logic (unchanged from audited v4)

* Re-arm preflight remains two-arm payload-progress based.
* Sensitivity is no longer supplied with `--observed-cmd` or
  `--sync-owner-observed`. It is derived from authenticated S0/S1 dump headers.
* S0/S1/S2 must all be atomic and from one observer generation.
* Each attempt records USB bus/device/endpoint identity for post-hoc usbmon
  verification.
* The running harness hashes `/proc/self/exe`; `--sha-harness`, when supplied,
  is only an expectation and must match.
* usbmon is campaign-only: `--usbmon-start-cmd` runs after S1; the stop command
  must terminate/wait for the writer before S2 and hashing. Failure is fatal.
* The emitted manifest is version 2 and pins the v9.1 gate, usbmon verifier,
  holder merger and verdict generator in the epoch.

## Build / local tests

```sh
make
make check
```

The crosscheck enumerates both duplicated decision rules:

```text
re-arm verdict       560 rows
kernel denominator   768 rows
```

## Campaign skeleton

Freeze the epoch from the files that will actually run; do not retype hashes:

```sh
python3 ../pipeline/freeze_epoch.py \
  --epoch-id E \
  --image /path/to/deployed/Image \
  --observer-patch /path/to/observer.patch \
  --harness ./r1a_host \
  -o epoch.json
```

Then pass that file directly to the harness:

```sh
sudo ./r1a_host \
  --epoch-json epoch.json --session-id S --boot-id B \
  --vid 0x1d6b --pid 0x0104 --expect-ep 0x02 \
  --snapshot-cmd 'ssh target "cat /sys/kernel/debug/.../r1_dump" > %s' \
  --snapshot-dir ./snaps \
  --usbmon batch.mon --usbmon-bus 1 \
  --usbmon-start-cmd './start_usbmon.sh batch.mon' \
  --usbmon-stop-cmd './stop_usbmon_and_wait.sh' \
  --mode cfg0 --depth 8 --xfer-len 16384 --settle-ms 200 \
  --sens-triggers 20 --attempts 50 --restore-cfg 1 \
  --g-dma 1 --g-dma-desc 0 --abi-version 9 --abi-header 112 --abi-record 80 \
  --snapshot-atomic 1 --lost 0 --overlap-count 0 \
  --target-kernel K --target-udc U --target-gadget G \
  --log harness.log --manifest session.json
```

`--epoch-json` is authoritative. Mixing it with `--epoch-id` or any `--sha-*`
epoch field aborts. The harness also hashes `/proc/self/exe` and requires it to
match `epoch.artifacts.harness`. Legacy manual hash flags remain only for old
fixtures and are not the frozen campaign path.


The base manifest is intentionally incomplete until the independent wire and
holder witnesses are merged.


## v4.2 provenance correction

The harness specification header/trust-path diagram was stale in v4 and still named `manifest_to_p4.py -> r1_gate_v9.py`. v4.1 corrected that documentation to the implemented raw-witness/manifest/v9.1 path. No measurement C/Python logic changed.


## v4.2 epoch freeze

`freeze_epoch.py` no longer carries a filename table. It takes the epoch keyset
from `r1a_manifest.py::EPOCH_ARTIFACTS` and the exact local runtime paths from
`r1_gate_v9_1.py::runtime_epoch_local_files()` (`module.__file__`). A new local
module import that is not epoch-pinned makes freezing fail.
