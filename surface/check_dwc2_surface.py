#!/usr/bin/env python3
"""Fail-closed source-surface scanner for the DWC2 R1 lifetime hypothesis.

This is deliberately a SOURCE-SHAPE classifier, not an affected-version or
security-impact oracle.  It answers whether a tree still contains the source
relationships that keep the runtime hypothesis alive.  Runtime reachability,
post-unmap issue, commit, attacker control, and impact remain separate facts.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def function_body(text: str, name: str) -> str:
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", text, re.S)
    if not m:
        raise ValueError(f"function not found: {name}")
    start = text.find("{", m.start())
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start(): i + 1]
    raise ValueError(f"unterminated function: {name}")


def ordered(body: str, *needles: str) -> bool:
    pos = -1
    for needle in needles:
        pos = body.find(needle, pos + 1)
        if pos < 0:
            return False
    return True


def compact(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def scan(root: Path, label: str, commit: str) -> dict[str, str]:
    gadget_path = root / "drivers/usb/dwc2/gadget.c"
    udc_core_path = root / "drivers/usb/gadget/udc/core.c"
    if not gadget_path.is_file() or not udc_core_path.is_file():
        raise ValueError("expected DWC2 gadget.c and gadget UDC core.c")

    gadget = gadget_path.read_text(errors="strict")
    udc_core = udc_core_path.read_text(errors="strict")

    stop = function_body(gadget, "dwc2_hsotg_ep_stop_xfr")
    disable = function_body(gadget, "dwc2_hsotg_ep_disable")
    complete = function_body(gadget, "dwc2_hsotg_complete_request")
    map_dma = function_body(gadget, "dwc2_hsotg_map_dma")
    unmap_dma = function_body(gadget, "dwc2_hsotg_unmap_dma")
    generic_map = function_body(udc_core, "usb_gadget_map_request_by_dev")
    generic_unmap = function_body(udc_core, "usb_gadget_unmap_request_by_dev")

    # Source primitive: timeout branches warn, then the function still reaches
    # endpoint disable programming.  This deliberately does not claim the
    # timeout is reachable on a real controller.
    stop_c = compact(stop)
    timeout_markers = (
        "timeout GINTSTS.GOUTNAKEFF",
        "timeout DOEPCTL.EPDisable",
    )
    stop_warn_continue = all(x in stop for x in timeout_markers) and (
        "DXEPCTL_EPDIS | DXEPCTL_SNAK" in stop
    ) and not re.search(
        r'timeout GINTSTS\.GOUTNAKEFF[^;]*;\s*return\b', stop_c
    )

    # Teardown must stop the endpoint and then retire queued requests.
    disable_stop_then_kill = ordered(
        disable, "dwc2_hsotg_ep_stop_xfr", "kill_all_requests"
    ) and "-ESHUTDOWN" in disable

    # Same request completion must unmap before gadget giveback.
    complete_unmap_then_giveback = ordered(
        complete, "dwc2_hsotg_unmap_dma", "usb_gadget_giveback_request"
    )

    # DWC2 delegates lifetime to gadget-core map/unmap helpers.
    dwc2_map_delegates = "usb_gadget_map_request" in map_dma
    dwc2_unmap_delegates = "usb_gadget_unmap_request" in unmap_dma

    # Linear core path maps and unmaps exactly req->length.
    gm = compact(generic_map)
    gu = compact(generic_unmap)
    linear_map_len = bool(re.search(
        r"dma_map_single\s*\([^;]*?req->buf\s*,\s*req->length\s*,", gm
    )) and "req->dma_mapped = 1" in gm
    linear_unmap_len = bool(re.search(
        r"dma_unmap_single\s*\([^;]*?req->dma\s*,\s*req->length\s*,", gu
    )) and "req->dma_mapped = 0" in gu

    descriptor_dma_code = (
        "using_desc_dma" in gadget and
        "dwc2_gadget_config_nonisoc_xfer_ddma" in gadget
    )
    address_dma_programming = bool(re.search(
        r"dwc2_writel\s*\(\s*hsotg\s*,\s*ureq->dma\s*,\s*dma_reg\s*\)",
        compact(gadget),
    ))

    checks = [
        stop_warn_continue,
        disable_stop_then_kill,
        complete_unmap_then_giveback,
        dwc2_map_delegates,
        dwc2_unmap_delegates,
        linear_map_len,
        linear_unmap_len,
        address_dma_programming,
    ]
    source_shape = "SOURCE_SHAPE_PRESENT" if all(checks) else "SOURCE_SHAPE_CHANGED"

    return {
        "label": label,
        "commit": commit,
        "stop_timeout_warn_continue": str(stop_warn_continue).lower(),
        "ep_disable_stop_then_kill": str(disable_stop_then_kill).lower(),
        "complete_unmap_then_giveback": str(complete_unmap_then_giveback).lower(),
        "dwc2_map_delegates": str(dwc2_map_delegates).lower(),
        "dwc2_unmap_delegates": str(dwc2_unmap_delegates).lower(),
        "linear_map_req_length": str(linear_map_len).lower(),
        "linear_unmap_req_length": str(linear_unmap_len).lower(),
        "address_dma_programming": str(address_dma_programming).lower(),
        "descriptor_dma_code_present": str(descriptor_dma_code).lower(),
        "source_shape": source_shape,
        "runtime_reachability": "UNKNOWN",
        "d_issue": "UNKNOWN",
        "d_commit": "UNKNOWN",
        "security_impact": "UNKNOWN",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    try:
        row = scan(args.root.resolve(), args.label, args.commit)
    except Exception as exc:
        print(f"DWC2_SURFACE_SCAN: FAIL: {exc}", file=sys.stderr)
        return 2

    if args.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    else:
        for k, v in row.items():
            print(f"{k}={v}")
        print(f"DWC2_SURFACE_SCAN: {row['source_shape']}")

    return 0 if row["source_shape"] == "SOURCE_SHAPE_PRESENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
