from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    p.write_text(s.replace(old, new, 1))


# 1) Canonical evidence ladder: hardware signature, controls, post-U hygiene.
replace_once(
    'docs/EVIDENCE-LADDER.md',
    'Only an exact controller databook/revision matched to the running hardware identity (`GSNPSID` and any required integration revision) may carry the hardware-contract claim. Product pages, legacy Raspberry Pi source comments, and third-party implementations are at most `WEAK_SIGNAL` and are excluded from load-bearing report evidence.',
    'Only an exact controller databook/revision matched to the running controller signature may carry the hardware-contract claim. The minimum signature is the raw tuple `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` from the same boot/configuration epoch. `GSNPSID` identifies the core revision but does not, by itself, establish the synthesized DMA/endpoint configuration. The selected databook must apply to that revision and to the observed `GHWCFG1..4` configuration relevant to reset/DMA semantics; if that applicability cannot be established, `K_hw` remains `UNDETERMINED`. Product pages, legacy Raspberry Pi source comments, and third-party implementations are at most `WEAK_SIGNAL` and are excluded from load-bearing report evidence.',
    'evidence databook signature',
)
replace_once(
    'docs/EVIDENCE-LADDER.md',
    'no explicit text for the matched controller revision\n    -> K_hw = UNDETERMINED',
    'no explicit text for the matched controller revision/configuration\n    -> K_hw = UNDETERMINED',
    'evidence databook undetermined scope',
)
replace_once(
    'docs/EVIDENCE-LADDER.md',
    'The measurement code remains read-only with respect to `DOEPINT` and must not reorder the reset/disconnect path.\n\nA fresh same-lineage `XferCompl` transition observed before U is terminal and yields `R1A_DEAD` for that attempt.',
    '''The measurement code remains read-only with respect to `DOEPINT` and must not reorder the reset/disconnect path.

`UNMAP_DONE` occurs after U and therefore has a stricter payload rule than earlier events. It may emit only stable lineage metadata (`reset/request/map/program`, endpoint, endpoint-interrupt generation) plus raw endpoint MMIO (`DOEPCTL`, `DOEPINT`, `DOEPTSIZ`). Mapping/request-payload fields are zero sentinels at this stage: `dma_addr=0`, `program_dma=0`, `length=0`, `actual=0`, `result=0`, `status=0`, `dma_mapped=0`. The `UNMAP_DONE` path must not read `req->dma`, `req->buf`, a saved/alignment buffer, or invoke `dma_sync_*`, another map/unmap, or any memory-side witness helper after the real unmap has returned.

#### Mandatory reset transition controls

A campaign `0 -> 1` `XferCompl` transition is discriminating only when **both** negative-control classes have passed in the same frozen controller/observer configuration:

```text
CTRL-IDLE / idle-reset
    no eligible live OUT transfer at reset
    purpose: detect XferCompl synthesized/reasserted by reset itself

CTRL-COMPLETED / completed-then-reset
    matching OUT transfer has a positive natural completion witness
    reset follows after a recorded, pre-frozen interval
    purpose: detect delayed/stale completion reporting from a transfer
             that was already complete before reset

CAMPAIGN-LIVE / live-then-reset
    matching OUT transfer is positively outstanding at RESET_ENTRY
    purpose: test the surviving reset branch
```

For `CTRL-COMPLETED`, `XferCompl` high at `RESET_ENTRY` is the direct expected signature when the bit has not already been naturally W1C-serviced. It is **not** made an unconditional validity requirement, because the ordinary endpoint-interrupt path may legitimately clear a completed transfer before the later reset. The fail-closed discriminator is stronger: if an already-completed control can show `RESET_ENTRY.XferCompl=0` followed by a new `0 -> 1` assertion after reset, then the same transition in `CAMPAIGN-LIVE` is non-discriminating and is `R1A_AMBIGUOUS`, not promotion evidence. Likewise, any post-reset `0 -> 1` in `CTRL-IDLE` kills the transition as an attribution discriminator.

Control counts, the completed-to-reset interval, and the exact host completion witness must be frozen before the campaign; they are not chosen after seeing campaign output.

A fresh same-lineage `XferCompl` transition observed before U is terminal and yields `R1A_DEAD` for that attempt.''',
    'evidence controls and post-u hygiene',
)

