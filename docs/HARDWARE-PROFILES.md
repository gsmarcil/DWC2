# Hardware profiles

This index records the exact boards considered by the DWC2 campaign, their campaign role, technical specifications, local visual references, and the boundary between vendor facts, pinned-source facts, and runtime-pending facts.

Hardware purchase authority still comes only from [`HARDWARE-ACQUISITION-GATE.md`](HARDWARE-ACQUISITION-GATE.md).

## Active / acquired

### Raspberry Pi Zero 2 W

- Profile: [`hardware/PI-ZERO-2W-PROFILE.md`](hardware/PI-ZERO-2W-PROFILE.md)
- Commands: [`hardware/PI-ZERO-2W-COMMANDS.md`](hardware/PI-ZERO-2W-COMMANDS.md)
- Local visual: [`hardware/images/pi-zero-2w-reference.svg`](hardware/images/pi-zero-2w-reference.svg)
- Procurement state: `ACQUIRED / IN TRANSIT`
- Campaign role: first real DWC2 PRIMARY-A / R1A platform

## Deferred

### ASUS Tinker Board S / RK3288

- Profile: [`hardware/TINKER-BOARD-S-PROFILE.md`](hardware/TINKER-BOARD-S-PROFILE.md)
- Commands: [`hardware/TINKER-BOARD-S-COMMANDS.md`](hardware/TINKER-BOARD-S-COMMANDS.md)
- Local visual: [`hardware/images/tinker-board-s-reference.svg`](hardware/images/tinker-board-s-reference.svg)
- Procurement state: `DEFERRED`
- Campaign role: RK3288-specific topology / possible PRIMARY-B follow-on if `AQ-D1` authorizes it

## Visual provenance rule

Repository-local SVGs are **identification schematics**, not vendor photographs and not wiring/mechanical drawings. They exist so the repository remains self-contained and reviewable without silently copying vendor artwork.

For a board that is physically acquired, the exact test unit must later receive its own evidence photographs:

```text
photo-top.jpg
photo-bottom.jpg
physical-revision.txt
board-silkscreen.txt
```

Those arrival photographs supersede the schematic for physical identity. They do not replace vendor specifications or runtime topology evidence.

## Profile evidence rule

Every profile keeps these labels separate:

```text
VENDOR-SPEC
SOURCE-PROVEN
RUNTIME-PENDING
```

A marketing specification never promotes a runtime DMA/UDC fact, and a source-level topology fact never authorizes a hardware purchase by itself.
