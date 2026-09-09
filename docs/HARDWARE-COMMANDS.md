# Hardware command runbooks

This index binds the procurement dependency graph to board-specific copy/paste command sequences. Acquisition order is controlled by [`HARDWARE-ACQUISITION-GATE.md`](HARDWARE-ACQUISITION-GATE.md); these files do not authorize purchases.

## Current primary — Raspberry Pi Zero 2 W

Command file:

- [`hardware/PI-ZERO-2W-COMMANDS.md`](hardware/PI-ZERO-2W-COMMANDS.md)

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

Command file:

- [`hardware/TINKER-BOARD-S-COMMANDS.md`](hardware/TINKER-BOARD-S-COMMANDS.md)

Do not execute as an acquisition plan until `AQ-D1` changes Tinker from `DEFERRED` to `JUSTIFIED`. Its runbook starts with:

```text
RK-FB0  running kernel/LPAE/SWIOTLB topology
RK-FB1  ff580000.usb DWC2 UDC + actual role
RK-FB2  GHWCFG4.DESC_DMA + effective gadget DMA parameters
RK-G25  actual DMA mapping classification
```

Only surviving topology-dependent work proceeds into `RK-R1/R2/R3`.

## Secondary boards

Firefly-RK3288, MiQi RK3288 and Radxa Rock 2 Square do not receive execution command files yet because none is currently purchase-authorized. A board-specific command file is created only when a live dependency makes that board `JUSTIFIED` or `SECONDARY-ONLY` under the acquisition gate. This prevents documentation itself from turning a candidate list into a shopping list.

## Evidence rule

Every board run creates a fresh boot/configuration artifact directory and hashes its captured files. A board's runtime topology is never inherited from another board or SoC family.
