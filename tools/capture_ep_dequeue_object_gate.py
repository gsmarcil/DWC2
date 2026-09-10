#!/usr/bin/env python3
"""Capture an exact-object artifact for POST-UNMAP-DMA-001 DDMA dequeue OBJECT_GATE.

This tool intentionally does not adjudicate OBJECT-PROVEN. It captures the exact
binary identity, tool/config identities, and source-interleaved disassembly needed
for a later fail-closed control-flow adjudication.

Important closure rules:
- With LTO enabled, a pre-link .o is not an admissible closure artifact; use the
  final linked image (vmlinux or the final module containing DWC2).
- Exact closure requires positive debug/source mapping: a real DWARF line-table
  section plus at least one file:line marker in the selected function disassembly.
  Symbol names or relocation names never count as source mapping.
- Do not look only for a call to dwc2_hsotg_ep_stop_xfr(): that static helper may
  be inlined. Adjudication must recognize either a retained call or the inlined
  SNAK/SGOUTNAK -> EPDIS -> wait sequence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

EXPECTED_GADGET_SHA256 = "baf17cb89e78c8a63f0a9688af7697875018f162923118f72f1092df703f6d8d"
DEFAULT_FUNCTION = "dwc2_hsotg_ep_dequeue"

DEBUG_LINE_SECTION_RE = re.compile(r"(?m)^\s*\d+\s+\.(?:z)?debug_line(?:\s|$)")
SOURCE_LINE_MARKER_RE = re.compile(
    r"(?m)^(?P<path>.+\.(?:c|h)):(?P<line>[1-9][0-9]*)(?:\s*(?:\([^\n]*\))?\s*)$"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=check)


def pick_tool(explicit: str | None, candidates: tuple[str, ...]) -> str:
    if explicit:
        path = shutil.which(explicit) if os.sep not in explicit else explicit
        if path and Path(path).exists():
            return str(path)
        raise SystemExit(f"REFUSED: tool not found: {explicit}")
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit(f"REFUSED: none of these tools are available: {', '.join(candidates)}")


def pick_optional_tool(explicit: str | None, candidates: tuple[str, ...]) -> str | None:
    if explicit:
        path = shutil.which(explicit) if os.sep not in explicit else explicit
        return str(path) if path and Path(path).exists() else None
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def config_lto_enabled(text: str) -> bool:
    for line in text.splitlines():
        if not line.endswith("=y"):
            continue
        key = line.split("=", 1)[0]
        if key.startswith("CONFIG_ARCH_SUPPORTS_LTO"):
            continue
        if key == "CONFIG_LTO" or key.startswith("CONFIG_LTO_"):
            return True
    return False


def likely_prelink_object(path: Path) -> bool:
    return path.suffix == ".o" and not path.name.endswith(".ko.o")


def source_mapping_evidence(section_headers: str, disassembly: str,
                            gadget_source: Path | None) -> tuple[bool, bool, bool, list[str]]:
    """Return positive source-map evidence independent from symbols/relocations."""
    has_debug_line = DEBUG_LINE_SECTION_RE.search(section_headers) is not None
    markers = [m.group(0).strip() for m in SOURCE_LINE_MARKER_RE.finditer(disassembly)]
    if gadget_source is not None:
        expected_name = gadget_source.name
        relevant = []
        for marker in markers:
            source_path = marker.rsplit(":", 1)[0]
            if Path(source_path).name == expected_name:
                relevant.append(marker)
        markers = relevant
    has_source_line = bool(markers)
    return has_debug_line and has_source_line, has_debug_line, has_source_line, markers


def capture(args: argparse.Namespace) -> int:
    obj = args.object.resolve()
    if not obj.is_file():
        print(f"OBJECT_GATE_CAPTURE: REFUSED — object not found: {obj}", file=sys.stderr)
        return 2

    out = args.out.resolve()
    if out.exists():
        print(f"OBJECT_GATE_CAPTURE: REFUSED — output already exists: {out}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        objdump = pick_tool(args.objdump, ("objdump", "llvm-objdump"))
    except SystemExit as exc:
        print(f"OBJECT_GATE_CAPTURE: {exc}", file=sys.stderr)
        return 2
    file_tool = pick_optional_tool(args.file_tool, ("file",))

    source_sha = None
    src: Path | None = None
    if args.gadget_source:
        src = args.gadget_source.resolve()
        if not src.is_file():
            print(f"OBJECT_GATE_CAPTURE: REFUSED — gadget source not found: {src}", file=sys.stderr)
            return 2
        source_sha = sha256_file(src)
        expected = args.expected_gadget_sha256.lower()
        if source_sha.lower() != expected:
            print("OBJECT_GATE_CAPTURE: REFUSED — gadget.c SHA256 mismatch", file=sys.stderr)
            print(f"  expected {expected}", file=sys.stderr)
            print(f"  actual   {source_sha}", file=sys.stderr)
            return 2

    cfg = args.config.resolve() if args.config else None
    lto_enabled = None
    if cfg:
        if not cfg.is_file():
            print(f"OBJECT_GATE_CAPTURE: REFUSED — config not found: {cfg}", file=sys.stderr)
            return 2
        cfg_text = cfg.read_text(errors="replace")
        lto_enabled = config_lto_enabled(cfg_text)
        if lto_enabled and likely_prelink_object(obj):
            print("OBJECT_GATE_CAPTURE: REFUSED — LTO enabled but a pre-link .o was supplied", file=sys.stderr)
            print("  use the final linked vmlinux or final module containing DWC2", file=sys.stderr)
            return 2

    try:
        objdump_version = run([objdump, "--version"]).stdout.splitlines()[0]
        obj_header = run([objdump, "-f", str(obj)]).stdout
        section_headers = run([objdump, "-h", str(obj)]).stdout
        file_desc = run([file_tool, "-L", str(obj)]).stdout.strip() if file_tool else None
        if "llvm-objdump" in Path(objdump).name:
            dis_argv = [objdump, "-drSl", "--no-show-raw-insn",
                        f"--disassemble-symbols={args.function}", str(obj)]
        else:
            dis_argv = [objdump, "-drwCSl", "--no-show-raw-insn",
                        f"--disassemble={args.function}", str(obj)]
        dis = run(dis_argv, check=False)
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        print(f"OBJECT_GATE_CAPTURE: REFUSED — tool execution failed: {exc}", file=sys.stderr)
        return 2

    if dis.returncode != 0:
        print("OBJECT_GATE_CAPTURE: REFUSED — objdump failed", file=sys.stderr)
        print(dis.stdout, file=sys.stderr)
        return 2

    symbol_markers = (f"<{args.function}>:", f"<{args.function}(")
    if not any(marker in dis.stdout for marker in symbol_markers):
        print(f"OBJECT_GATE_CAPTURE: REFUSED — function symbol not found: {args.function}", file=sys.stderr)
        print("  if LTO changed symbolization, capture the exact linked call site and adjudicate manually", file=sys.stderr)
        return 2

    source_mapped, has_debug_line, has_source_line, source_line_markers = source_mapping_evidence(
        section_headers, dis.stdout, src
    )
    if args.require_source_map and not source_mapped:
        print("OBJECT_GATE_CAPTURE: REFUSED — positive DWARF source/line mapping not recovered", file=sys.stderr)
        print(f"  debug_line_section={has_debug_line} source_line_marker={has_source_line}", file=sys.stderr)
        print("  rebuild the exact target with -g (or equivalent line-table debug info) and recapture", file=sys.stderr)
        return 2

    stage = Path(tempfile.mkdtemp(prefix=".object-gate-stage-", dir=out.parent))
    try:
        (stage / "disassembly-source.txt").write_text(dis.stdout)
        (stage / "object-header.txt").write_text(obj_header)
        (stage / "section-headers.txt").write_text(section_headers)
        if cfg:
            shutil.copyfile(cfg, stage / "kernel-config.txt")

        meta = {
            "event": "POST_UNMAP_DMA_OBJECT_GATE_CAPTURE",
            "claim_id": "POST-UNMAP-DMA-001",
            "track": "PRIMARY-B-DDMA-ISOC-DEQUEUE",
            "status": "CAPTURED_NOT_ADJUDICATED",
            "function": args.function,
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            "epoch_id": args.epoch_id,
            "board_id": args.board_id,
            "kernel_commit": args.kernel_commit,
            "object_path": str(obj),
            "object_sha256": sha256_file(obj),
            "object_file_description": file_desc,
            "file_tool": file_tool,
            "object_is_prelink_o": likely_prelink_object(obj),
            "lto_enabled_from_config": lto_enabled,
            "debug_line_section_present": has_debug_line,
            "source_line_marker_present": has_source_line,
            "source_line_markers": source_line_markers,
            "source_interleave_present": source_mapped,
            "objdump": objdump,
            "objdump_version": objdump_version,
            "objdump_argv": dis_argv,
            "gadget_source_path": str(src) if src else None,
            "gadget_source_sha256": source_sha,
            "expected_gadget_source_sha256": args.expected_gadget_sha256 if src else None,
            "config_sha256": sha256_file(cfg) if cfg else None,
            "compiler_identity": args.compiler_identity,
            "adjudication_contract": {
                "OBJECT_PROVEN": [
                    "load hs_ep->req pointer value",
                    "compare that value with req argument",
                    "retain a conditional branch separating stop from skip-stop",
                    "no memory read through the loaded hs_ep->req value before the comparison",
                    "NULL path reaches complete_request/U without executing the stop sequence",
                ],
                "KILLED": [
                    "memory read through hs_ep->req before the comparison",
                    "comparison folded to a constant that invalidates the silent-skip path",
                    "stop sequence executes unconditionally on the NULL path",
                ],
                "INLINE_WARNING": (
                    "Do not require a call instruction to dwc2_hsotg_ep_stop_xfr; the static helper "
                    "may be inlined. Recognize the inlined SNAK/SGOUTNAK, EPDIS and wait sequence."
                ),
            },
            "closure_boundary": (
                "This capture does not prove silent skip. PASS requires exact target linked/object "
                "control-flow adjudication under this board/toolchain/config identity."
            ),
        }
        (stage / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        os.replace(stage, out)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    print("OBJECT_GATE_CAPTURE: PASS")
    print(f"  status          {meta['status']}")
    print(f"  board_id        {meta['board_id']}")
    print(f"  object_sha256   {meta['object_sha256']}")
    print(f"  lto_enabled     {meta['lto_enabled_from_config']}")
    print(f"  debug_line      {meta['debug_line_section_present']}")
    print(f"  source_line     {meta['source_line_marker_present']}")
    print(f"  source_mapped   {meta['source_interleave_present']}")
    print(f"  function        {args.function}")
    print(f"  output          {out}")
    return 0


def selftest(_: argparse.Namespace) -> int:
    passed = 0
    cc = shutil.which("cc")
    if not cc:
        print("OBJECT_GATE_CAPTURE_SELFTEST: SKIP — cc unavailable")
        return 77
    with tempfile.TemporaryDirectory(prefix="object-gate-selftest-") as td:
        root = Path(td)
        src = root / "t.c"
        obj = root / "t.o"
        obj_nog = root / "t-nog.o"
        out = root / "artifact"
        cfg = root / ".config"
        src.write_text(r'''struct usb_request { void *p; };
struct wrap { struct usb_request req; long x; };
struct ep { struct wrap *req; };
extern void dwc2_hsotg_ep_stop_xfr(struct ep *);
extern void dwc2_hsotg_complete_request(struct ep *, struct wrap *);
__attribute__((noinline)) int dwc2_hsotg_ep_dequeue(struct ep *ep, struct usb_request *req, struct wrap *w) {
    if (req == &ep->req->req) dwc2_hsotg_ep_stop_xfr(ep);
    dwc2_hsotg_complete_request(ep, w);
    return 0;
}
''')
        cfg.write_text("# CONFIG_LTO is not set\n")
        for argv, label in (
            ([cc, "-O2", "-g", "-c", str(src), "-o", str(obj)], "debug compile"),
            ([cc, "-O2", "-c", str(src), "-o", str(obj_nog)], "no-debug compile"),
        ):
            cp = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if cp.returncode:
                print(f"OBJECT_GATE_CAPTURE_SELFTEST: FAIL — {label}")
                print(cp.stdout)
                return 1

        ns = argparse.Namespace(
            object=obj, out=out, objdump=None, file_tool=None,
            gadget_source=None, expected_gadget_sha256=EXPECTED_GADGET_SHA256,
            config=cfg, function=DEFAULT_FUNCTION, epoch_id="SELFTEST",
            board_id="SELFTEST-BOARD", kernel_commit="SELFTEST",
            compiler_identity=run([cc, "--version"]).stdout.splitlines()[0],
            require_source_map=True,
        )
        rc = capture(ns)
        if rc != 0:
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — positive source-mapped capture")
            return 1
        passed += 1
        meta = json.loads((out / "meta.json").read_text())
        dis = (out / "disassembly-source.txt").read_text()
        positive_checks = [
            meta["status"] == "CAPTURED_NOT_ADJUDICATED",
            meta["function"] == DEFAULT_FUNCTION,
            len(meta["object_sha256"]) == 64,
            DEFAULT_FUNCTION in dis,
            meta["debug_line_section_present"] is True,
            meta["source_line_marker_present"] is True,
            meta["source_interleave_present"] is True,
            meta["lto_enabled_from_config"] is False,
            (out / "object-header.txt").is_file(),
            (out / "section-headers.txt").is_file(),
        ]
        if not all(positive_checks):
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — positive invariant")
            return 1
        passed += 1

        # Negative control: same fixture without -g retains the exact weak symbol/
        # relocation look-alikes that defeated the old hits>=2 heuristic, yet must
        # still be refused and leave no artifact.
        objdump = pick_tool(None, ("objdump", "llvm-objdump"))
        weak = run([objdump, "-dr", str(obj_nog)]).stdout
        weak_needles = (DEFAULT_FUNCTION, "dwc2_hsotg_ep_stop_xfr", "dwc2_hsotg_complete_request")
        if not all(n in weak for n in weak_needles):
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — no-debug fixture lost weak symbol look-alikes")
            return 1
        passed += 1
        no_debug = argparse.Namespace(**vars(ns))
        no_debug.object = obj_nog
        no_debug.out = root / "no-debug-artifact"
        if capture(no_debug) != 2 or no_debug.out.exists():
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — no-debug source-map negative control")
            return 1
        passed += 1

        # Auxiliary `file(1)` is descriptive only and must not gate admissible capture.
        no_file = argparse.Namespace(**vars(ns))
        no_file.out = root / "no-file-artifact"
        no_file.file_tool = "definitely-missing-file-tool"
        if capture(no_file) != 0:
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — optional file tool")
            return 1
        passed += 1
        no_file_meta = json.loads((no_file.out / "meta.json").read_text())
        if no_file_meta["object_file_description"] is not None or no_file_meta["file_tool"] is not None:
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — optional file metadata invariant")
            return 1
        passed += 1

        lto_cfg = root / "lto.config"
        lto_cfg.write_text("CONFIG_LTO=y\nCONFIG_LTO_CLANG=y\n")
        bad_lto = argparse.Namespace(**vars(ns))
        bad_lto.out = root / "lto-artifact"
        bad_lto.config = lto_cfg
        if capture(bad_lto) != 2 or bad_lto.out.exists():
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — LTO pre-link negative control")
            return 1
        passed += 1

        bad = argparse.Namespace(**vars(ns))
        bad.out = root / "bad-artifact"
        bad.function = "definitely_missing_symbol"
        if capture(bad) != 2 or bad.out.exists():
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — missing-symbol negative control")
            return 1
        passed += 1
    expected = 8
    if passed != expected:
        print(f"OBJECT_GATE_CAPTURE_SELFTEST: FAIL — internal count {passed}/{expected}")
        return 1
    print(f"OBJECT_GATE_CAPTURE_SELFTEST: PASS {passed}/{expected}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("capture", help="capture exact-object evidence; does not adjudicate PASS")
    p.add_argument("object", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--function", default=DEFAULT_FUNCTION)
    p.add_argument("--objdump")
    p.add_argument("--file-tool", help="optional descriptive file(1)-compatible tool")
    p.add_argument("--gadget-source", type=Path)
    p.add_argument("--expected-gadget-sha256", default=EXPECTED_GADGET_SHA256)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--epoch-id", required=True)
    p.add_argument("--board-id", required=True)
    p.add_argument("--kernel-commit", required=True)
    p.add_argument("--compiler-identity", required=True)
    p.add_argument("--require-source-map", action=argparse.BooleanOptionalAction, default=True)
    p.set_defaults(func=capture)

    p = sub.add_parser("selftest")
    p.set_defaults(func=selftest)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