# 2) Runtime runbook: same contract as executable operating procedure.
replace_once(
    'docs/RUNTIME-RUNBOOK.md',
    '7. For reset/disconnect work, capture the exact controller identity (`GSNPSID` plus any integration/revision facts needed to select the correct databook) before making any hardware-contract statement.',
    '7. For reset/disconnect work, capture the raw controller signature `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` from the same boot/configuration epoch before making any hardware-contract statement. `GSNPSID` alone is insufficient to select a load-bearing DMA/reset contract.',
    'runbook preflight signature',
)
replace_once(
    'docs/RUNTIME-RUNBOOK.md',
    'After reading the running `GSNPSID`, select the exact controller databook/revision if obtainable and classify exactly one result:',
    'After reading the running `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` tuple, select a databook/revision only if its core revision and applicable synthesized configuration match the observed signature. A revision-only match is insufficient. Then classify exactly one result:',
    'runbook databook gate signature',
)
replace_once(
    'docs/RUNTIME-RUNBOOK.md',
    'The reset observer must not write `DOEPINT`, add a stop/NAK, change IRQ ordering, or modify map/unmap behavior.\n\nReset-specific interpretation is frozen as follows:',
    '''The reset observer must not write `DOEPINT`, add a stop/NAK, change IRQ ordering, or modify map/unmap behavior.

`UNMAP_DONE` is post-U and is register-only apart from stable lineage metadata. Its mapping/request-payload slots must be zero sentinels (`dma_addr`, `program_dma`, `length`, `actual`, `result`, `status`, `dma_mapped` all zero). After the real unmap returns, the observer may read only stable lineage/endpoint bookkeeping and the raw `DOEPCTL` / `DOEPINT` / `DOEPTSIZ` MMIO needed for the reset discriminator; it must not read `req->dma`/`req->buf`, touch the request buffer, call `dma_sync_*`, remap, or add a memory-side witness.

### Mandatory three-arm reset discriminator

Run and preserve all three arms under the same observer/controller/configuration fingerprint:

```text
CTRL-IDLE
  no eligible live OUT transfer at reset
  detects reset-synthesized/reasserted XferCompl

CTRL-COMPLETED
  same transfer class completes naturally first
  positive natural completion witness precedes reset
  reset follows after a recorded, pre-frozen interval
  detects late/stale completion reporting

CAMPAIGN-LIVE
  same transfer class is positively outstanding at RESET_ENTRY
  tests the surviving reset branch
```

`CTRL-COMPLETED` should show `XferCompl` already present at `RESET_ENTRY` when it has not been naturally W1C-serviced. If the normal endpoint interrupt cleared it before reset, the control remains usable for the stronger question: it must not produce a new post-reset `0 -> 1`. Any post-reset `0 -> 1` in either `CTRL-IDLE` or `CTRL-COMPLETED` makes the campaign transition non-discriminating and forces `R1A_AMBIGUOUS`. Freeze the control denominators, completed-to-reset interval, and completion witness before campaign execution.

Reset-specific interpretation is frozen as follows:''',
    'runbook controls and post-u hygiene',
)
replace_once(
    'docs/RUNTIME-RUNBOOK.md',
    '- reset branch: exact `GSNPSID`, selected databook identity/result, `K_hw`, `reset_generation`, `RESET_ENTRY`, reset-safe `PRE_U`, and reset-safe `UNMAP_DONE` raw `DOEPINT`/`DOEPTSIZ`;',
    '- reset branch: raw `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` controller signature, selected databook identity/applicability/result, `K_hw`, `CTRL-IDLE`, `CTRL-COMPLETED`, `CAMPAIGN-LIVE`, `reset_generation`, `RESET_ENTRY`, reset-safe `PRE_U`, and register-only reset-safe `UNMAP_DONE` raw `DOEPCTL`/`DOEPINT`/`DOEPTSIZ`;',
    'runbook required reset artifacts',
)
replace_once(
    'docs/RUNTIME-RUNBOOK.md',
    'RESET-D  UNMAP_DONE register snapshot occurs only after the real unmap returns\n```',
    'RESET-D  UNMAP_DONE register snapshot occurs only after the real unmap returns\nRESET-E  UNMAP_DONE has zero mapping/request-payload reads and emits lineage + raw MMIO only\nRESET-F  both idle-reset and completed-then-reset controls are frozen before campaign promotion\n```',
    'runbook reset semantic gates',
)

