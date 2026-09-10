# Raspberry Pi Zero 2 W — command runbook

Purpose: obtain the cheapest decisive DWC2 artifacts before any further hardware purchase. This file is board-specific; none of its DMA-topology conclusions transfer to RK3288.

The logical decision order is `PI-FB1 -> PI-FB2 -> PI-R1A -> PI-G25 -> conditional PI-G6`, but `PI-FB1` and `PI-FB2` should be captured in the same first boot.

## 0. Evidence directory

Run as a normal user with `sudo` available. Keep one directory per boot so evidence from different configurations cannot be mixed.

```sh
set -eu
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$HOME/dwc2-pi-zero-2w-$STAMP"
mkdir -p "$OUT"
printf '%s\n' "$OUT"
```

## 1. Freeze the running platform before changing anything

```sh
{
  date -u --iso-8601=seconds
  uname -a
  printf 'cmdline: '; cat /proc/cmdline
  printf 'model: '; tr -d '\0' </proc/device-tree/model 2>/dev/null || true; echo
  printf 'compatible:\n'; tr '\0' '\n' </proc/device-tree/compatible 2>/dev/null || true
  printf 'arch: '; uname -m
} | tee "$OUT/platform.txt"

if [ -r /proc/config.gz ]; then
  zcat /proc/config.gz >"$OUT/kernel.config"
elif [ -r "/boot/config-$(uname -r)" ]; then
  cp "/boot/config-$(uname -r)" "$OUT/kernel.config"
elif [ -r "/boot/firmware/config-$(uname -r)" ]; then
  cp "/boot/firmware/config-$(uname -r)" "$OUT/kernel.config"
else
  printf 'RUNNING_KERNEL_CONFIG_NOT_FOUND\n' | tee "$OUT/kernel-config.status"
fi

if [ -f "$OUT/kernel.config" ]; then
  grep -E '^(CONFIG_(USB_DWC2|USB_DWC2_PERIPHERAL|USB_DWC2_DUAL_ROLE|DEBUG_FS|SWIOTLB|SWIOTLB_DYNAMIC|ARM_LPAE|IOMMU_SUPPORT)=|# CONFIG_(SWIOTLB|SWIOTLB_DYNAMIC|ARM_LPAE) is not set)' \
    "$OUT/kernel.config" | tee "$OUT/kernel-relevant.config" || true
fi
```

This step is evidence only. Do not infer ARM32/LPAE from the board model; record the kernel that actually booted.

## 2. PI-FB1 + PI-FB2 — first-boot zero-cost capture

Mount debugfs if available, then collect UDC state and the DWC2 hardware/parameter view.

