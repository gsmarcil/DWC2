# Impact analysis for the DWC2 stop-before-unmap hypothesis

Analytical. **Nothing here moves the evidence ladder.** Every claim carries the
support level that was actually established for it, and the verification method
is named so a reviewer can repeat it rather than trust this file.

```text
verified against   torvalds/linux @ 08df884136f1c1197bab2a27814404fd329d9aac
```

## Support vocabulary

```text
SOURCE-PROVEN       read out of the kernel tree at the commit above
EXTERNAL-VERIFIED   confirmed at a primary or multiple independent sources
EXTERNAL-REPORTED   exists, but its body could not be read from here
LIKELY              follows from documented behaviour, not directly observed
UNKNOWN             requires a hardware artifact
```

## 1. The driver does not wait for transfer completion on the OUT path

`SOURCE-PROVEN.` This is the load-bearing internal claim, and it is stronger
than a summary suggests. In `dwc2_gadget_handle_ep_disabled()`, a non-isochronous
OUT endpoint clears `GOUTNAK` if set and then:

```c
if (!hs_ep->isochronous)
        return;
```

For BULK OUT, the path the hypothesis concerns, the handler returns without
touching the in-flight request at all. It never reads `XferCompl` and never
waits for it. The isochronous branch below is the only one that completes
requests, and it does so with `-ENODATA`.

So the disabled-interrupt handler contributes no quiescence evidence whatsoever
on the hypothesis path. Whatever confidence exists that DMA has stopped comes
from `dwc2_hsotg_ep_stop_xfr()`, whose waits warn and continue.

## 2. EPDisbld and XferCompl are distinct bits

`EXTERNAL-REPORTED` for the vendor wording; `SOURCE-PROVEN` for the consequence.

Vendor documentation for DWC2-derived cores separates two interrupt bits:
`EPDisbld` reports that the endpoint was disabled per the application's request,
while `XferCompl` reports that the programmed transfer completed on the AHB as
well as on the USB. Only the second speaks to the memory side.

The datasheets were not fetched from a primary source here, so the wording is
`EXTERNAL-REPORTED`. What does not depend on them is section 1: the Linux driver
does not consult `XferCompl` on this path either way.

Consequence, stated conservatively: a disable acknowledgement is not a statement
about DMA. Treating either the acknowledgement or the expiry of a wait for it as
proof of quiescence is unsupported.

## 3. Descriptor DMA widens the window rather than narrowing it

`SOURCE-PROVEN` for the structure. `using_desc_dma()` is simply
`hsotg->params.g_dma_desc`, so a target runs DDMA only when that parameter is
set, and Buffer DMA otherwise. The campaign targets `g_dma=1, g_dma_desc=0`,
which is the Buffer DMA case.

An RFC posted 2023-07-26 by `abailon@baylibre.com`
(`20230726102252.2236314-1-abailon@baylibre.com`) reports that the driver may
update a descriptor already owned by the DMA engine. The message id, author and
date are `EXTERNAL-VERIFIED`; the body could not be read from here, and no
matching fix is in mainline, so the RFC is `EXTERNAL-REPORTED` and unmerged.

A separate DDMA hazard **is** merged and is worth recording because it shows this
family of bug is real in DWC2 and not hypothetical:

```text
1134289b6b93  2024-05-23  Peng Hongchi
usb: dwc2: gadget: Don't write invalid mapped sg entries into dma_desc
with iommu enabled
```

With an IOMMU present, `dma_map_sg()` merges entries, so `num_mapped_sgs` is
smaller than `num_sgs` and the tail of the scatterlist holds entries with
`dma_addr = 0xffffffff, len = 0`. Writing those into the descriptor ring caused
transmission errors. That is a real defect where the driver's view of a mapping
and the hardware's view diverged.

It is not this hypothesis. The trigger is entry merging, not a teardown race.
It is recorded as context on DDMA fragility only.

## 4. Stopping DMA is not a solved problem in this controller

`EXTERNAL-VERIFIED` via the Fuchsia commit already recorded in `PENDING.md` at
`MIRROR_VERIFIED / ORIGINAL_PENDING`. Engineers working on DWC2 concluded that
guaranteeing DMA has stopped before releasing memory is "harder than it looks",
that stopping individual endpoints is "only _reluctantly_ supported", and chose
to quarantine pinned memory rather than reclaim it.

