# POST-UNMAP-DMA-001 — G0.5 DMA-API-debug gate

This gate is intentionally run **before** building a custom gadget workload.
It asks a narrower question than the post-unmap DMA hypothesis:

> Does Linux's `CONFIG_DMA_API_DEBUG` observe a DMA-API contract violation from
> the driver during an already-available DWC2 exercise window?

It does **not** prove that hardware cannot DMA after `dma_unmap_*()`. A driver can
call the DMA API in a formally valid order while the controller still performs a
late transaction; that requires later IOMMU/hardware/runtime evidence.

## Admission states

`tools/dma_api_debug_gate.py probe` returns one of:

- `READY` — `CONFIG_DMA_API_DEBUG=y`, `dma-api/` is accessible, and debugging is active.
- `BLOCKED_CONFIG` — the running kernel was not built with `CONFIG_DMA_API_DEBUG=y`.
- `BLOCKED_DEBUGFS` — the option is enabled but the `dma-api/` debugfs interface is inaccessible.
- `BLOCKED_RUNTIME_DISABLED` — the runtime interface says debugging is disabled.

A missing bound DWC2 device is reported separately. `READY` with no bound `dwc2`
device means the checker is usable, but no DWC2 runtime claim is available.

## Kernel configuration

The minimum build-time settings for this gate are:

```text
CONFIG_DMA_API_DEBUG=y
CONFIG_DEBUG_FS=y
```

For an existing kernel source tree:

```bash
scripts/config --enable DMA_API_DEBUG
scripts/config --enable DEBUG_FS
make olddefconfig
```

`CONFIG_DMA_API_DEBUG` is enabled by default at boot when compiled in unless the
kernel command line disables it with `dma_debug=off`. It has runtime overhead;
its advantage here is low **engineering** cost compared with building a custom
DWC2 gadget stimulus, not zero execution cost.

## Exact run sequence

Self-test the gate first:

```bash
python3 tools/dma_api_debug_gate.py selftest
```

On the target DWC2 system:

```bash
sudo python3 tools/dma_api_debug_gate.py probe
sudo python3 tools/dma_api_debug_gate.py arm --driver dwc2 --num-errors 64
sudo python3 tools/dma_api_debug_gate.py snapshot artifacts/post-unmap-dma/dma-api-before
```

Exercise the **existing** DWC2 gadget/teardown path only. Do not build the custom
post-unmap gadget yet. Immediately capture the second snapshot:

```bash
sudo python3 tools/dma_api_debug_gate.py snapshot artifacts/post-unmap-dma/dma-api-after
python3 tools/dma_api_debug_gate.py compare \
  artifacts/post-unmap-dma/dma-api-before \
  artifacts/post-unmap-dma/dma-api-after
```

## Closure semantics

### Positive

```text
DMA_API_DEBUG_ERROR_DELTA > 0
DMA_API_DEBUG_COMPARE: DMA_API_MISUSE_OBSERVED
```

This is a stop artifact. Preserve `kernel-log.txt`, `kernel-log-dma-api.txt`,
`dma-api-state.txt`, and `dma-api-dump.txt`; inspect the warning stack before
building any custom gadget.

### Clean

```text
DMA_API_DEBUG_ERROR_DELTA = 0
DMA_API_DEBUG_COMPARE: API_MISUSE_NOT_OBSERVED
```

Promote only this statement:

```text
DRIVER_API_MISUSE_NOT_OBSERVED_DURING_EXERCISED_WINDOW
```

Do **not** promote:

```text
NO_POST_UNMAP_DMA
```

A clean DMA-API-debug run leaves the hardware post-unmap hypothesis active and
permits transition to the next runtime track.

## G0.5 stop conditions

- `BLOCKED_CONFIG` → stop; rebuild/boot a kernel with `CONFIG_DMA_API_DEBUG=y`.
- `BLOCKED_DEBUGFS` → stop; make the debugfs interface accessible and rerun.
- `BLOCKED_RUNTIME_DISABLED` → stop; reboot without `dma_debug=off` or investigate exhaustion.
- `DMA_API_MISUSE_OBSERVED` → stop custom-gadget work and analyze the warning stack.
- `API_MISUSE_NOT_OBSERVED` with a real DWC2 exercise window → G0.5 closes cleanly and Track L2 may start.
