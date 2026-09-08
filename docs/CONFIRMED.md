# Confirmed findings

This file contains only claims that are currently accepted from pinned source or separately verified historical artifacts. It does **not** treat the present `baseline/` directory as reproducible evidence until the repository completeness gate passes.

## 1. Source-level teardown ordering

At the pinned DWC2 source:

- DMA mode is controlled by `hsotg->params.g_dma`; descriptor DMA by `g_dma_desc`.
- An active request is programmed into the endpoint and its DMA address is exposed to the controller.
- `complete_request()` updates request status, calls the DWC2 DMA unmap path, clears the active request/list state, and only then gives the request back.
- In OUT endpoint stop, waits for Global OUT NAK / endpoint disable can time out and continue after warning rather than proving hardware quiescence.
- `ep_disable()` and current-request `ep_dequeue()` can route through that stop path and then complete/kill the same request.

Therefore the source supports the hypothesis that software teardown may continue after a failed quiescence wait. **The source alone does not prove that hardware is still issuing DMA at that point.**

## 2. R1A host-trigger path

The planned host path uses raw usbfs control submission rather than the convenience configuration API. This avoids the host-side `usb_set_configuration()` path that would locally tear down URBs before the control request reaches the gadget.

For re-arming, `USBDEVFS_RESETEP` resets host-side endpoint state (toggle/sequence/window). DWC2 device-side endpoint enable resets non-control data PID to D0. The re-arm preflight therefore measures whether endpoint reset is required on the actual host controller instead of assuming it.

These are source/tooling facts. **Real R1A execution on a DWC2 board remains pending.**

## 3. Pre-runtime tooling — historical verification only

Separately verified frozen artifacts from earlier clean-room runs recorded successful pre-runtime checks for:

- observer ABI v9 parsing and negative ABI discrimination;
- P4 classification tests;
- host build/selftests;
- manifest validation;
- usbmon and holder witness validation;
- campaign-only record slicing;
- epoch/provenance binding;
- deterministic/fail-closed packaging gates.

Those historical verification results remain valid statements about the artifacts that were actually tested. They are **not currently reproducible from this GitHub tree**, because the checked-in `baseline/` is incomplete and contains files that do not all match `baseline/SHA256SUMS`. The current fragment is documented in [`BASELINE-STATUS.md`](BASELINE-STATUS.md).

Therefore the current repository state is:

```text
checked-in pre-runtime baseline    INCOMPLETE / RE-IMPORT REQUIRED
historical clean-room results      RETAINED AS HISTORICAL EVIDENCE
current-tree reproducibility       NOT ESTABLISHED
```

`./VERIFY-REPOSITORY.sh` must pass from a clean checkout before this section may again describe the repository itself as containing a verified baseline.

The runtime boundary remains:

```text
R1A runtime             NOT EXECUTED
R2 / D_issue            UNKNOWN
R3 / D_commit           UNKNOWN
security impact         UNKNOWN
```

## 4. P3 status

`P3 = NOT_BUILT`.

It is **not required for R1A runtime** under the frozen R1 predicate. This is not a PASS; it is a scope statement.

## 5. Claims that must remain separate

- `UNMAP_DONE` proves the mapping lifetime ended.
- Access/fault to the same retired mapping proves a post-unmap **attempt** (`D_issue`) only when identity/correlation is closed.
- An IOMMU fault is **not** evidence of `D_commit`.
- `D_commit` requires a memory-side completed-effect observation or equivalent.
- Security severity requires a concrete security boundary/ownership impact and attacker preconditions.
