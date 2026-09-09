# ASUS Tinker Board S / RK3288 — command runbook

Purpose: resolve the RK3288-specific DMA topology and any surviving PRIMARY-B / R1 blocker only if `AQ-D1` authorizes this board after Pi Zero 2 W evidence.

Do not execute this runbook merely because the source hypothesis survived. Tinker Board S remains `DEFERRED` until the acquisition gate changes it to `JUSTIFIED`.

## 0. Evidence directory

Keep one directory per boot/configuration.

```sh
set -eu
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$HOME/dwc2-tinker-s-$STAMP"
mkdir -p "$OUT"
printf '%s\n' "$OUT"
```

## 1. RK-FB0 — freeze the running kernel/topology

```sh
{
  date -u --iso-8601=seconds
  uname -a
  printf 'cmdline: '; cat /proc/cmdline
  printf 'model: '; tr -d '\0' </proc/device-tree/model 2>/dev/null || true; echo
  printf 'compatible:\n'; tr '\0' '\n' </proc/device-tree/compatible 2>/dev/null || true
  printf 'arch: '; uname -m
  printf 'meminfo:\n'; grep -E '^(MemTotal|HighTotal|LowTotal):' /proc/meminfo || true
} | tee "$OUT/platform.txt"

if [ -r /proc/config.gz ]; then
  zcat /proc/config.gz >"$OUT/kernel.config"
elif [ -r "/boot/config-$(uname -r)" ]; then
  cp "/boot/config-$(uname -r)" "$OUT/kernel.config"
else
  printf 'RUNNING_KERNEL_CONFIG_NOT_FOUND\n' | tee "$OUT/kernel-config.status"
fi

if [ -f "$OUT/kernel.config" ]; then
  grep -E '^(CONFIG_(ARM_LPAE|SWIOTLB|SWIOTLB_DYNAMIC|USB_DWC2|USB_DWC2_PERIPHERAL|USB_DWC2_DUAL_ROLE|DEBUG_FS|IOMMU_SUPPORT|ROCKCHIP_IOMMU)=|# CONFIG_(ARM_LPAE|SWIOTLB|SWIOTLB_DYNAMIC|ROCKCHIP_IOMMU) is not set)' \
    "$OUT/kernel.config" | tee "$OUT/kernel-relevant.config" || true
fi

cat /proc/iomem >"$OUT/iomem.txt" 2>/dev/null || true
```

`CONFIG_ARM_LPAE` is a topology input, not a cosmetic build option: record it from the running image.

## 2. RK-FB1 + RK-FB2 — capture DWC2 role and hardware capability in the same boot

