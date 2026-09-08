# Development environments (not DWC2 timing evidence)

These systems were useful for source builds, QEMU/KVM work and host-side tooling. Neither is a real DWC2 peripheral-mode target and therefore neither counts as runtime evidence for R1A.

## Host A — Ubuntu 24.04 workstation

Relevant surviving facts from the development audit:

- x86_64 Ubuntu host;
- xHCI controllers, no real DWC2 gadget UDC exposed through `/sys/class/udc`;
- DWC2 code present in the kernel configuration but no usable DWC2 peripheral hardware;
- raw gadget / FunctionFS support available;
- `dummy_hcd` absent in the tested configuration;
- QEMU/KVM available for development.

## Host B — Lenovo Y510p

- x86_64 Ubuntu host;
- xHCI/EHCI host controllers;
- no real DWC2 gadget peripheral controller;
- raw gadget / FunctionFS available;
- `dummy_hcd` absent in the tested configuration.

## Consequence

Results from either machine can validate tooling and host-side logic, but cannot establish DWC2 stop-timeout timing, quiescence, post-unmap DMA or any R1/R2/R3 runtime claim.
