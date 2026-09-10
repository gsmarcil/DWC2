#!/usr/bin/env python3
"""Low-cost DMA-API-debug gate for the DWC2 post-unmap DMA campaign.

This tool is deliberately a *driver API misuse* gate, not a proof that hardware
cannot DMA after unmap. A clean result means only that CONFIG_DMA_API_DEBUG did
not observe a DMA-API contract violation during one identity-stable exercised
window.
"""
from __future__ import annotations

import argparse
import gzip
import json
import platform
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

DMA_API_KEYS = (
    "disabled",
    "error_count",
    "num_errors",
    "all_errors",
    "min_free_entries",
    "num_free_entries",
    "nr_total_entries",
    "driver_filter",
)

COMPARABILITY_KEYS = ("kernel", "dwc2_bindings", "driver_filter", "boot_id")
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
WARN_RE = re.compile(r"DMA-API|check_unmap|debug_dma_|dma[_ -]api", re.I)


@dataclass
class Probe:
    kernel: str
    boot_id: Optional[str]
    config_path: Optional[str]
    config_dma_api_debug: Optional[str]
    config_debug_fs: Optional[str]
    debugfs_root: str
    dma_api_dir: str
    dma_api_present: bool
    dma_api_disabled: Optional[str]
    error_count: Optional[int]
    num_errors: Optional[int]
    driver_filter: Optional[str]
    dwc2_bindings: list[str]
    state: str
    reason: str


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return None


def _read_int(path: Path) -> Optional[int]:
    value = _read(path)
    if value is None:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _find_config(explicit: Optional[Path]) -> tuple[Optional[Path], dict[str, str]]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    kernel = platform.release()
    candidates.extend([
        Path("/proc/config.gz"),
        Path(f"/boot/config-{kernel}"),
        Path(f"/lib/modules/{kernel}/build/.config"),
    ])
    for path in candidates:
        if not path.is_file():
            continue
        try:
            if path.suffix == ".gz":
                text = gzip.open(path, "rt", errors="replace").read()
            else:
                text = path.read_text(errors="replace")
        except OSError:
            continue
        cfg: dict[str, str] = {}
        for line in text.splitlines():
            if line.startswith("CONFIG_") and "=" in line:
                key, value = line.split("=", 1)
                cfg[key] = value.strip()
            elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
                key = line[2:].split(" ", 1)[0]
                cfg[key] = "n"
        return path, cfg
    return None, {}


def _dwc2_bindings(sys_root: Path) -> list[str]:
    found: list[str] = []
    for bus in ("platform", "pci"):
        driver = sys_root / "bus" / bus / "drivers" / "dwc2"
        if not driver.is_dir():
            continue
        for child in sorted(driver.iterdir()):
            if child.name in {"bind", "unbind", "uevent", "module", "new_id", "remove_id"}:
                continue
            if child.is_symlink() or child.is_dir():
                found.append(f"{bus}:{child.name}")
    return found


def probe(args: argparse.Namespace) -> Probe:
    config_path, cfg = _find_config(args.config)
    dma_debug = cfg.get("CONFIG_DMA_API_DEBUG")
    debug_fs = cfg.get("CONFIG_DEBUG_FS")
    debugfs_root = args.debugfs
    dma_api = debugfs_root / "dma-api"
    present = dma_api.is_dir()
    disabled = _read(dma_api / "disabled") if present else None
    error_count = _read_int(dma_api / "error_count") if present else None
    num_errors = _read_int(dma_api / "num_errors") if present else None
    driver_filter = _read(dma_api / "driver_filter") if present else None
    bindings = _dwc2_bindings(args.sys_root)
    boot_id = _read(BOOT_ID_PATH)

    if dma_debug != "y":
        state = "BLOCKED_CONFIG"
        reason = "CONFIG_DMA_API_DEBUG is not enabled in the running-kernel config"
    elif not present:
        state = "BLOCKED_DEBUGFS"
        reason = "CONFIG_DMA_API_DEBUG=y but debugfs dma-api/ is not accessible"
    elif (disabled or "").upper().startswith("Y"):
        state = "BLOCKED_RUNTIME_DISABLED"
        reason = "DMA-API debugging is disabled at runtime (for example dma_debug=off or allocator failure)"
    else:
        state = "READY"
        reason = "DMA-API debugging is compiled in and active"

    return Probe(
        kernel=platform.release(),
        boot_id=boot_id,
        config_path=str(config_path) if config_path else None,
        config_dma_api_debug=dma_debug,
        config_debug_fs=debug_fs,
        debugfs_root=str(debugfs_root),
        dma_api_dir=str(dma_api),
        dma_api_present=present,
        dma_api_disabled=disabled,
        error_count=error_count,
        num_errors=num_errors,
        driver_filter=driver_filter,
        dwc2_bindings=bindings,
        state=state,
        reason=reason,
    )


