# Impact analysis — DWC2 stop-before-unmap

Analytical. **Does not move the evidence ladder.** Each claim carries its
support class.

```text
SOURCE-PROVEN   established by the Linux source, line-cited below
DOCUMENTED      stated in controller documentation reviewed
EXTERNAL        corroboration from outside this repository, bounded by
                its own scope
UNKNOWN         not established by any artifact currently held
```

Source claims were re-read at `08df884136f1c1197bab2a27814404fd329d9aac` in
`drivers/usb/dwc2/gadget.c`. Line numbers are given so a reviewer repeats the
reading rather than trusting this file.

## 1. The source-level chain (SOURCE-PROVEN)

Read directly from the tree, not inferred from hardware behaviour:

```text
dwc2_hsotg_ep_disable()
  -> if (ctrl & DXEPCTL_EPENA)                          :4243
       dwc2_hsotg_ep_stop_xfr()                         :4244
  -> wait DXEPINT_EPDISBLD, timeout 100                 :3982
  -> on timeout: dev_warn() only, no abort              :3983
  -> W1C clear of EPDISBLD                              :3987
  -> ctrl &= ~DXEPCTL_EPENA                             :4246
  -> kill_all_requests(..., -ESHUTDOWN)                 :4257
  -> dwc2_hsotg_complete_request()
  -> dwc2_hsotg_unmap_dma()                             :2140
  -> usb_gadget_unmap_request()
  -> [for a DWC2-mapped non-zero request]
       dma_unmap_{single,sg}()
```

The load-bearing property is not that the driver ignores the timeout. It is that
the driver never escalates the timeout into any positive quiescence
acknowledgement before reaching the unmap. The warning changes no control flow.
Under the guard/detector rule in `METHODOLOGY.md`, this is a detector, not a
guard.

```text
SOURCE-PROVEN
    For a non-zero request whose mapping was established through the
    gadget DMA mapping path, Linux DWC2 can terminate that mapping after
    an endpoint-stop acknowledgement timeout without obtaining a
    positive endpoint-disabled acknowledgement.

NOT licensed by this section
    DMA is definitely still active when unmap occurs.
```

That remains `UNKNOWN` and is the closure gate of this document.

## 2. The closure gate (UNKNOWN)

```text
host keeps an OUT request active
  -> DWC2 has request DMA state programmed
  -> Linux requests endpoint stop
  -> EPDISBLD wait TIMES OUT
  -> Linux does not abort teardown
  -> kill_all_requests()
  -> dwc2_hsotg_complete_request()
  -> [for a DWC2-mapped non-zero request]
       dma_unmap_{single,sg}()
  -> usb_gadget_giveback_request()
  -> subsequent buffer reuse/free is possible
  -> ??????????????????????????????????????????
  -> does DWC2 perform any memory transaction using the retired mapping?
```

For a DWC2-mapped non-zero request, the path through
`usb_gadget_giveback_request()` is SOURCE-PROVEN. Subsequent buffer reuse or
free is function-driver-dependent and is **possible**, not SOURCE-PROVEN for a
particular request.

```text
CLAIM
    For a request mapped through the gadget DMA path, after failure to
    obtain endpoint-disable acknowledgement, Linux DWC2 may end that
    mapping's lifetime while hardware activity associated with the
    request remains possible.

SUCCESS ARTIFACT
    Same request, same DMA address:
      STOP_BEGIN -> EPDISBLD_TIMEOUT -> UNMAP_DONE
      -> post-unmap DMA transaction OR IOMMU fault to the retired IOVA

KILL
    Positive evidence that no DWC2 memory-side DMA can occur after the
    timeout path reaches unmap.
```

## 3. DMA backend taxonomy for the victim model

What `dma_unmap()` actually does decides the shape of any victim effect. This is
more load-bearing than the Buffer-DMA versus Descriptor-DMA distinction and must
be stated before any impact claim.

```text
STRICT IOMMU
    dma_unmap revokes the IOVA synchronously
    stale DMA -> expected observable is an IOMMU fault, write blocked
    direct corruption not shown in this configuration

NON-STRICT / LAZY IOMMU
    invalidation is deferred; translation may persist briefly
    late DMA may still reach the old physical page
    API lifetime violation possible; victim overwrite needs
    reuse/invalidation ordering evidence

DIRECT DMA / NO IOMMU
    unmap may not revoke the physical address at all
    later allocator ownership change is possible
    strongest corruption model, conditional on continuation

SWIOTLB
    DMA targets bounce storage; unmap/recycle changes slot ownership
    late DMA could affect a recycled slot; needs its own victim model
```

