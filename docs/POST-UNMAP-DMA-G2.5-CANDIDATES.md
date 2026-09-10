# POST-UNMAP-DMA-001 — G2.5 candidate enumeration

## Scope and pin

This file is the first fail-closed enumeration of **named physical targets** for the
G2.5 matrix defined in `POST-UNMAP-DMA-G2.5.md`.

Linux source pin for controller/DT claims:

```text
f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
```

Candidate rows are not yet `TARGET_BUILD_ID`s because no exact campaign build has been
booted and frozen. Therefore every candidate currently carries:

```text
toolchain_id = PENDING_EXACT_BUILD
config_hash  = PENDING_EXACT_BUILD
dtb_hash     = PENDING_EXACT_BOOTED_DTB
```

No row reaches `G2.5 PASS` merely from board documentation, DTS source, a historical
kernel log, or a controller-family inference.

## Source-derived capability rules

At the pinned DWC2 source, gadget DMA defaults are derived from the hardware registers:

```text
dma_capable = hw.arch != GHWCFG2_SLAVE_ONLY_ARCH
p->g_dma = dma_capable
p->g_dma_desc = hw->dma_desc_enable
hw->dma_desc_enable = !!(GHWCFG4 & GHWCFG4_DESC_DMA)
```

Relevant register definitions at the same pin:

```text
GHWCFG2_SLAVE_ONLY_ARCH = 0
GHWCFG2_EXT_DMA_ARCH    = 1
GHWCFG2_INT_DMA_ARCH    = 2
GHWCFG4_DESC_DMA        = BIT(30)
GHWCFG4_DESC_DMA_DYN    = BIT(31)
```

Thus a named target's register dump is preferred over assumptions from SoC marketing.

## Campaign capability matrix — first pass

Legend:

```text
YES       source/runtime evidence supports the capability at controller/SoC level
NO        a discriminating hardware/source artifact kills the capability
UNKNOWN   evidence is insufficient; do not infer yes
PENDING   capability survives, but exact target-build/topology/rig gate is not frozen
```

| Board | Campaign | Arch | DWC2 gadget route | `supports_g_dma` | `supports_g_dma_desc` | `isoc_ep_available` | Capability verdict | Exact tuple |
|---|---|---:|---|---|---|---|---|---|
| ASUS Tinker Board S (RK3288) | PRIMARY-A | ARM32 | `ff580000.usb`, OTG enabled in mainline DTS | YES | YES | YES | **SURVIVES capability** | PENDING |
| ASUS Tinker Board S (RK3288) | PRIMARY-B | ARM32 | same DWC2 OTG controller | YES | YES | YES | **SURVIVES capability**; DDMA execution-risk note applies | PENDING |
| Firefly-RK3288 | PRIMARY-A | ARM32 | `ff580000.usb`, OTG enabled in mainline DTS | YES | YES | YES | **SURVIVES capability** | PENDING |
| Firefly-RK3288 | PRIMARY-B | ARM32 | same DWC2 OTG controller | YES | YES | YES | **SURVIVES capability**; DDMA execution-risk note applies | PENDING |
| Raspberry Pi Zero W (BCM2835) | PRIMARY-A | ARM32/ARMv6 | BCM2835 DWC2 OTG node + Zero-W OTG include | YES | NO | not needed for A | **SURVIVES capability** | PENDING |
| Raspberry Pi Zero W (BCM2835) | PRIMARY-B | ARM32/ARMv6 | same controller | YES | **NO** | not adjudicated | **KILLED_BY_HARDWARE_CAPABILITY** (`GHWCFG4.DESC_DMA=0`) | N/A |
| STM32MP157C-DK2 | PRIMARY-A | ARM32/Cortex-A7 | `st,stm32mp15-hsotg`, DWC2, role-switch enabled | UNKNOWN | UNKNOWN | UNKNOWN | **HOLD — hardware DMA register artifact required** | PENDING |
| STM32MP157C-DK2 | PRIMARY-B | ARM32/Cortex-A7 | same DWC2 HS OTG controller | UNKNOWN | UNKNOWN | UNKNOWN | **HOLD — GHWCFG2/GHWCFG4 + isoc capability required** | PENDING |

