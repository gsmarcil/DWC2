#!/usr/bin/env python3
"""Capture an exact-object artifact for POST-UNMAP-DMA-001 DDMA dequeue OBJECT_GATE.

This tool intentionally does not adjudicate OBJECT-PROVEN. It captures the exact
binary identity, tool/config identities, and source-interleaved disassembly needed
for a later fail-closed control-flow adjudication.

Important closure rules:
- With LTO enabled, a pre-link .o is not an admissible closure artifact; use the
  final linked image (vmlinux or the final module containing DWC2).
- Exact closure requires debug/source mapping. The capture uses objdump -S and
  refuses when it cannot recover source context for dwc2_hsotg_ep_dequeue().
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

LTO_Y_RE = re.compile(r"^CONFIG_(?:LTO(?:_[A-Z0-9_]+)?|ARCH_SUPPORTS_LTO_CLANG_THIN)=y$", re.M)


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


def config_lto_enabled(text: str) -> bool:
    # CONFIG_LTO=y, CONFIG_LTO_CLANG=y, CONFIG_LTO_CLANG_THIN=y,
    # CONFIG_LTO_GCC=y, etc. The ARCH_SUPPORTS_* capability alone must not make
    # LTO "enabled", so filter it back out after the broad regex.
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


def source_context_present(disassembly: str, gadget_source: Path | None) -> bool:
    # objdump -S may emit either the source filename/line markers or the exact
    # source text. Accept either, but do not infer line identity from addresses.
    needles = [
        "dwc2_hsotg_ep_dequeue",
        "if (req == &hs_ep->req->req)",
        "dwc2_hsotg_ep_stop_xfr",
        "dwc2_hsotg_complete_request",
    ]
    if gadget_source is not None:
        needles.extend([gadget_source.name, str(gadget_source)])
    # Function name alone is not enough; require a second source-oriented anchor.
    hits = sum(1 for n in needles if n in disassembly)
    return hits >= 2


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

    objdump = pick_tool(args.objdump, ("objdump", "llvm-objdump"))
    file_tool = pick_tool(args.file_tool, ("file",))

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
    cfg_text = None
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
        file_desc = run([file_tool, "-L", str(obj)]).stdout.strip()
        obj_header = run([objdump, "-f", str(obj)]).stdout
        if "llvm-objdump" in Path(objdump).name:
            dis_argv = [objdump, "-drS", "--no-show-raw-insn",
                        f"--disassemble-symbols={args.function}", str(obj)]
        else:
            dis_argv = [objdump, "-drwCS", "--no-show-raw-insn",
                        f"--disassemble={args.function}", str(obj)]
        dis = run(dis_argv, check=False)
    except (OSError, subprocess.CalledProcessError) as exc:
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

    source_mapped = source_context_present(dis.stdout, src)
    if args.require_source_map and not source_mapped:
        print("OBJECT_GATE_CAPTURE: REFUSED — source/line context not recovered by objdump -S", file=sys.stderr)
        print("  rebuild the target with -g (or equivalent debug info) and recapture", file=sys.stderr)
        return 2

    stage = Path(tempfile.mkdtemp(prefix=".object-gate-stage-", dir=out.parent))
    try:
        (stage / "disassembly-source.txt").write_text(dis.stdout)
        (stage / "object-header.txt").write_text(obj_header)
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
            "object_is_prelink_o": likely_prelink_object(obj),
            "lto_enabled_from_config": lto_enabled,
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
    print(f"  source_mapped   {meta['source_interleave_present']}")
    print(f"  function        {args.function}")
    print(f"  output          {out}")
    return 0


def selftest(_: argparse.Namespace) -> int:
    cc = shutil.which("cc")
    if not cc:
        print("OBJECT_GATE_CAPTURE_SELFTEST: SKIP — cc unavailable")
        return 77
    with tempfile.TemporaryDirectory(prefix="object-gate-selftest-") as td:
        root = Path(td)
        src = root / "t.c"
        obj = root / "t.o"
        out = root / "artifact"
        cfg = root / ".config"
        src.write_text(r'''struct usb_request { void *p; };
struct wrap { struct usb_request req; long x; };
struct ep { struct wrap *req; };
extern void stop(struct ep *);
extern void complete(struct ep *, struct wrap *);
__attribute__((noinline)) int dwc2_hsotg_ep_dequeue(struct ep *ep, struct usb_request *req, struct wrap *w) {
    if (req == &ep->req->req) stop(ep);
    complete(ep, w);
    return 0;
}
''')
        cfg.write_text("# CONFIG_LTO is not set\n")
        cp = subprocess.run([cc, "-O2", "-g", "-c", str(src), "-o", str(obj)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if cp.returncode:
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — compile")
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
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — capture")
            return 1
        meta = json.loads((out / "meta.json").read_text())
        dis = (out / "disassembly-source.txt").read_text()
        checks = [
            meta["status"] == "CAPTURED_NOT_ADJUDICATED",
            meta["function"] == DEFAULT_FUNCTION,
            len(meta["object_sha256"]) == 64,
            DEFAULT_FUNCTION in dis,
            meta["source_interleave_present"] is True,
            meta["lto_enabled_from_config"] is False,
            (out / "object-header.txt").is_file(),
        ]
        if not all(checks):
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — invariant")
            return 1

        # Fail closed when LTO is enabled but only a pre-link .o is supplied.
        lto_cfg = root / "lto.config"
        lto_cfg.write_text("CONFIG_LTO=y\nCONFIG_LTO_CLANG=y\n")
        bad_lto = argparse.Namespace(**vars(ns))
        bad_lto.out = root / "lto-artifact"
        bad_lto.config = lto_cfg
        if capture(bad_lto) != 2 or bad_lto.out.exists():
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — LTO pre-link negative control")
            return 1

        bad_out = root / "bad-artifact"
        bad = argparse.Namespace(**vars(ns))
        bad.out = bad_out
        bad.function = "definitely_missing_symbol"
        if capture(bad) != 2 or bad_out.exists():
            print("OBJECT_GATE_CAPTURE_SELFTEST: FAIL — missing-symbol negative control")
            return 1
    print("OBJECT_GATE_CAPTURE_SELFTEST: PASS 8/8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("capture", help="capture exact-object evidence; does not adjudicate PASS")
    p.add_argument("object", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--function", default=DEFAULT_FUNCTION)
    p.add_argument("--objdump")
    p.add_argument("--file-tool")
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