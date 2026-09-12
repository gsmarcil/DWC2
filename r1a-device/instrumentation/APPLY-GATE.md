# Instrumentation apply gate

```text
R1A-RESET-INSTRUMENTATION-v3.patch   REJECT / DO NOT RUN
R1A-RESET-INSTRUMENTATION-v4.patch   SUPERSEDED BY v5
R1A-RESET-INSTRUMENTATION-v5.patch   NEEDS_BUILD_VERIFICATION
```

## v5 status

v5 exists and clears criteria 1 to 3. It does **not** clear 4 and 5, so it is
still not admissible for the campaign.

```text
patch_sha256  c2b0884c9a2753853ed2c19b3a25f49fdced159585e5ba045f4f034f354c509d

criterion 1  EPDIS event after the write, renamed EPDIS_WRITTEN     PASS
criterion 2  zero MMIO between the stop timeout and the unmap in
             the decisive build                                     PASS
criterion 3  PROGRAMMED split into DMA_ADDR_WRITTEN and EP_ARMED    PASS

standalone apply to the pin, whitespace, diff --check                PASS

criterion 4  campaign composition built and tested as one kernel    UNVERIFIED
criterion 5  arm64 build with measurement off and on                UNVERIFIED
```

Criteria 4 and 5 were not attempted rather than attempted and passed. The
environment that produced v5 holds three pinned driver files and no kernel tree
or cross toolchain, so no build of any kind was run. The receipt records this as
`NOT_RUN`, not as a pass.

### How criterion 2 is met, and how that is checked

The three register reads are now inside `#ifdef CONFIG_USB_DWC2_R1_MEASURE_DIAG`,
a separate Kconfig defaulting to `n`. In the campaign build they are not
compiled at all, so the property is a fact about the binary rather than about a
runtime flag someone might set wrongly.

Verified by stripping the diagnostic region from the patched source and counting
`dwc2_readl` calls in the window:

```text
MMIO reads in ep_stop_xfr after the EPDIS write   0
MMIO reads between PRE_U and the unmap            0
same reads present in the diagnostic build        yes
```

Every record also carries `DWC2_R1_FLAG_DIAG_BUILD` (flags bit 7) when the
diagnostic build produced it. This is load-bearing: without it a diagnostic
trace and a decisive trace are indistinguishable in the artifact, which is the
same discrimination failure documented in `docs/EVIDENCE-DISCRIMINATION.md`. A
consumer closing the hypothesis negatively must reject any trace with that bit
set.


Every finding below was re-read out of the patch files themselves. Line numbers
refer to the patch, not to the kernel.

## v3 — rejected by its own receipt

`R1A-RESET-INSTRUMENTATION-v3.RECEIPT.txt` opens with
`SUPERSEDED BY v4 — do not run`, and gives the reason: v3's `UNMAP_DONE` may
read request or mapping-derived scalars after U. That is the defect the whole
campaign exists to avoid, committed inside the instrument. No further analysis
is required.

## v4 — what is genuinely sound

```text
PATCH_APPLIES_TO_PIN       PASS   f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
BUILD_CONFIG_OFF           PASS
BUILD_CONFIG_ON            PASS
POST_U_PAYLOAD_READ_GUARD  PASS   unmap_done_mapping_payload_reads=ZERO
```

The reproducibility story is good: the patch is bound to the same kernel pin the
campaign targets, and the receipt records standalone apply plus builds with
measurement disabled and enabled.

None of that is in question below. The blockers are about whether the instrument
can answer the question, not whether it compiles.

## BLOCKER 1 — the event precedes the act it names

Patch lines 364-366:

```c
+	dwc2_r1_measure_event(hsotg, hs_ep, hs_ep->req,
+			       DWC2_R1_EPDIS_ASSERT, 0, true);
 	dwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);
```

The artifact records `EPDIS_ASSERT` before software asserts EPDIS. The final
argument is `snapshot_regs = true`, so three MMIO reads also land between the
event and the write.

The trace therefore reads:

```text
EPDIS_ASSERT -> 3 MMIO reads -> time -> actual EPDIS write
```

Anything that happens in that window, including `XferCompl` or a hardware state
change, appears in the trace as having followed the assertion when the assertion
had not yet occurred. That is a false causal ordering in the one place the
campaign reasons about causality.

Required: emit after the write, named for what happened.

```c
dwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);
dwc2_r1_measure_event(..., DWC2_R1_EPDIS_WRITTEN, ..., false);
```