No `R2_ELIGIBLE=yes` is assigned in this table. The table only closes or retains the
controller/campaign-capability stage.

---

## Candidate 1 — ASUS Tinker Board S / RK3288

### Named-board and physical route

Pinned mainline identifies the board as:

```text
arch/arm/boot/dts/rockchip/rk3288-tinker-s.dts
model = "Rockchip RK3288 Asus Tinker Board S"
compatible = "asus,rk3288-tinker-s", "rockchip,rk3288"
```

It includes `rk3288-tinker.dtsi`; that board DTSI enables both the USB PHY and
`&usb_otg`. The RK3288 SoC DTS defines that controller as:

```text
usb_otg: usb@ff580000 {
    compatible = "rockchip,rk3288-usb", "rockchip,rk3066-usb", "snps,dwc2";
    dr_mode = "otg";
    ...
}
```

ASUS documentation independently confirms a physical device-side route: Tinker Board S
can be attached to a PC through its Micro-USB data connection and recognized by the PC.
This supports practical peripheral reachability but is not a substitute for the exact
campaign DTB.

### DMA/DDMA capability

An RK3288 DWC2 register dump for the `ff580000.usb` controller reports:

```text
GSNPSID = 0x4F54310A
GHWCFG4 = 0xDBF04030
```

At the pinned driver definitions:

```text
GHWCFG4 bit 30 = DESC_DMA = 1
GHWCFG4 bit 31 = DESC_DMA_DYN = 1
```

A Synopsys engineer explicitly interpreted that core as supporting descriptor DMA and
noted that it can switch between buffer DMA and descriptor DMA after core reset.
Therefore the RK3288 `ff580000` DWC2 core survives both the PRIMARY-A and PRIMARY-B
controller-capability predicates.

Historical RK3288 gadget testing also ran the standard UAC2 gadget in buffer DMA mode:

```text
g_dma=1
g_dma_desc=0
```

with isochronous traffic on `ff580000.usb`. This is corroboration for address-DMA and
isoc functionality at the RK3288 controller level.

### Important non-kill risk

The same historical UAC2 discussion says descriptor DMA was forcibly disabled because it
was causing problems on RK3288. This is **not** a capability kill — GHWCFG4 reports DDMA
support — but it is a PRIMARY-B execution-risk flag:

```text
rk3288_ddma_runtime_stability = RISK / MUST_RETEST_ON_EXACT_PIN
```

### Current verdict

```text
PRIMARY-A capability = SURVIVES
PRIMARY-B capability = SURVIVES
PRIMARY-B DDMA stability = OPEN / risk flagged

exact toolchain_id = PENDING
exact config_hash  = PENDING
exact dtb_hash     = PENDING
dma_path           = UNRESOLVED
dma_coherent       = UNRESOLVED
R2 eligible        = NO / NOT YET ADJUDICATED
```

### Fastest next artifacts

```text
1. exact booted DTB + sha256
2. exact .config + sha256
3. compiler/linker identity
4. DWC2 GSNPSID/GHWCFG2/GHWCFG4 dump from the actual board
5. resolved DT properties: dma-ranges / dma-coherent / iommus
6. boot/runtime evidence for SWIOTLB and IOMMU attachment
7. PRIMARY-A: host bus-reset trigger + active-request observer
8. PRIMARY-B: real isoc function bind + chain-start observer
9. PRIMARY-B: exact gadget.o/vmlinux OBJECT_GATE artifact
```

---

## Candidate 2 — Firefly-RK3288

Pinned mainline identifies:

```text
arch/arm/boot/dts/rockchip/rk3288-firefly.dts
model = "Firefly-RK3288"
compatible = "firefly,firefly-rk3288", "rockchip,rk3288"
```