def print_probe(p: Probe) -> None:
    print(f"DMA_API_DEBUG_GATE: {p.state}")
    print(f"  kernel                 {p.kernel}")
    print(f"  boot_id                {p.boot_id or 'UNAVAILABLE'}")
    print(f"  config_path            {p.config_path or 'NOT_FOUND'}")
    print(f"  CONFIG_DMA_API_DEBUG   {p.config_dma_api_debug or 'UNKNOWN'}")
    print(f"  CONFIG_DEBUG_FS        {p.config_debug_fs or 'UNKNOWN'}")
    print(f"  dma_api_dir            {p.dma_api_dir}")
    print(f"  dma_api_disabled       {p.dma_api_disabled if p.dma_api_disabled is not None else 'UNAVAILABLE'}")
    print(f"  error_count            {p.error_count if p.error_count is not None else 'UNAVAILABLE'}")
    print(f"  num_errors             {p.num_errors if p.num_errors is not None else 'UNAVAILABLE'}")
    print(f"  driver_filter          {p.driver_filter!r}")
    print(f"  dwc2_bindings          {', '.join(p.dwc2_bindings) if p.dwc2_bindings else 'NONE_OBSERVED'}")
    print(f"  reason                 {p.reason}")
    if p.state == "READY" and not p.dwc2_bindings:
        print("  runtime_note           DMA debug is ready, but no bound dwc2 device was observed")


def _kernel_log() -> str:
    commands = (["dmesg", "--time-format", "iso"], ["dmesg"])
    for cmd in commands:
        try:
            cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                check=False, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if cp.stdout:
            return cp.stdout
    return ""