```sh
sudo mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
sudo modprobe dwc2 2>"$OUT/modprobe-dwc2.err" || true

{
  echo '=== platform device candidates ==='
  ls -ld /sys/bus/platform/devices/ff580000.usb* 2>&1 || true
  for p in /sys/bus/platform/devices/ff580000.usb*; do
    [ -e "$p" ] || continue
    echo "=== $(basename "$p") ==="
    readlink -f "$p/driver" 2>/dev/null || true
    readlink -f "$p/of_node" 2>/dev/null || true
    readlink -f "$p/iommu_group" 2>/dev/null || true
  done
  echo
  echo '=== /sys/class/udc ==='
  ls -la /sys/class/udc 2>&1 || true
  for u in /sys/class/udc/*; do
    [ -e "$u" ] || continue
    echo "=== UDC: $(basename "$u") ==="
    readlink -f "$u" || true
    readlink -f "$u/device/driver" 2>/dev/null || true
    for f in state current_speed maximum_speed is_otg function uevent; do
      [ -r "$u/$f" ] && { echo "--- $f"; cat "$u/$f"; }
    done
  done
} | tee "$OUT/rk-fb1-udc-platform.txt"

DWC2_DIR=""
for d in /sys/kernel/debug/usb/*; do
  [ -d "$d" ] || continue
  if [ -r "$d/hw_params" ] && [ -r "$d/params" ]; then
    case "$(basename "$d")" in
      *ff580000*|*usb*) DWC2_DIR="$d"; break ;;
    esac
  fi
done

if [ -z "$DWC2_DIR" ]; then
  for d in /sys/kernel/debug/usb/*; do
    [ -d "$d" ] || continue
    if [ -r "$d/hw_params" ] && [ -r "$d/params" ]; then
      DWC2_DIR="$d"
      break
    fi
  done
fi

if [ -n "$DWC2_DIR" ]; then
  printf '%s\n' "$DWC2_DIR" | tee "$OUT/dwc2-debugfs-dir.txt"
  for f in dr_mode hw_params params regdump state; do
    [ -r "$DWC2_DIR/$f" ] && sudo cat "$DWC2_DIR/$f" >"$OUT/dwc2-$f.txt"
  done

  grep -E '(^|[[:space:]])(op_mode|arch|dma_desc_enable|g_dma|g_dma_desc)([[:space:]]|=)' \
    "$OUT/dwc2-hw_params.txt" "$OUT/dwc2-params.txt" 2>/dev/null \
    | tee "$OUT/rk-fb2-effective.txt" || true

  grep -Ei 'GHWCFG2|GHWCFG4' "$OUT/dwc2-regdump.txt" 2>/dev/null \
    | tee "$OUT/rk-fb2-hwcfg-raw.txt" || true

  GHWCFG4_HEX="$(grep -i 'GHWCFG4' "$OUT/dwc2-regdump.txt" 2>/dev/null \
      | grep -o '0x[0-9A-Fa-f]\+' | tail -n1 || true)"
  if [ -n "$GHWCFG4_HEX" ]; then
    printf 'GHWCFG4=%s\n' "$GHWCFG4_HEX" | tee "$OUT/rk-fb2-ghwcfg4.txt"
    printf 'GHWCFG4_DESC_DMA=%d\n' "$(( (GHWCFG4_HEX >> 30) & 1 ))" \
      | tee -a "$OUT/rk-fb2-ghwcfg4.txt"
  else
    printf 'GHWCFG4_NOT_CAPTURED\n' | tee "$OUT/rk-fb2-ghwcfg4.txt"
  fi
else
  printf 'DWC2_DEBUGFS_NOT_FOUND\n' | tee "$OUT/dwc2-debugfs-dir.txt"
fi
```

Interpretation:

```text
RK-FB1:
  ff580000.usb bound to dwc2 + usable peripheral role -> runtime branch survives
  role/UDC failure                                 -> diagnose this board before considering a secondary

RK-FB2:
  GHWCFG4.DESC_DMA = 0                            -> PRIMARY-B_ON_TINKER killed
  GHWCFG4.DESC_DMA = 1 + effective g_dma_desc=1   -> PRIMARY-B capability survives
```

A board-role failure is not authorization to buy Firefly. First determine whether it is a board configuration/DT/connector problem or a SoC-wide limitation.

## 3. RK-G25 stock-kernel topology capture

The source-level expectation is direct/non-IOMMU DMA with no bounce for the relevant 32-bit-addressable memory, but runtime evidence must decide it.

```sh
{
  echo '=== DMA/IOMMU/SWIOTLB dmesg ==='
  dmesg -T | grep -Ei 'software IO TLB|swiotlb|iommu|rockchip.*iommu|dma[-_ ]range|ff580000|dwc2' || true
  echo
  echo '=== ff580000 iommu group ==='
  for p in /sys/bus/platform/devices/ff580000.usb*; do
    [ -e "$p" ] || continue
    printf '%s -> ' "$p/iommu_group"
    readlink -f "$p/iommu_group" 2>/dev/null || echo NONE
  done
  echo
  echo '=== all iommu groups ==='
  find /sys/kernel/iommu_groups -maxdepth 2 -type l -print -exec readlink -f {} \; 2>/dev/null || true
} | tee "$OUT/rk-g25-runtime-topology.txt"

if command -v dtc >/dev/null 2>&1; then
  sudo dtc -I fs -O dts /sys/firmware/devicetree/base \
    >"$OUT/live.dts" 2>"$OUT/live-dtc.err" || true
  grep -nE 'ff580000|usb@ff580000|snps,dwc2|dma-ranges|iommus|memory@|reserved-memory' \
    "$OUT/live.dts" >"$OUT/live-dt-dma-usb-extract.txt" || true
else
  find /sys/firmware/devicetree/base \( -name dma-ranges -o -name iommus \) -print 2>/dev/null \
    | tee "$OUT/live-dt-dma-properties.txt" || true
fi
```