## BLOCKER 2 — the observer can close the window it is measuring

This is the one that would waste a campaign.

`dwc2_r1_emit()` under `snapshot_regs`:

```c
if (snapshot_regs) {
        epctl = dwc2_readl(hsotg, DOEPCTL(hs_ep->index));
        epint = dwc2_readl(hsotg, DOEPINT(hs_ep->index));
        epsiz = dwc2_readl(hsotg, DOEPTSIZ(hs_ep->index));
}
```

Three MMIO reads. The call sites that pass `true` are exactly the three inside
the critical window:

```text
patch:365   EPDIS_ASSERT   snapshot=true
patch:374   WAIT_RETURN    snapshot=true
patch:314   PRE_U          snapshot=true
```

So nine MMIO reads are inserted between the stop attempt and the unmap. The
hypothesis is that hardware is *not yet quiescent* when software unmaps. Adding
delay in that exact interval gives the hardware more time to finish.

The failure is asymmetric, which is what makes it dangerous:

```text
instrument can turn   a racing uninstrumented execution
into                  an apparently safe instrumented one

instrument cannot     create the race where none exists
```

A positive result from v4 would still mean something. **A negative result would
mean nothing at all**, because the instrument perturbs the measurement in the
direction of the null. Closing the hypothesis with this build would be closing
it on an artifact of the observer.

Required: the decisive run carries no MMIO between timeout and unmap.

```text
EPDIS write
  -> EPDIS_WRITTEN     lineage only
  -> original wait loop, untouched
  -> WAIT_RETURN       lineage only
  -> UNMAP_BEGIN       lineage only
  -> dma_unmap()
  -> UNMAP_DONE        lineage only
```

Register snapshots move to a separate diagnostic mode that is never used to
close the hypothesis negatively.

## BLOCKER 3 — `PROGRAMMED` conflates two events

In `dwc2_hsotg_start_req` the DMA address is written first, and the endpoint is
armed later in a separate write:

```c
dwc2_writel(hsotg, ureq->dma, dma_reg);     /* address written */
...
dwc2_writel(hsotg, ctrl, epctrl_reg);       /* ctrl carries EPENA */
+	dwc2_r1_measure_programmed(hsotg, hs_ep, hs_req, ...);
```

One `PROGRAMMED` event is emitted after arming, so it stands for both "the DMA
address reached the register" and "the endpoint was armed". Lineage proof needs
these separate: the claim is that the IOVA whose lifetime ended is the same one
that entered a hardware register.

Required:

```text
MAP -> DMA_ADDR_WRITTEN -> EP_ARMED -> ...
```

## Composition and target gaps

```text
CAMPAIGN_COMPOSITION   UNVERIFIED
ARM_TARGET_BUILD       UNVERIFIED
```

`PENDING.md` still requires `observer ABI=9`, `snapshot_atomic=1` and `lost=0`
for the campaign. v4 is independent instrumentation and does not provide those
by itself, and the CI evidence covers v4 **standalone** only. Either v4 replaces
the ABI=9 observer, in which case P0 and the consumer contracts must be updated,
or it is stacked with it, in which case the actual stacked combination needs its
own apply, build and semantic test. No artifact currently shows that the kernel
which would be booted is the combination that was tested.

The CI built `x86_64_defconfig`. The campaign target is a Cortex-A53. The patch
adds `u64` counters to hot structures and touches IRQ and endpoint paths, so the
target architecture must be built before the patch is trusted:

```text
x86_64  CONFIG_R1_MEASURE=n/y   PASS   (done)
arm64   CONFIG_R1_MEASURE=n/y   required
arm     CONFIG_R1_MEASURE=n/y   required if a 32-bit Pi kernel stays in scope
```

## Promotion criteria

v4 becomes `SAFE_TO_APPLY` when all of these hold:

```text
1  EPDIS event is emitted after the register write and named for it
2  zero MMIO reads between the stop timeout and the unmap in the
   decisive run; snapshots confined to a separate diagnostic mode
3  PROGRAMMED split into DMA_ADDR_WRITTEN and EP_ARMED
4  the actual campaign composition applied, built and semantically
   tested as one kernel
5  arm64 build PASS with measurement off and on
```

Until then the instrument may be developed and built, but no trace it produces
may be used to close `D_issue` in either direction.

This gate makes no claim about DWC2 hardware. It is about whether these patches
can produce admissible evidence, and today they cannot.