Its common DTSI enables `&usbphy` and `&usb_otg`. The inherited RK3288 OTG controller is
the same `ff580000` DWC2 node described above.

Firefly's own documentation describes firmware transfer from a host through a Micro-USB
data cable, which corroborates a physical host-to-board USB device route.

Because this board is the same RK3288 SoC/controller family, the RK3288 register evidence
retains it as a **candidate** for both campaigns. This is a SoC/controller-level
capability transfer only; the exact physical Firefly board must still reproduce
`GSNPSID/GHWCFG2/GHWCFG4` before campaign admission.

```text
PRIMARY-A capability = SURVIVES, TARGET REGISTER RECONFIRM REQUIRED
PRIMARY-B capability = SURVIVES, TARGET REGISTER RECONFIRM REQUIRED
PRIMARY-B DDMA stability = OPEN / same RK3288 risk

toolchain_id = PENDING
config_hash  = PENDING
dtb_hash     = PENDING
dma_path     = UNRESOLVED
dma_coherent = UNRESOLVED
R2 eligible  = NO / NOT YET ADJUDICATED
```

Fastest next artifacts are the same exact-build/DTB/register/topology artifacts as for
Tinker Board S.

---

## Candidate 3 — Raspberry Pi Zero W / BCM2835

### Named-board and gadget route

Pinned mainline identifies:

```text
arch/arm/boot/dts/broadcom/bcm2835-rpi-zero-w.dts
model = "Raspberry Pi Zero W"
compatible = "raspberrypi,model-zero-w", "brcm,bcm2835"
```

The board includes `bcm283x-rpi-usb-otg.dtsi`, which sets the BCM2835 DWC2 node to OTG.
The SoC DTS also supplies a DMA translation window:

```text
soc {
    dma-ranges = <0x40000000 0x00000000 0x20000000>;
}
```

This `dma-ranges` source fact does **not** by itself prove direct-vs-SWIOTLB or coherency
for the exact campaign tuple.

Raspberry Pi documentation currently lists Zero/Zero W as gadget-capable through the
Micro-USB OTG/data port, corroborating practical peripheral-mode reachability.

### Discriminating hardware capability artifact

A Raspberry Pi Zero DWC2 hardware dump reports:

```text
GSNPSID = 0x4f54280a
GHWCFG2 = 0x228ddd50
GHWCFG4 = 0x1ff00020
```

Pinned DWC2 definitions decode:

```text
(GHWCFG2 >> 3) & 0x3 = 2 = GHWCFG2_INT_DMA_ARCH
GHWCFG4 & BIT(30) = 0
```

Therefore:

```text
supports_g_dma      = YES
supports_g_dma_desc = NO
```

This gives a real G2.5 kill for PRIMARY-B rather than an ambiguity:

```text
Pi Zero W / PRIMARY-B = KILLED_BY_HARDWARE_CAPABILITY
reason = descriptor DMA hardware bit absent
```

PRIMARY-A remains alive.

### Current verdict

```text
PRIMARY-A capability = SURVIVES
PRIMARY-B capability = KILLED

toolchain_id = PENDING
config_hash  = PENDING
dtb_hash     = PENDING
dma_path     = UNRESOLVED
dma_coherent = UNRESOLVED
R2-A eligible = NO / NOT YET ADJUDICATED
```

### Fastest next PRIMARY-A artifacts

```text
1. exact booted DTB/config/toolchain identities and hashes
2. actual-board GSNPSID/GHWCFG2/GHWCFG4 confirmation
3. resolve direct/SWIOTLB/IOMMU path from exact build + boot
4. resolve coherency/cache-maintenance semantics
5. host bus-reset trigger
6. active-request + UNMAP_DONE observer
```

No effort should be spent building a PRIMARY-B OBJECT_GATE for BCM2835 unless a different
physical revision produces a contradictory descriptor-DMA hardware register artifact.

---

## Candidate 4 — STM32MP157C-DK2

Pinned mainline identifies:

```text
arch/arm/boot/dts/st/stm32mp157c-dk2.dts
model = "STMicroelectronics STM32MP157C-DK2 Discovery Board"
compatible = "st,stm32mp157c-dk2", "st,stm32mp157"
```

The common DK DTSI enables the high-speed OTG controller:

```text
&usbotg_hs {
    phys = <&usbphyc_port1 0>;
    phy-names = "usb2-phy";
    usb-role-switch;
    status = "okay";
}
```

The SoC node is compatible with `st,stm32mp15-hsotg` and `snps,dwc2`. ST's board
specification describes a dual Cortex-A7 32-bit STM32MP157 with USB OTG HS and a USB
Type-C dual-role port.

However, the pinned STM32MP15 DWC2 platform parameter function does not hard-code
`g_dma` or `g_dma_desc`; it leaves those to the generic hardware auto-detection.
Without an exact `GHWCFG2/GHWCFG4` artifact from this controller, the campaign capability
must remain unknown.

```text
supports_g_dma      = UNKNOWN
supports_g_dma_desc = UNKNOWN
isoc_ep_available   = UNKNOWN
PRIMARY-A capability = HOLD
PRIMARY-B capability = HOLD
```

This candidate is attractive from a rig-control perspective, but **rig convenience must
not promote an unresolved R2 capability predicate**.

### Fastest killer/upgrade artifact

Before any canary, custom gadget, or OBJECT_GATE work:

```text
GSNPSID
GHWCFG2
GHWCFG4
```

from the actual DK2 DWC2 instance.

Then, only if DMA capability survives:

```text
exact DTB/config/toolchain hashes
resolved dma_path/coherency
PRIMARY-A reset stimulus
PRIMARY-B isoc endpoint/function/chain-start evidence
PRIMARY-B exact object gate
```

---

## Convenience ranking — deliberately after capability

All surviving first-pass candidates are 32-bit ARM boards, so the generic
`NET_IP_ALIGN=2` fallback is potentially useful. It is **not promoted** for any candidate
until the exact target build proves the effective preprocessor value.

```text
Tinker Board S       NET_IP_ALIGN = PENDING_EXACT_BUILD
Firefly-RK3288       NET_IP_ALIGN = PENDING_EXACT_BUILD
Raspberry Pi Zero W  NET_IP_ALIGN = PENDING_EXACT_BUILD
STM32MP157C-DK2      NET_IP_ALIGN = PENDING_EXACT_BUILD
```

Stock `u_ether` also requires the exact UDC behavior not to set
`quirk_avoids_skb_reserve`. Failure of that shortcut does not block a new-epoch custom
G6 canary.

## First-pass ranking

This ranking is for **next evidence acquisition**, not a claim of G2.5 PASS.

### PRIMARY-A

```text
1. ASUS Tinker Board S / RK3288
   - DWC2 OTG route explicit in pinned mainline
   - address DMA historically exercised on RK3288
   - physical device route documented
   - exact DMA topology still unresolved

2. Firefly-RK3288
   - same strong RK3288 DWC2 capability
   - OTG enabled in pinned mainline
   - exact-board register confirmation still required

3. Raspberry Pi Zero W / BCM2835
   - strongest discriminating hardware evidence: internal DMA yes, DDMA no
   - mature physical gadget route
   - PRIMARY-A only
   - exact topology/coherency still unresolved

4. STM32MP157C-DK2
   - excellent kernel/DTB and physical OTG prospects
   - but g_dma hardware capability is not yet closed by a register artifact
```

### PRIMARY-B

```text
1. ASUS Tinker Board S / RK3288
   - RK3288 GHWCFG4 says descriptor DMA supported
   - isochronous gadget activity historically observed
   - exact target object/topology/chain-start still pending
   - DDMA stability risk must be retested

2. Firefly-RK3288
   - same RK3288 controller capability
   - exact-board register reconfirmation required
   - same DDMA stability risk

3. STM32MP157C-DK2
   - HOLD until GHWCFG2/GHWCFG4 and isoc capability are measured

KILLED: Raspberry Pi Zero W
   - GHWCFG4.DESC_DMA = 0
```