Also preserve the DWC2 device-tree node that the platform device is actually bound to:

```sh
for p in /sys/bus/platform/devices/ff580000.usb*; do
  [ -e "$p/of_node" ] || continue
  readlink -f "$p/of_node" | tee "$OUT/ff580000-of-node.txt"
  break
done
```

The following are corroboration, not the final per-mapping verdict:

```text
no IOMMU group
absence/presence of SWIOTLB boot messages
32-bit DMA mask expectation
live DT dma-ranges state
```

The decisive `RK-G25` artifact remains an actual DWC2 request mapping.

## 4. RK-G25 evidence-bearing mapping observer — implementation gate

Do not build an out-of-tree observer until section 1 establishes the exact running configuration. Required semantic fields are:

```text
cpu_va
cpu_phys
dma_addr
translated_dma_phys
dma backend / ops state
iommu attachment
dma_mask
bus_dma_limit
active dma-ranges context
bounce_membership
bounce_membership_method
```

Classification contract:

```text
backend=dma-direct
cpu_phys == translated_dma_phys
bounce_membership=false
    -> DIRECT_NO_BOUNCE

bounce_membership=true
    -> SWIOTLB_BOUNCE

raw dma_addr != cpu_phys
translated_dma_phys == cpu_phys
bounce_membership=false
    -> BUS_TRANSLATION_NO_BOUNCE
```

Do not use raw address inequality as a bounce detector.

Before choosing a loadable-module implementation, preserve the kernel build facts needed to test helper linkage:

```sh
{
  uname -r
  test -d "/lib/modules/$(uname -r)/build" && echo BUILD_TREE_PRESENT || echo BUILD_TREE_MISSING
  grep -E '^(CONFIG_(SWIOTLB|SWIOTLB_DYNAMIC|MODVERSIONS|MODULES|DEBUG_INFO|KALLSYMS)=|# CONFIG_(SWIOTLB|SWIOTLB_DYNAMIC) is not set)' \
    "$OUT/kernel.config" 2>/dev/null || true
} | tee "$OUT/rk-g25-observer-build-preflight.txt"
```

If the needed SWIOTLB-membership helper resolves to a non-exported internal symbol for this exact build, move the observer in-tree rather than weakening the artifact contract.

## 5. RK-R1 / R2 / R3

Only after `RK-FB0/1/2` and `RK-G25` establish the board's actual capability should topology-dependent campaign work start.

Repository-side gate on the development host:

```sh
cd /path/to/DWC2
./VERIFY-REPOSITORY.sh
```

For R1A use `docs/RUNTIME-RUNBOOK.md`. Do not treat a Tinker result as evidence for Pi, or vice versa; each platform gets its own configuration fingerprint and epoch artifacts.

For R2, identity must close across request -> mapping -> `UNMAP_DONE` -> retired range -> post-unmap device access. For R3, use a completed memory-side effect; a fault alone is not `D_commit`.

## 6. G6 canary rule on RK3288

If G6 becomes relevant, keep the canary inside the DMA-mapped allocation and after the logical request boundary. Align the logical boundary to a cache-line boundary and dedicate full cache line(s) to the canary. Record the actual cache-line size used by the test rather than assuming one from SoC marketing material.

Useful runtime observations:

```sh
getconf LEVEL1_DCACHE_LINESIZE 2>/dev/null | tee "$OUT/l1-dcache-line-userspace.txt" || true
cat /sys/devices/system/cpu/cpu0/cache/index0/coherency_line_size 2>/dev/null \
  | tee "$OUT/l1-dcache-line-sysfs.txt" || true
```

## 7. Finalize the boot artifact bundle

```sh
(
  cd "$OUT"
  find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
printf 'TINKER_S_BOOT_ARTIFACTS=%s\n' "$OUT"
```

## Stop conditions before any RK3288 secondary purchase

```text
Tinker produces the decisive required artifact
    -> stop buying RK3288 boards.

The surviving claim no longer depends on hardware
    -> stop buying.

Tinker failure is explained by an RK3288-wide/source invariant
    -> do not buy Firefly/MiQi/Rock2 for the same question.

Only a demonstrated board-specific ambiguity remains, and a second RK3288 board can decide it
    -> one SECONDARY-ONLY board may be evaluated under AQ-D2.
```