# 3) Pi first-boot commands: preserve exact synthesized-controller signature.
replace_once(
    'docs/hardware/PI-ZERO-2W-COMMANDS.md',
    '''  grep -E '(^|[[:space:]])(op_mode|arch|dma_desc_enable|g_dma|g_dma_desc)([[:space:]]|=)' \\
    "$OUT/dwc2-hw_params.txt" "$OUT/dwc2-params.txt" 2>/dev/null \\
    | tee "$OUT/pi-fb2-effective.txt" || true

  GHWCFG4_HEX="$(grep -i 'GHWCFG4' "$OUT/dwc2-regdump.txt" 2>/dev/null \\
''',
    '''  grep -E '(^|[[:space:]])(op_mode|arch|dma_desc_enable|g_dma|g_dma_desc)([[:space:]]|=)' \\
    "$OUT/dwc2-hw_params.txt" "$OUT/dwc2-params.txt" 2>/dev/null \\
    | tee "$OUT/pi-fb2-effective.txt" || true

  grep -Ei 'GSNPSID|GHWCFG1|GHWCFG2|GHWCFG3|GHWCFG4' \\
    "$OUT/dwc2-regdump.txt" 2>/dev/null \\
    | tee "$OUT/pi-controller-signature-raw.txt" || true

  if ! grep -qi 'GSNPSID' "$OUT/pi-controller-signature-raw.txt" || \\
     ! grep -qi 'GHWCFG1' "$OUT/pi-controller-signature-raw.txt" || \\
     ! grep -qi 'GHWCFG2' "$OUT/pi-controller-signature-raw.txt" || \\
     ! grep -qi 'GHWCFG3' "$OUT/pi-controller-signature-raw.txt" || \\
     ! grep -qi 'GHWCFG4' "$OUT/pi-controller-signature-raw.txt"; then
    printf 'CONTROLLER_SIGNATURE_INCOMPLETE\\n' | tee "$OUT/pi-controller-signature.status"
  else
    printf 'CONTROLLER_SIGNATURE_COMPLETE\\n' | tee "$OUT/pi-controller-signature.status"
  fi

  GHWCFG4_HEX="$(grep -i 'GHWCFG4' "$OUT/dwc2-regdump.txt" 2>/dev/null \\
''',
    'pi controller signature capture',
)
replace_once(
    'docs/hardware/PI-ZERO-2W-COMMANDS.md',
    '`GHWCFG4.DESC_DMA` is bit 30. Keep the raw register dump as the primary artifact, not only the decoded value.',
    '`GHWCFG4.DESC_DMA` is bit 30. Keep the raw register dump as the primary artifact, not only the decoded value. For reset/databook work, the load-bearing controller match key is the same-epoch raw tuple `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}`; `GSNPSID` alone is never sufficient.',
    'pi signature interpretation',
)

# 4) Tinker commands: same signature rule if AQ-D1 ever authorizes it.
replace_once(
    'docs/hardware/TINKER-BOARD-S-COMMANDS.md',
    '''  grep -Ei 'GHWCFG2|GHWCFG4' "$OUT/dwc2-regdump.txt" 2>/dev/null \\
    | tee "$OUT/rk-fb2-hwcfg-raw.txt" || true''',
    '''  grep -Ei 'GSNPSID|GHWCFG1|GHWCFG2|GHWCFG3|GHWCFG4' \\
    "$OUT/dwc2-regdump.txt" 2>/dev/null \\
    | tee "$OUT/rk-controller-signature-raw.txt" || true''',
    'tinker controller signature capture',
)
replace_once(
    'docs/hardware/TINKER-BOARD-S-COMMANDS.md',
    'A board-role failure is not authorization to buy Firefly. First determine whether it is a board configuration/DT/connector problem or a SoC-wide limitation.',
    'For reset/databook work, preserve `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}` from the same epoch and require databook applicability to both the core revision and synthesized configuration. A board-role failure is not authorization to buy Firefly. First determine whether it is a board configuration/DT/connector problem or a SoC-wide limitation.',
    'tinker signature interpretation',
)

# 5) Device README: make v4 the current pre-hardware observer artifact.
replace_once(
    'r1a-device/README.md',
    'The active producer\'s source is admitted by executable repository gates.\nStructural and synthetic round-trip tests do **not** substitute for execution on\na real DWC2 UDC.\n',
    '''The active producer's source is admitted by executable repository gates.
Structural and synthetic round-trip tests do **not** substitute for execution on
a real DWC2 UDC.

## Current reset-capable observer artifact

The current pre-hardware observer patch is:

```text
instrumentation/R1A-RESET-INSTRUMENTATION-v4.patch
SHA256 d27b292633fe78a9ee5adc087ed0357fd3a0dbee6c9923474fb32f04dc2df6d7
```

Its receipt records standalone apply, measurement-disabled build,
measurement-enabled build, semantic fail-closed checks, and
`unmap_done_mapping_payload_reads=ZERO`. V3 remains historical evidence and is
not the preferred hardware epoch after this refinement.
''',
    'device readme v4 observer',
)