## Fastest common acquisition script / artifact set

For every physical candidate that becomes available, collect these before custom gadget
work:

```text
BOARD_ID / serial label chosen for campaign
uname -a
/proc/config.gz or exact build .config
sha256(.config)
compiler + linker identities
exact booted DTB bytes
sha256(booted DTB)

DWC2:
  UDC name
  GSNPSID
  GHWCFG2
  GHWCFG4
  effective g_dma
  effective g_dma_desc

DMA topology:
  effective DT path to UDC
  dma-ranges
  dma-coherent presence/absence
  iommus property / attached IOMMU domain
  SWIOTLB boot/runtime state
```

For PRIMARY-A additionally collect host-triggered bus-reset reachability and the
active-request/UNMAP ordering observer.

For PRIMARY-B additionally collect endpoint capability, exact isoc gadget function,
chain-start evidence, and exact target `gadget.o`/`vmlinux` OBJECT_GATE artifact.

## Closure state after enumeration pass 1

```text
G2.5 candidate set                NON-EMPTY

PRIMARY-A capability survivors:
  ASUS Tinker Board S / RK3288
  Firefly-RK3288
  Raspberry Pi Zero W / BCM2835

PRIMARY-B capability survivors:
  ASUS Tinker Board S / RK3288
  Firefly-RK3288

PRIMARY-B hard kill:
  Raspberry Pi Zero W / BCM2835  (no descriptor DMA bit)

HOLD / insufficient hardware capability evidence:
  STM32MP157C-DK2 A
  STM32MP157C-DK2 B

named exact TARGET_BUILD_ID       NONE YET
DMA_TOPOLOGY_RESOLVED row         NONE YET
RIG_READY row                     NONE YET
G2.5 PASS                         NOT REACHED
```

## Evidence anchors

Pinned Linux source:

- `arch/arm/boot/dts/rockchip/rk3288-tinker-s.dts`
- `arch/arm/boot/dts/rockchip/rk3288-tinker.dtsi`
- `arch/arm/boot/dts/rockchip/rk3288.dtsi`
- `arch/arm/boot/dts/rockchip/rk3288-firefly.dts`
- `arch/arm/boot/dts/rockchip/rk3288-firefly.dtsi`
- `arch/arm/boot/dts/broadcom/bcm2835-rpi-zero-w.dts`
- `arch/arm/boot/dts/broadcom/bcm283x-rpi-usb-otg.dtsi`
- `arch/arm/boot/dts/broadcom/bcm2835.dtsi`
- `arch/arm/boot/dts/st/stm32mp157c-dk2.dts`
- `arch/arm/boot/dts/st/stm32mp15xx-dkx.dtsi`
- `drivers/usb/dwc2/params.c`
- `drivers/usb/dwc2/hw.h`

External corroboration used for candidate enumeration:

- ASUS Tinker Board S documentation / user manual:
  https://www.asus.com/es/networking-iot-servers/aiot-industrial-solutions/all-series/tinker-board-s/
- Firefly-RK3288 firmware/USB connection documentation:
  https://wiki.t-firefly.com/en/Firefly-RK3288/upgrade_firmware.html
- RK3288 DWC2 GHWCFG4/DDMA discussion:
  https://lists.infradead.org/pipermail/linux-rockchip/2018-February/019389.html
- RK3288 UAC2 buffer-DMA/isoc discussion:
  https://www.spinics.net/lists/linux-usb/msg174128.html
- Raspberry Pi Zero DWC2 hardware-register dump:
  https://lists.infradead.org/pipermail/linux-arm-kernel/2016-August/449668.html
- Raspberry Pi gadget-mode hardware guidance:
  https://www.raspberrypi.com/news/usb-gadget-mode-in-raspberry-pi-os-ssh-over-usb/
- ST STM32MP157C-DK2 product specification:
  https://www.st.com/en/evaluation-tools/stm32mp157c-dk2.html