No victim claim here may be read without naming the backend. Absence of an IOMMU
fault under non-strict mode is not evidence of safety; it is an untested
condition.

Cross-object reuse is not required for the first observable victim effect. If
post-unmap DMA is demonstrated after giveback, the minimum effect is
post-completion mutation of a buffer the gadget layer already considers
completed:

```text
DMA_UNMAP -> GIVEBACK -> late DMA mutates the same buffer
```

A stronger cross-object corruption claim additionally requires evidence that the
buffer was freed or recycled to a different owner before the late DMA write.

## 4. Sub-question triage

### 4.1 Buffer DMA versus Descriptor DMA

Holds: both modes exist, and `using_desc_dma()` is simply
`hsotg->params.g_dma_desc`, so DDMA runs only when that parameter is set. In
DDMA, software and hardware share the descriptor ring, and a 2023 RFC
(`20230726102252.2236314-1-abailon@baylibre.com`, EXTERNAL, unmerged) reports
that software may modify a descriptor the DMA side is still consuming. The
outcome reported there is BNA/ZLP, not memory corruption.

Does not hold: a fixed byte bound such as "1 to 64 bytes" for Buffer DMA. The
driver programs the length from the remaining request and then caps it:

```c
length = ureq->length - ureq->actual;          /* :1094 */
maxreq = get_ep_limit(hs_ep);                  /* :1099 */
```

A single programmed transfer can therefore span multiple packets, and `maxpacket`
is not the bound.

```text
Buffer DMA    the potential stale-write extent is bounded by DMA work
              still outstanding when the mapping lifetime ends, not by
              maxpacket

Descriptor DMA  software can modify descriptors concurrently with the DMA
              side; the consequence when the referenced buffer is
              unmapped before the descriptor is consumed is UNKNOWN
```

A merged DDMA defect is worth recording as context on ring fragility, and
explicitly is not this hypothesis: `1134289b6b93` (2024-05-23) stopped the driver
writing IOMMU-merged invalid scatterlist entries (`dma_addr=0xffffffff, len=0`)
into the descriptor ring.

### 4.2 EPDISBLD versus XferCompl

Holds: the two bits encode different events. `EPDISBLD` indicates the endpoint
was disabled per software request; `XferCompl` in non-SG mode indicates the
programmed transfer completed on AHB and on USB.

Does not hold: that `EPDISBLD` asserted without `XferCompl` implies DMA is still
active. The disable may **abort** the transfer rather than complete it, and
`XferCompl` is not required to rise in that case. A pending `XferCompl` observed
elsewhere may equally be a transfer that completed immediately before the
disable and whose interrupt state was not yet cleared.

```text
EPDISBLD sufficient for memory-side quiescence:  UNKNOWN
```

The strength of the timeout path does not depend on this subsection. It is the
absence of any positive acknowledgement at all, combined with continued
execution into unmap. That is section 1.

### 4.3 Absence of an XferCompl wait

Downgraded. The driver not waiting on `XferCompl` is consistent with the chain,
but it is evidence only that this particular bit is not used as a gate, not that
quiescence is missing. Whether any other gate exists on the path is what
section 1 answers, and the answer there is none.

### 4.4 Core soft reset

Corrected. The frequently quoted precondition

> "only after making sure that neither the DMA engine is reading from the RxFIFO
> nor the MAC is writing the data into the FIFO"

belongs to **RxFFlsh**, not to Core Soft Reset. An earlier draft of this file
attributed it to `CSftRst`, which inverted the conclusion.

Core soft reset is `DOCUMENTED` to return state machines to idle, terminate AHB
master transactions after the last clean AHB data phase, terminate USB
transactions immediately, and require `AHBIdle` to be checked afterwards. The
register semantics are documented; comparing reset with endpoint disable as a
quiescence boundary is an analytical inference.

```text
DOCUMENTED
    Core soft reset returns the relevant state machines toward idle and
    has explicit AHB transaction-completion semantics.

ANALYTICAL
    Those semantics make full core reset a stronger candidate quiescence
    boundary than endpoint disable.

SOURCE-PROVEN
    The Linux teardown path under investigation does not escalate an
    EPDISBLD timeout to core reset before unmapping requests.
```

This makes the Fuchsia observation more relevant, not less. Fuchsia uses core
reset before releasing memory and quarantines the memory when reset does not
succeed. It does not claim core reset is unreliable; it uses core reset as the
safe boundary.

### 4.5 AHBIdle versus DMAReq

Holds: the bits are distinct. `AHBIdle` is an AHB master state-machine
condition; `DMAReq` indicates a DMA request in progress.

