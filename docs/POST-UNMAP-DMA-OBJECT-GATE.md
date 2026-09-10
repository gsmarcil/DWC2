# POST-UNMAP-DMA-001 — PRIMARY-B exact OBJECT_GATE

## Purpose

This gate resolves only the C/object-code boundary in the DDMA-isoc dequeue branch.
It does **not** prove `K_hw`, `D_issue`, `D_commit`, or security impact.

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

Source proves:

```text
A: descriptor publication
   desc->buf = request DMA address
   desc->status = HREADY
   desc_list_dma -> DIEPDMA/DOEPDMA
   EPENA | CNAK

B: no software retirement around U
   ep_dequeue -> complete_request -> dma_unmap
   no descriptor clear
   no descriptor status rewrite
   no next_desc adjustment
   no compl_desc adjustment
   DDMA-isoc complete_request returns after giveback

enabler source fact
   offsetof(struct dwc2_hsotg_req, req) == 0
```

The remaining target-object question is the lowering of:

```c
if (req == &hs_ep->req->req)
        dwc2_hsotg_ep_stop_xfr(...);

dwc2_hsotg_complete_request(...);
```

The zero member offset explains why a compiler can compare the value loaded from
`hs_ep->req` directly against the `req` argument. Exact campaign closure is still
bound to the final target object/image, architecture, compiler, flags, and config.

## Pattern-level result — closed but deliberately narrow

A layout-matched reproducer was compiled with:

```text
architecture  x86-64
compiler      gcc 13.3
optimization  -O2
layout        struct usb_request req is first member / offset 0
```

Observed control-flow shape:

```asm
call  on_list
testl %eax, %eax
je    <not-on-list>
cmpq  %rbp, 16(%rbx)   # load hs_ep->req value and compare directly with req
je    <stop-path>
                        # otherwise continue to completion path
```

The same pattern was observed with and without `-fdelete-null-pointer-checks`.
The pinned kernel Makefile adds `-fno-delete-null-pointer-checks`; that flag is
therefore not treated as the carrier of the result.

Frozen classification:

```text
PRIMARY-B enabler
  offsetof(struct dwc2_hsotg_req, req) == 0   SOURCE-PROVEN
  silent-skip codegen pattern                 PATTERN-PROVEN
      scope: x86-64 / gcc 13.3 / -O2 layout reproducer
  target campaign object                      PENDING_OBJECT_GATE
```

`PATTERN-PROVEN` is not `OBJECT-PROVEN` and must not be generalized to another
architecture, toolchain, LTO mode, or target config.

## Exact target artifact selection

The artifact must correspond to the named G2.5 target and evidence epoch.

```text
non-LTO build:
    drivers/usb/dwc2/gadget.o is admissible
    final vmlinux/module is also admissible

LTO build:
    pre-link gadget.o is NOT admissible
    use final linked vmlinux or the final linked module containing DWC2
```

Reason: with LTO, pre-link IR/object code need not reflect final code generation.

The exact gate build must carry debug/source mapping (`-g` or equivalent debug-info
configuration) so the machine instructions can be tied to the `ep_dequeue` source
condition rather than guessed from addresses.

Preferred inspection:

```bash
objdump -dS --disassemble=dwc2_hsotg_ep_dequeue <artifact>
```

or an architecture-matched equivalent such as cross-`objdump`, `llvm-objdump -dS`,
or `gdb disassemble /s`.

## Capture procedure

Run the repository capture tool first:

```bash
python3 tools/capture_ep_dequeue_object_gate.py selftest

python3 tools/capture_ep_dequeue_object_gate.py capture \
  <gadget.o-or-final-linked-image> \
  --out artifacts/post-unmap-dma/object-gate-primary-b \
  --gadget-source <linux>/drivers/usb/dwc2/gadget.c \
  --config <linux>/.config \
  --epoch-id <new-epoch-id> \
  --board-id <named-g2.5-board> \
  --kernel-commit f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8 \
  --compiler-identity "$(<compiler> --version | head -1)"
```

