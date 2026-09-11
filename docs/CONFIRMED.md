# Confirmed findings

This file contains only claims that are currently accepted from pinned source or
separately verified artifacts. The canonical v4.2 `baseline/` is reproducible
while its 89-path integrity and executable package gates pass; overall campaign
readiness is a separate state.

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

## 3. Pre-runtime tooling — canonical v4.2 verified

Separately verified frozen artifacts from earlier clean-room runs recorded successful pre-runtime checks for:

- observer ABI v9 parsing and negative ABI discrimination;
- P4 classification tests;
- host build/selftests;
- manifest validation;
- usbmon and holder witness validation;
- campaign-only record slicing;
- epoch/provenance binding;
- deterministic/fail-closed packaging gates.

Those results are now reproducible from the byte-identical canonical v4.2 import.
The archive's external SHA256, internal 89-path manifest, package verification,
and baseline integrity gate passed during import. See
[`CANONICAL-IMPORT-RECEIPT-v4.2.md`](CANONICAL-IMPORT-RECEIPT-v4.2.md).

Therefore the current repository state is:

```text
checked-in pre-runtime baseline       VERIFIED / CANONICAL v4.2
historical clean-room results         RETAINED AS HISTORICAL EVIDENCE
current-tree baseline reproducibility ESTABLISHED
```

The gate verdict is stated below in the canonical key form so it is compared
against what `VERIFY-REPOSITORY.sh` actually computes rather than drifting on
its own:

```text
REPOSITORY_BASELINE: PASS
SOURCE_FOUNDATION: PASS
HOLDER_CAMPAIGN_READINESS: PASS
REPOSITORY_GATE: PASS
```

This pre-runtime verification does not promote any runtime claim.

This file previously recorded `holder campaign readiness BLOCKED / PRODUCER
INCOMPATIBLE` and stated that the gate "must preserve `REPOSITORY_BASELINE:
PASS` while failing the incompatible holder producer". Both outlived the
condition that produced them: the compatible producer was imported, G1 closed,
and the gate went green. The wording here was also in a prose form the
status-sync guard could not read, which is why it drifted for longer than the
files the guard covered. It now uses the checked form.

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

## Related but distinct, recorded so they are not conflated

```text
CVE-2026-64337 / mtu3     commit 0bddda5a1166 (2026-06-23)
                          usb: mtu3: unmap request DMA on queue failure
```

An unmapped-DMA leak on the **queue error path**, not a teardown-path
asymmetry. Noted only to show that map/unmap asymmetry is not confined to
shutdown paths. It does not bear on the DWC2 teardown hypothesis.

```text
musb (historical)         commit 06d9db7273c7 (2013-03-15)
                          usb: musb: gadget: do *unmap_dma_buffer* only for
                          valid DMA addr
```

Unmapping DMA unconditionally in a shared giveback path caused an OOPS on ep0,
which has no DMA buffer. Historical only: it shows giveback-path unmap handling
has been fragile in this subsystem for over a decade. It is not evidence that
DWC2 has the same bug.

```text
CVE-2026-68370 / dummy_hcd   commit d5e5cd3654d2 (2026-07-16)  OUT OF SCOPE
```

Concurrent reuse of a shared `usb_request` during giveback. It involves no
`dma_unmap` and no mapping lifetime at all, so it is not the same bug class and
is excluded deliberately rather than overlooked.