Reset is not an escape hatch either. Vendor documentation conditions a core soft
reset on the application first ensuring the DMA engine is not reading from the
RxFIFO, which is the very fact in question. That wording is
`EXTERNAL-REPORTED`.

## 5. usbliter8: what it proves, and what it does not

`EXTERNAL-VERIFIED.` Published June 2026 by Paradigm Shift and reported
consistently across multiple independent outlets.

The mechanism, as reported: the DWC2 controller stores incoming Setup packets by
DMA, buffers three, and on the fourth decrements its write pointer by a fixed 24
bytes while short packets advance it by only the bytes actually written. The
mismatch walks the write pointer backwards through memory, 12 bytes at a time.

```text
proves     DWC2 DMA can write outside the region the software intended,
           on real silicon, to an address the software did not choose

proves     the IOMMU configuration decides the blast radius. A12/A13 run
           the DART in bypass inside SecureROM, so the walking pointer
           reaches arbitrary SRAM. A14 and later configure it correctly
           and the same flaw is not exploitable

proves     the protection that worked was NOT trusting the controller to
           stop. A11 re-establishes the DMA address after every packet

does NOT   support the stop-before-unmap hypothesis. Different code base
           entirely (Apple SecureROM, not Linux), different trigger
           (Setup-packet pointer underflow, not a teardown race), and a
           different failure (a pointer walking backwards, not a mapping
           expiring under a live engine)
```

The third line is the one worth carrying: the mitigation that held was
re-establishing the address rather than relying on quiescence. That is the same
instinct behind Fuchsia's quarantine and behind DWC3's refusal to unmap while
`DWC3_EP_DELAY_STOP` is set. Three independent parties declined to trust a DWC2-
family controller to have stopped.

That is a pattern in how engineers treat this hardware. It is not evidence about
what the hardware does.

## 6. The chain, and where it actually breaks

```text
host sends an OUT packet                          SOURCE-PROVEN
DMA begins writing into the mapped buffer         SOURCE-PROVEN
driver raises EPDisable                           SOURCE-PROVEN
disable handler returns without touching the
  in-flight BULK OUT request                      SOURCE-PROVEN
stop waits expire, warn, and continue             SOURCE-PROVEN
complete_request() -> dma_unmap()                 SOURCE-PROVEN
DMA still active, late write lands post-unmap     UNKNOWN   <-- the gap
memory reallocated, write hits another object     UNKNOWN
```

Every link is source-proven down to one, and that one is the entire hypothesis.
The analysis above narrows what a positive result would mean; it does not
shorten the chain by a single rung.

Note also what the chain does not require. The hypothesis does not need the
attacker to control the late write's content or destination. A single unowned
write is a memory-safety defect. Controllability is a severity question, and
severity is not on the table until `D_commit` exists.

## 7. What would close the gap

```text
1  Record XferCompl relative to EPDisbld on real DWC2 hardware. If
   XferCompl can arrive after EPDisbld, the disable acknowledgement is
   proven insufficient as a quiescence signal.

2  Sample AHBIdle and DMAReq together. If DMAReq can be set while
   AHBIdle reads idle, AHBIdle is proven insufficient on its own.

3  Record the IOMMU mode with every run. Under non-strict mode
   invalidation is deferred, so absence of a fault is an untested
   condition rather than evidence of safety. Pi Zero 2W has no IOMMU on
   the USB path, so this witness is unavailable on the planned target.

4  Read the A11 mitigation. Re-establishing the DMA address every packet
   is a defence that does not depend on the controller stopping, and it
   may suggest a Linux-side guard that is testable without proving the
   race first.
```

Items 1 and 2 are the cheapest and the most decisive. Both are single
observations on a board that is already the campaign's first target, and either
result is publishable: proving a signal insufficient is as useful as proving the
race.

## 8. Limits of this document

```text
does not prove   that Linux DWC2 has a stop-before-unmap race
does not prove   that a late write reaches a sensitive kernel object
does not prove   that a host can widen the window on demand
cites usbliter8  only for DWC2 DMA's capability to write where software
                 did not intend, never as evidence of this race
```

Every `UNKNOWN` above needs an artifact from real DWC2 hardware. Runtime R1A
remains `NOT EXECUTED`, `K_hw` remains `UNDETERMINED`, and `D_issue` and
`D_commit` remain `UNKNOWN`.