```sh
sudo mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
sudo modprobe dwc2 2>"$OUT/modprobe-dwc2.err" || true

{
  echo '=== /sys/class/udc ==='
  ls -la /sys/class/udc 2>&1 || true
  echo
  for u in /sys/class/udc/*; do
    [ -e "$u" ] || continue
    echo "=== UDC: $(basename "$u") ==="
    readlink -f "$u" || true
    readlink -f "$u/device/driver" 2>/dev/null || true
    for f in state current_speed maximum_speed is_otg function uevent; do
      [ -r "$u/$f" ] && { echo "--- $f"; cat "$u/$f"; }
    done
  done
} | tee "$OUT/udc.txt"

find /sys/kernel/debug/usb -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null \
  | tee "$OUT/debugfs-usb-dirs.txt" || true

DWC2_DIR=""
for d in /sys/kernel/debug/usb/*; do
  [ -d "$d" ] || continue
  if [ -r "$d/hw_params" ] && [ -r "$d/params" ]; then
    DWC2_DIR="$d"
    break
  fi
done

if [ -n "$DWC2_DIR" ]; then
  printf '%s\n' "$DWC2_DIR" | tee "$OUT/dwc2-debugfs-dir.txt"
  for f in dr_mode hw_params params regdump state; do
    if [ -r "$DWC2_DIR/$f" ]; then
      sudo cat "$DWC2_DIR/$f" >"$OUT/dwc2-$f.txt"
    fi
  done

  grep -E '(^|[[:space:]])(op_mode|arch|dma_desc_enable|g_dma|g_dma_desc)([[:space:]]|=)' \
    "$OUT/dwc2-hw_params.txt" "$OUT/dwc2-params.txt" 2>/dev/null \
    | tee "$OUT/pi-fb2-effective.txt" || true

  grep -Ei 'GSNPSID|GHWCFG1|GHWCFG2|GHWCFG3|GHWCFG4' \
    "$OUT/dwc2-regdump.txt" 2>/dev/null \
    | tee "$OUT/pi-controller-signature-raw.txt" || true

  if ! grep -qi 'GSNPSID' "$OUT/pi-controller-signature-raw.txt" || \
     ! grep -qi 'GHWCFG1' "$OUT/pi-controller-signature-raw.txt" || \
     ! grep -qi 'GHWCFG2' "$OUT/pi-controller-signature-raw.txt" || \
     ! grep -qi 'GHWCFG3' "$OUT/pi-controller-signature-raw.txt" || \
     ! grep -qi 'GHWCFG4' "$OUT/pi-controller-signature-raw.txt"; then
    printf 'CONTROLLER_SIGNATURE_INCOMPLETE\n' | tee "$OUT/pi-controller-signature.status"
  else
    printf 'CONTROLLER_SIGNATURE_COMPLETE\n' | tee "$OUT/pi-controller-signature.status"
  fi

  GHWCFG4_HEX="$(grep -i 'GHWCFG4' "$OUT/dwc2-regdump.txt" 2>/dev/null \
      | grep -o '0x[0-9A-Fa-f]\+' | tail -n1 || true)"
  if [ -n "$GHWCFG4_HEX" ]; then
    printf 'GHWCFG4=%s\n' "$GHWCFG4_HEX" | tee "$OUT/pi-fb2-ghwcfg4.txt"
    printf 'GHWCFG4_DESC_DMA=%d\n' "$(( (GHWCFG4_HEX >> 30) & 1 ))" \
      | tee -a "$OUT/pi-fb2-ghwcfg4.txt"
  else
    printf 'GHWCFG4_NOT_CAPTURED\n' | tee "$OUT/pi-fb2-ghwcfg4.txt"
  fi
else
  printf 'DWC2_DEBUGFS_NOT_FOUND\n' | tee "$OUT/dwc2-debugfs-dir.txt"
fi
```

Interpretation:

```text
PI-FB1:
  usable DWC2 UDC + usable peripheral state -> continue toward PI-R1A
  no usable UDC                           -> Pi runtime branch blocked for this configuration

PI-FB2:
  GHWCFG4.DESC_DMA = 0                   -> PRIMARY-B_ON_PI killed only
  GHWCFG4.DESC_DMA = 1 + g_dma_desc=1    -> PRIMARY-B capability survives on Pi
```

`GHWCFG4.DESC_DMA` is bit 30. Keep the raw register dump as the primary artifact, not only the decoded value. For reset/databook work, the load-bearing controller match key is the same-epoch raw tuple `{GSNPSID, GHWCFG1, GHWCFG2, GHWCFG3, GHWCFG4}`; `GSNPSID` alone is never sufficient.

## 3. Role/overlay diagnosis only if PI-FB1 is blocked

First inspect the active firmware configuration; do not append an overlay blindly.

```sh
CFG=""
for f in /boot/firmware/config.txt /boot/config.txt; do
  [ -r "$f" ] && { CFG="$f"; break; }
done

if [ -n "$CFG" ]; then
  printf 'firmware_config=%s\n' "$CFG" | tee "$OUT/firmware-config-path.txt"
  grep -nE '(^|[[:space:]])dtoverlay=dwc2|dr_mode|otg_mode' "$CFG" \
    | tee "$OUT/dwc2-overlay-existing.txt" || true
else
  printf 'RASPBERRY_PI_FIRMWARE_CONFIG_NOT_FOUND\n' | tee "$OUT/firmware-config-path.txt"
fi

dmesg -T | grep -Ei 'dwc2|usb.*role|otg|udc|software IO TLB|swiotlb|iommu' \
  | tee "$OUT/dmesg-dwc2-topology.txt" || true
```

