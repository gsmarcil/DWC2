# POST-UNMAP-DMA-001 — PRIMARY-B exact OBJECT_GATE

## Purpose

This gate exists only to resolve the C/object-code boundary in the DDMA-isoc dequeue branch.
It does **not** attempt to prove `K_hw`, `D_issue`, `D_commit`, or security impact.

The source-side facts are already frozen:

```text
Linux pin
f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8

drivers/usb/dwc2/gadget.c
sha256 baf17cb89e78c8a63f0a9688af7697875018f162923118f72f1092df703f6d8d

PRIMARY-B prerequisites
g_dma      = 1
g_dma_desc = 1
endpoint   = isochronous
chain_started = yes
```

For the DDMA-isoc path, source proves:

```text
A: descriptor publication
   desc->buf = request DMA address
   desc->status = HREADY
   desc_list_dma -> DIEPDMA/DOEPDMA
   EPENA | CNAK

B: no software retirement before U
   ep_dequeue -> complete_request -> dma_unmap
   no descriptor clear
   no descriptor status rewrite
   no next_desc adjustment
   no compl_desc adjustment
   DDMA-isoc complete_request returns after giveback
```

The remaining object-level question is the lowering of:

```c
if (req == &hs_ep->req->req)
        dwc2_hsotg_ep_stop_xfr(...);

dwc2_hsotg_complete_request(...);
```

`struct dwc2_hsotg_req::req` is the first member, so its source offset is zero.  When
`hs_ep->req == NULL`, however, `&hs_ep->req->req` is still a null-derived member-address
expression in C.  The source alone must therefore not be used to claim the actual machine
control flow.

## Exact closure artifact

The only admissible OBJECT_GATE closure artifact is generated from the exact campaign
kernel object or linked image for the new evidence epoch.

Required identity:

```text
epoch_id
kernel commit
exact gadget.c SHA256
exact object/vmlinux SHA256
kernel config SHA256
compiler identity
objdump identity
architecture / object format
symbolized disassembly of dwc2_hsotg_ep_dequeue
```

Capture it with:

```bash
python3 tools/capture_ep_dequeue_object_gate.py selftest

python3 tools/capture_ep_dequeue_object_gate.py capture \
  <path-to-gadget.o-or-vmlinux> \
  --out artifacts/post-unmap-dma/object-gate-primary-b \
  --gadget-source <linux>/drivers/usb/dwc2/gadget.c \
  --config <linux>/.config \
  --epoch-id <new-epoch-id> \
  --kernel-commit f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8 \
  --compiler-identity "$(<compiler> --version | head -1)"
```

For a cross-built ARM target, pass the matching disassembler explicitly when required,
for example `--objdump arm-linux-gnueabihf-objdump` or `--objdump llvm-objdump`.

The capture tool intentionally emits:

```text
CAPTURED_NOT_ADJUDICATED
```

It refuses a wrong `gadget.c` hash, missing object, missing function symbol, failed
disassembler invocation, or pre-existing output directory.  Failed captures do not leave
a completed artifact directory.

## OBJECT_GATE PASS

`PRIMARY-B` may cross the object gate only if the exact disassembly proves the following
control-flow predicate:

```text
hs_ep->req == NULL
    -> evaluation of the comparison does not perform a faulting memory access through NULL
    -> branch does not call/reach dwc2_hsotg_ep_stop_xfr
    -> control reaches dwc2_hsotg_complete_request
    -> U remains reachable
```

Equivalent optimized or inlined code is acceptable only when the same control flow is
recoverable from the exact linked image.  If LTO/inlining removes the standalone symbol,
that is **not PASS**; capture/adjudication must move to the exact linked call site.

A successful object gate promotes only:

```text
PRIMARY-B skip-stop execution = OBJECT-PROVEN
```

It does not promote:

```text
hardware still owns/fetches descriptor at U
post-unmap DMA issue
post-unmap DMA commit
memory corruption
security impact
```

Those remain `K_hw` / G3 / G4 / G6 questions.

## OBJECT_GATE FAIL / INDETERMINATE

```text
FAIL
    exact machine path faults before complete_request/U
    or exact machine path necessarily reaches ep_stop_xfr

INDETERMINATE
    symbol/call site cannot be recovered with identity
    disassembly is insufficient to establish the NULL path
    object/config/compiler identity is incomplete
    LTO/inlining changed the shape and linked-site proof was not captured
```

`INDETERMINATE` must never be promoted to PASS.

## Preliminary compiler characterization — not closure

A local control reproducer with the same zero-offset member pattern was compiled only to
estimate whether the proposed silent-skip lowering is plausible.  These results are
**not campaign evidence** and are not bound to a target board, target config, or target
kernel object.

Observed locally:

```text
GCC 14.2.0, x86_64, -O2
    compares req directly against the pointer value loaded from ep->req
    no second dereference through that loaded pointer before the branch

Clang 17.0.0, x86_64, -O2
    same shape

Clang 17.0.0, armv7-linux-gnueabihf, -O2
    ldr r2, [r0]
    cmp r2, r1
    bne skip_stop

Clang 17.0.0, aarch64-linux-gnu, -O2
    ldr x8, [x0]
    cmp x8, x1
    b.ne skip_stop
```

These observations strengthen the case for running the exact OBJECT_GATE but do not
replace it.

## DDMA identity-drift side track

Keep the identity issue separate from the post-unmap claim:

```text
hardware completion identity  = compl_desc / descriptor slot
software completion identity  = get_ep_head(hs_ep)
```

`ep_dequeue` removes a request from the software queue while not adjusting `compl_desc` or
retiring the corresponding descriptor.  Therefore the source establishes a descriptor/
queue identity asymmetry, but a concrete wrong-request association remains a separate
reachability proof.

For G4, never derive `same_mapping_identity` merely from queue order after a DDMA-isoc
dequeue.  The runtime artifact must bind descriptor slot, DMA address, mapping ID, request
ID, and epoch explicitly.

## Current state

```text
PRIMARY-A reset/disconnect   SOURCE-PROVEN ordering; K_hw OPEN
PRIMARY-B DDMA-isoc dequeue  A SOURCE-PROVEN
                             B SOURCE-PROVEN
                             zero-offset enabler SOURCE-PROVEN
                             silent skip EXACT OBJECT_GATE OPEN
                             K_hw OPEN

R2 / D_issue                 UNKNOWN
R3 / D_commit                UNKNOWN
security impact              UNKNOWN
```