For a cross target, pass the matching disassembler explicitly, for example:

```text
--objdump arm-linux-gnueabihf-objdump
--objdump aarch64-linux-gnu-objdump
--objdump llvm-objdump
```

The tool records object SHA256, config SHA256, compiler identity, objdump identity,
board/epoch identity, LTO state from config, and source-interleaved disassembly.
It refuses a pre-link `.o` when LTO is enabled and refuses closure capture when
source context cannot be recovered.

The capture result remains:

```text
CAPTURED_NOT_ADJUDICATED
```

Capture success is not OBJECT_GATE success.

## Pre-registered falsifier

The gate is deliberately two-sided.

### OBJECT-PROVEN

Promote only when the exact named-target artifact establishes all of:

```text
1. load hs_ep->req pointer value
2. compare that value with the req argument
3. retain a conditional branch separating stop from skip-stop
4. no memory read through the loaded hs_ep->req value before the comparison
5. hs_ep->req == NULL path reaches complete_request/U without executing stop
```

Equivalent register allocation/instruction selection is allowed. The semantic
predicate matters, not literal opcode spelling.

### KILLED

Kill the silent-skip model if any of these is established on the exact artifact:

```text
A. memory is read through hs_ep->req before the comparison
   -> NULL becomes a faulting path, not a silent skip

B. the comparison is folded to a constant in a way that removes the proposed
   NULL conditional behavior

C. the stop sequence executes unconditionally on the NULL path
```

### INDETERMINATE

```text
source/line mapping unavailable
object/config/compiler identity incomplete
LTO build inspected only at pre-link .o
control flow cannot be recovered from the final linked image
```

`INDETERMINATE` must never be promoted to PASS.

## Inlining warning — do not search only for a call

`dwc2_hsotg_ep_stop_xfr()` is `static` and may be inlined at optimization time.
Therefore this is **not** a valid adjudication rule:

```text
no call dwc2_hsotg_ep_stop_xfr -> stop branch absent
```

The stop arm must be recognized by either:

```text
retained call to dwc2_hsotg_ep_stop_xfr
```

or the inlined register sequence corresponding to:

```text
SNAK / SGNPINNAK or SGOUTNAK
wait for NAK-effective state
EPDIS | SNAK
wait for EPDISBLD
```

This prevents a false PASS caused only by function inlining.

## Scope of an OBJECT-PROVEN result

A successful exact gate promotes only:

```text
PRIMARY-B skip-stop execution = OBJECT-PROVEN
```

and is qualified by:

```text
board_id
architecture
compiler + version
compiler flags / config
LTO state
kernel commit
gadget.c identity
exact object/linked-image SHA256
epoch_id
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

## DDMA identity-drift side track

Keep the identity issue separate from the post-unmap claim:

```text
hardware completion identity  = compl_desc / descriptor slot
software completion identity  = get_ep_head(hs_ep)
```

`ep_dequeue` removes a request from the software queue while not adjusting
`compl_desc` or retiring the corresponding descriptor. The source therefore
establishes a descriptor/queue identity asymmetry, but a concrete wrong-request
association remains a separate reachability proof.

For G4, never derive `same_mapping_identity` merely from queue order after a
DDMA-isoc dequeue. Runtime evidence must bind descriptor slot, DMA address,
mapping ID, request ID, dequeue sequence, and epoch explicitly.

## Current state

```text
PRIMARY-A reset/disconnect   SOURCE-PROVEN ordering; K_hw OPEN

PRIMARY-B DDMA-isoc dequeue
  A                          SOURCE-PROVEN
  B                          SOURCE-PROVEN
  zero-offset enabler        SOURCE-PROVEN
  x86-64/gcc13.3 pattern     PATTERN-PROVEN
  named target object        PENDING_OBJECT_GATE
  K_hw                       OPEN

R2 / D_issue                 UNKNOWN
R3 / D_commit                UNKNOWN
security impact              UNKNOWN
```