Does not hold: that `AHBIdle=1` with `DMAReq=1` is reachable, or that `AHBIdle`
is therefore insufficient. No artifact currently held establishes the (1,1)
state.

```text
AHBIdle sufficient for quiescence:  UNKNOWN
```

Sampling the two together is a valid runtime probe. It is not a source-level
conclusion.

## 5. External corroboration, bounded

### 5.1 Fuchsia DWC2 — invariant only

Fuchsia's driver deliberately leaks pinned endpoint memory to a quarantine to
avoid runaway DMA after shutdown, states that stopping individual DWC2 endpoints
is "only _reluctantly_ supported", uses core reset before releasing memory, and
keeps memory quarantined when reset does not succeed.

```text
corroborates   the invariant: memory must not be released or unpinned
               until the controller is known to have stopped
corroborates   that engineers who examined DWC2 independently found the
               stop operation non-trivial
does NOT       show Linux DWC2 has the same bug
does NOT       show the Linux stop-timeout path is what Fuchsia guarded
```

### 5.2 usbliter8 — consequence analogue only

usbliter8 (Paradigm Shift, June 2026, EXTERNAL-VERIFIED across multiple
independent outlets) shows DWC2 DMA writing outside the intended buffer and
reaching unintended SRAM where platform isolation did not contain it. A12/A13
run the DART in bypass inside SecureROM; A11 reprograms the DMA address after
every packet and the accumulation does not occur.

```text
corroborates   DWC2 DMA can produce real victim corruption when its
               effective target escapes the intended buffer
corroborates   absence of platform isolation is what turns an escape into
               a memory-safety effect
does NOT       speak to the Linux stop ordering under investigation
does NOT       show post-unmap DMA continuation
does NOT       establish the meaning of EPDISBLD or AHBIdle
does NOT       make A11 a "protection against failure to stop"
```

That last line corrects an earlier draft of this file. A11 reprograms the
address to prevent pointer drift accumulating, not to stop DMA. Reading it as a
quiescence mitigation was an over-reading, and the "three parties declined to
trust the controller" framing built on it does not survive.

## 6. What must be measured on hardware

```text
1  EPDISBLD / XferCompl ordering. Which rises first, and does XferCompl
   follow EPDISBLD after the timeout path? Directly tests whether the
   aborted transfer still completes.

2  AHBIdle and DMAReq sampled together. One positive reading of (1,1) is
   a binary refutation of AHBIdle sufficiency. (1,0) throughout the
   timeout window is weak evidence the other way.

3  Post-unmap DMA observation. Same request, same DMA address: capture
   any AHB or memory-side transaction to the retired IOVA after
   UNMAP_DONE.

4  IOMMU mode recorded on every run: strict, non-strict, direct or
   SWIOTLB.

5  Core reset behaviour after timeout: does a reset issued after the
   timeout path reach AHBIdle? Same boundary Fuchsia relies on.
```

Probes 1 and 2 are cheap mechanism discriminators. Probe 3 is the decisive
closure test: only a post-unmap transaction or fault tied to the same request and
retired mapping promotes the hypothesis. Results from probes 1 and 2 may explain
the mechanism, but do not by themselves close the security claim.

## 7. Scope limits

```text
nothing here moves DWC2 K_hw from UNDETERMINED
nothing here asserts DMA is active at unmap
DWC3 and chipidea rows stay sibling-driver documentation, not premises
usbliter8 and Fuchsia are used strictly within section 5
```

The only SOURCE-PROVEN claim this document adds is the ordering in section 1:
for a DWC2-mapped non-zero request, the timeout does not abort the path, and
unmap is reached without a positive endpoint-disabled acknowledgement.

## 8. Summary

| Claim | Class |
|---|---|
| Source-level chain to unmap | SOURCE-PROVEN |
| DMA active at unmap | UNKNOWN |
| Buffer DMA byte bound | removed |
| DDMA descriptor reuse reaches unmapped buffer | UNKNOWN |
| EPDISBLD without XferCompl implies DMA active | removed |
| Absence of an XferCompl wait as evidence | downgraded |
| CSftRst quoted as a DMA precondition | corrected, belongs to RxFFlsh |
| Core reset semantics | DOCUMENTED |
| Core reset as stronger quiescence boundary | ANALYTICAL |
| AHBIdle equals quiescence | UNKNOWN |
| Fuchsia as invariant corroboration | EXTERNAL, bounded |
| usbliter8 as consequence analogue | EXTERNAL, bounded |
| A11 as failure-to-stop protection | removed |