def snapshot(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    p = probe(args)
    (out / "probe.json").write_text(json.dumps(asdict(p), indent=2, sort_keys=True) + "\n")
    print_probe(p)

    config_path = Path(p.config_path) if p.config_path else None
    if config_path and config_path.is_file():
        if config_path.suffix == ".gz":
            text = gzip.open(config_path, "rt", errors="replace").read()
        else:
            text = config_path.read_text(errors="replace")
        selected = [line for line in text.splitlines()
                    if "CONFIG_DMA_API_DEBUG" in line or "CONFIG_DEBUG_FS" in line]
        (out / "kernel-config.txt").write_text("\n".join(selected) + "\n")

    dma_api = Path(p.dma_api_dir)
    state_lines: list[str] = []
    if dma_api.is_dir():
        for name in DMA_API_KEYS:
            value = _read(dma_api / name)
            state_lines.append(f"{name}={value if value is not None else 'UNAVAILABLE'}")
        dump = _read(dma_api / "dump")
        if dump is not None:
            (out / "dma-api-dump.txt").write_text(dump + ("\n" if dump else ""))
    (out / "dma-api-state.txt").write_text("\n".join(state_lines) + "\n")
    (out / "dwc2-bindings.txt").write_text("\n".join(p.dwc2_bindings) + ("\n" if p.dwc2_bindings else ""))
    log = _kernel_log()
    (out / "kernel-log.txt").write_text(log)
    filtered = "\n".join(line for line in log.splitlines() if WARN_RE.search(line))
    (out / "kernel-log-dma-api.txt").write_text(filtered + ("\n" if filtered else ""))
    print(f"  snapshot               {out}")
    return 0 if p.state == "READY" else 2


def arm(args: argparse.Namespace) -> int:
    p = probe(args)
    print_probe(p)
    if p.state != "READY":
        return 2
    dma_api = Path(p.dma_api_dir)
    try:
        if args.driver is not None:
            (dma_api / "driver_filter").write_text(args.driver + "\n")
        if args.num_errors is not None:
            (dma_api / "num_errors").write_text(str(args.num_errors) + "\n")
    except OSError as exc:
        print(f"DMA_API_DEBUG_ARM: REFUSED: {exc}", file=sys.stderr)
        return 3
    print("DMA_API_DEBUG_ARM: PASS")
    print(f"  driver_filter          {_read(dma_api / 'driver_filter')!r}")
    print(f"  num_errors             {_read(dma_api / 'num_errors')}")
    return 0


def _load_probe(path: Path, label: str) -> dict:
    try:
        value = json.loads((path / "probe.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} probe.json unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} probe.json is not an object")
    return value


def _validate_identity_field(key: str, value: object) -> bool:
    if key in {"kernel", "boot_id"}:
        return isinstance(value, str) and bool(value.strip())
    if key == "dwc2_bindings":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if key == "driver_filter":
        return isinstance(value, str)
    return False


def compare(args: argparse.Namespace) -> int:
    try:
        before = _load_probe(args.before, "before")
        after = _load_probe(args.after, "after")
    except ValueError as exc:
        print(f"DMA_API_DEBUG_COMPARE: REFUSED — {exc}")
        return 2

    for name, obj in (("before", before), ("after", after)):
        if obj.get("state") != "READY":
            print(f"DMA_API_DEBUG_COMPARE: REFUSED — {name} snapshot state={obj.get('state')}")
            return 2

    # A clean delta is admissible only inside one positively identified runtime
    # window. Equality of the counter alone is not evidence of comparability.
    for key in COMPARABILITY_KEYS:
        if key not in before or key not in after:
            print(f"DMA_API_DEBUG_COMPARE: REFUSED — {key} missing from snapshot identity")
            return 2
        if not _validate_identity_field(key, before[key]) or not _validate_identity_field(key, after[key]):
            print(f"DMA_API_DEBUG_COMPARE: REFUSED — {key} unavailable or malformed")
            return 2
        if before[key] != after[key]:
            print(f"DMA_API_DEBUG_COMPARE: REFUSED — {key} differs between snapshots")
            return 2

    b = before.get("error_count")
    a = after.get("error_count")
    if not isinstance(b, int) or isinstance(b, bool) or not isinstance(a, int) or isinstance(a, bool):
        print("DMA_API_DEBUG_COMPARE: REFUSED — error_count unavailable")
        return 2
    delta = a - b
    print(f"DMA_API_DEBUG_ERROR_COUNT_BEFORE: {b}")
    print(f"DMA_API_DEBUG_ERROR_COUNT_AFTER:  {a}")
    print(f"DMA_API_DEBUG_ERROR_DELTA:        {delta}")
    if delta < 0:
        print("DMA_API_DEBUG_COMPARE: REFUSED — counter moved backwards; snapshots are not comparable")
        return 2
    if delta > 0:
        print("DMA_API_DEBUG_COMPARE: DMA_API_MISUSE_OBSERVED")
        print("CLAIM_BOUNDARY: this proves a DMA-API debug violation was observed; inspect the kernel stack before any custom gadget work")
        return 10
    print("DMA_API_DEBUG_COMPARE: API_MISUSE_NOT_OBSERVED")
    print("CLAIM_BOUNDARY: clean DMA-API debug does NOT prove NO_POST_UNMAP_DMA")
    return 0


def selftest(_: argparse.Namespace) -> int:
    checks = 0

    def require(condition: bool, label: str) -> None:
        nonlocal checks
        if not condition:
            raise RuntimeError(label)
        checks += 1

    try:
        with tempfile.TemporaryDirectory(prefix="dma-api-debug-selftest-") as td:
            root = Path(td)
            cfg = root / "config"
            dbg = root / "debug" / "dma-api"
            sys_root = root / "sys"
            dbg.mkdir(parents=True)
            (sys_root / "bus/platform/drivers/dwc2").mkdir(parents=True)
            (sys_root / "bus/platform/drivers/dwc2/fe980000.usb").mkdir()
            for name, value in {
                "disabled": "N\n", "error_count": "0\n", "num_errors": "1\n",
                "all_errors": "0\n", "driver_filter": "dwc2\n", "dump": "",
                "min_free_entries": "10\n", "num_free_entries": "20\n", "nr_total_entries": "30\n",
            }.items():
                (dbg / name).write_text(value)

            base = argparse.Namespace(config=cfg, debugfs=root / "debug", sys_root=sys_root)

            cfg.write_text("# CONFIG_DMA_API_DEBUG is not set\nCONFIG_DEBUG_FS=y\n")
            require(probe(base).state == "BLOCKED_CONFIG", "disabled-config negative control")

            cfg.write_text("CONFIG_DMA_API_DEBUG=y\nCONFIG_DEBUG_FS=y\n")
            ready = probe(base)
            require(ready.state == "READY", "ready positive control")
            require(ready.dwc2_bindings == ["platform:fe980000.usb"], "binding capture")
            require(isinstance(ready.boot_id, str) and bool(ready.boot_id), "boot_id capture")

            (dbg / "disabled").write_text("Y\n")
            require(probe(base).state == "BLOCKED_RUNTIME_DISABLED", "runtime-disabled negative control")
            (dbg / "disabled").write_text("N\n")

            before = root / "before"; after = root / "after"
            before.mkdir(); after.mkdir()
            p0 = asdict(probe(base)); p0["error_count"] = 4
            p1 = dict(p0); p1["error_count"] = 4
            (before / "probe.json").write_text(json.dumps(p0))
            (after / "probe.json").write_text(json.dumps(p1))
            cargs = argparse.Namespace(before=before, after=after)
            require(compare(cargs) == 0, "equal-window clean positive control")

            p1["error_count"] = 5
            (after / "probe.json").write_text(json.dumps(p1))
            require(compare(cargs) == 10, "error-delta positive control")

            mismatches = {
                "kernel": "different-kernel",
                "dwc2_bindings": ["platform:different.usb"],
                "driver_filter": "different-driver",
                "boot_id": "00000000-0000-0000-0000-000000000000",
            }
            for key, other in mismatches.items():
                bad = dict(p0)
                bad[key] = other
                bad["error_count"] = p0["error_count"]
                (after / "probe.json").write_text(json.dumps(bad))
                require(compare(cargs) == 2, f"{key} mismatch negative control")

            missing_boot = dict(p0)
            missing_boot.pop("boot_id", None)
            (after / "probe.json").write_text(json.dumps(missing_boot))
            require(compare(cargs) == 2, "missing boot_id negative control")

            backwards = dict(p0)
            backwards["error_count"] = 3
            (after / "probe.json").write_text(json.dumps(backwards))
            require(compare(cargs) == 2, "counter-backwards negative control")

    except RuntimeError as exc:
        print(f"DMA_API_DEBUG_SELFTEST: FAIL — {exc}")
        return 1

    expected = 13
    if checks != expected:
        print(f"DMA_API_DEBUG_SELFTEST: FAIL — internal count {checks}/{expected}")
        return 1
    print(f"DMA_API_DEBUG_SELFTEST: PASS {checks}/{expected}")
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="override running-kernel config path")
    parser.add_argument("--debugfs", type=Path, default=Path("/sys/kernel/debug"),
                        help="debugfs mountpoint (default: /sys/kernel/debug)")
    parser.add_argument("--sys-root", type=Path, default=Path("/sys"),
                        help="sysfs root (default: /sys)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="check compile-time and runtime readiness")
    add_common(p)

    def probe_cmd(a: argparse.Namespace) -> int:
        result = probe(a)
        print_probe(result)
        return 0 if result.state == "READY" else 2

    p.set_defaults(func=probe_cmd)

    p = sub.add_parser("snapshot", help="capture an evidence snapshot")
    add_common(p); p.add_argument("out", type=Path); p.set_defaults(func=snapshot)

    p = sub.add_parser("arm", help="explicitly set DMA-API debug warning/filter controls")
    add_common(p)
    p.add_argument("--driver", default="dwc2", help="driver_filter value (default: dwc2; use '' to clear)")
    p.add_argument("--num-errors", type=int, default=64, help="warnings to print before silencing (default: 64)")
    p.set_defaults(func=arm)

    p = sub.add_parser("compare", help="compare before/after snapshots")
    p.add_argument("before", type=Path); p.add_argument("after", type=Path); p.set_defaults(func=compare)

    p = sub.add_parser("selftest", help="run discriminating positive and negative controls")
    p.set_defaults(func=selftest)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
