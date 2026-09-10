# Hardware command runbooks

This index binds the procurement dependency graph to board-specific copy/paste command sequences. Acquisition order is controlled by [`HARDWARE-ACQUISITION-GATE.md`](HARDWARE-ACQUISITION-GATE.md); technical identity/specification is recorded in [`HARDWARE-PROFILES.md`](HARDWARE-PROFILES.md). These files do not authorize purchases.

## Current primary — Raspberry Pi Zero 2 W

Hardware profile and command file:

- [`hardware/PI-ZERO-2W-PROFILE.md`](hardware/PI-ZERO-2W-PROFILE.md)
- [`hardware/PI-ZERO-2W-COMMANDS.md`](hardware/PI-ZERO-2W-COMMANDS.md)
- local visual: [`hardware/images/pi-zero-2w-reference.svg`](hardware/images/pi-zero-2w-reference.svg)

First boot collects both cheap hardware facts in one configuration epoch:

```text
PI-FB1  DWC2 UDC + usable peripheral/operational state
PI-FB2  GHWCFG4.DESC_DMA + effective g_dma/g_dma_desc state
```

Then, only if the branch survives:

```text
PI-R1A -> PI-G25 -> conditional PI-G6
```

A decisive Pi result can eliminate the need for the next board.

## Deferred next board — ASUS Tinker Board S / RK3288

Hardware profile and command file:

- [`hardware/TINKER-BOARD-S-PROFILE.md`](hardware/TINKER-BOARD-S-PROFILE.md)
- [`hardware/TINKER-BOARD-S-COMMANDS.md`](hardware/TINKER-BOARD-S-COMMANDS.md)
- local visual: [`hardware/images/tinker-board-s-reference.svg`](hardware/images/tinker-board-s-reference.svg)

Do not execute as an acquisition plan until `AQ-D1` changes Tinker from `DEFERRED` to `JUSTIFIED`. Its runbook starts with:

```text
RK-FB0  running kernel/LPAE/SWIOTLB topology
RK-FB1  ff580000.usb DWC2 UDC + actual role
RK-FB2  GHWCFG4.DESC_DMA + effective gadget DMA parameters
RK-G25  actual DMA mapping classification
```

Only surviving topology-dependent work proceeds into `RK-R1/R2/R3`.

## Secondary boards

Firefly-RK3288, MiQi RK3288 and Radxa Rock 2 Square do not receive execution command files or full profiles yet because none is currently purchase-authorized. A board-specific profile/runbook is created when a live dependency makes that board `JUSTIFIED` or `SECONDARY-ONLY` under the acquisition gate. This prevents documentation itself from turning a candidate list into a shopping list.

## Evidence rule

Every board run creates a fresh boot/configuration artifact directory and hashes its captured files. A board's runtime topology is never inherited from another board or SoC family. Repository-local profile SVGs are identification aids only; photographs of the exact acquired unit are captured when hardware arrives.