If the image uses Raspberry Pi firmware overlays and the only blocker is absence of the DWC2 peripheral overlay, use a separate configuration epoch. Back up the file first:

```sh
# Run only after inspecting the previous block and confirming the image uses this file.
# CFG=/boot/firmware/config.txt   # or /boot/config.txt, as discovered above
sudo cp -a "$CFG" "$CFG.pre-dwc2-campaign"
printf '\n# DWC2 campaign epoch\ndtoverlay=dwc2,dr_mode=peripheral\n' | sudo tee -a "$CFG"
sudo reboot
```

After reboot, start a NEW `$OUT` directory and repeat sections 1-2. Never merge pre-overlay and post-overlay evidence into one epoch.

## 4. PI-G25 — topology preflight available without a custom observer

This does not yet classify an individual request mapping. It freezes all stock-kernel facts needed to choose the correct observer implementation.

```sh
{
  echo '=== DMA/IOMMU-relevant dmesg ==='
  dmesg -T | grep -Ei 'software IO TLB|swiotlb|iommu|dma[-_ ]range|dwc2' || true
  echo
  echo '=== IOMMU groups ==='
  find /sys/kernel/iommu_groups -maxdepth 2 -type l -print -exec readlink -f {} \; 2>/dev/null || true
} | tee "$OUT/pi-g25-runtime-topology.txt"

if command -v dtc >/dev/null 2>&1; then
  sudo dtc -I fs -O dts /sys/firmware/devicetree/base \
    >"$OUT/live.dts" 2>"$OUT/live-dtc.err" || true
  grep -nE 'dma-ranges|iommus|usb@|dwc2|snps,dwc2' "$OUT/live.dts" \
    >"$OUT/live-dt-dma-usb-extract.txt" || true
else
  find /sys/firmware/devicetree/base -name dma-ranges -o -name iommus 2>/dev/null \
    | tee "$OUT/live-dt-dma-properties.txt" || true
fi
```

Do NOT classify a request as bounced merely because `req->dma != cpu_phys`. On BCM platforms a bus translation may account for that difference. The evidence-bearing PI-G25 observer must record:

```text
cpu_va
cpu_phys
dma_addr
translated_dma_phys
dma backend / ops state
iommu attachment
dma mask / bus limit
active dma-ranges context
bounce_membership
bounce_membership_method
```

The exact helper/API used for `translated_dma_phys` and SWIOTLB membership is selected only after the running kernel configuration and module-linkage constraints are known.

## 5. PI-R1A

Do not start an evidence-bearing R1A batch until the repository's campaign readiness gate is green and the exact executing observer/harness epoch is frozen. Then follow `docs/RUNTIME-RUNBOOK.md` rather than improvising commands here.

Quick repository-side precondition check on the development host:

```sh
cd /path/to/DWC2
./VERIFY-REPOSITORY.sh
```

A nonzero exit remains fail-closed. It is not permission to run a negative R1A campaign with incomplete witnesses.

## 6. PI-G6

Run only if the relevant primitive survives and the mapping/ownership model is established. The canary must be inside the DMA-mapped allocation but after the logical request boundary, with the logical boundary and canary isolated on full cache-line boundaries. Do not use a canary outside the mapped range as a completed-effect artifact.

## 7. Finalize the boot artifact bundle

```sh
(
  cd "$OUT"
  find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
printf 'PI_ZERO_2W_BOOT_ARTIFACTS=%s\n' "$OUT"
```

## Stop conditions before another purchase

```text
R1 primitive decisively killed on valid Pi evidence
    -> do not buy Tinker for that primitive.

Pi supplies all evidence needed for the surviving claim
    -> do not buy Tinker.

Pi leaves a specifically named topology/descriptor-DMA blocker that RK3288 can decide
    -> evaluate AQ-D1; Tinker may become JUSTIFIED.

Pi-specific role/capability failure
    -> do not generalize the failure to RK3288.
```
