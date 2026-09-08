#!/usr/bin/env python3
"""Fail closed when the active holder merger has no compatible producer.

This is a structural repository gate, not runtime proof.  It derives whether
``holder_merger`` is active from the validator, confirms the frozen merger's
input contract, then requires the canonical device source to expose the event
log interface and every load-bearing JSONL field consumed by that merger.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_VALIDATOR = ROOT / "baseline" / "pipeline" / "r1a_manifest.py"
DEFAULT_MERGER = ROOT / "baseline" / "pipeline" / "holder_merge.py"
DEFAULT_PRODUCER = ROOT / "r1a-device" / "r1a_ffs_out_v2.c"

EVENT_EQUALS = {
    "event": "R1A_HOLDER",
    "phase": "campaign",
}
EVENT_FIELDS = (
    "pending_reads",
    "session_id",
    "boot_id",
    "device_seq",
)


def parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def literal_assignment(path: Path, name: str):
    for node in parse_python(path).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name
               for target in targets):
            return ast.literal_eval(value)
    raise ValueError(f"{path}: missing literal assignment {name}")


def get_key(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return None
    if not node.args:
        return None
    key = node.args[0]
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value
    return None


def constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def consumer_requirements(path: Path) -> tuple[set[str], dict[str, set[str]], set[str]]:
    tree = parse_python(path)
    fields: set[str] = set()
    equals: dict[str, set[str]] = {}
    options: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            key = get_key(node)
            if key is not None:
                fields.add(key)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                for arg in node.args:
                    value = constant_string(arg)
                    if value and value.startswith("--"):
                        options.add(value)

        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left_key = get_key(node.left)
            right_value = constant_string(node.comparators[0])
            right_key = get_key(node.comparators[0])
            left_value = constant_string(node.left)
            if left_key is not None and right_value is not None:
                equals.setdefault(left_key, set()).add(right_value)
            if right_key is not None and left_value is not None:
                equals.setdefault(right_key, set()).add(left_value)

    return fields, equals, options


def c_string_literals(text: str) -> list[str]:
    """Extract decoded C string literals while ignoring comments and chars."""
    strings: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated C block comment")
            i = end + 2
            continue
        if text[i] == "'":
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            continue
        if text[i] != '"':
            i += 1
            continue

        i += 1
        buf: list[str] = []
        while i < n:
            ch = text[i]
            if ch == '"':
                i += 1
                strings.append("".join(buf))
                break
            if ch == "\\" and i + 1 < n:
                esc = text[i + 1]
                decoded = {"n": "\n", "r": "\r", "t": "\t", '"': '"',
                           "\\": "\\"}.get(esc, esc)
                buf.append(decoded)
                i += 2
                continue
            buf.append(ch)
            i += 1
        else:
            raise ValueError("unterminated C string literal")
    return strings


def report(label: str, ok: bool, detail: str = "") -> None:
    suffix = "PASS" if ok else "FAIL"
    if detail:
        suffix += f" — {detail}"
    print(f"{label:34s} {suffix}")


def check(validator: Path, merger: Path, producer: Path) -> int:
    try:
        keyset = literal_assignment(validator, "EPOCH_ARTIFACTS")
    except Exception as exc:
        print(f"HOLDER_CONTRACT_ERROR: cannot derive epoch keyset: {exc}", file=sys.stderr)
        return 2
    if not isinstance(keyset, (tuple, list)) or not all(isinstance(k, str) for k in keyset):
        print("HOLDER_CONTRACT_ERROR: EPOCH_ARTIFACTS is not a literal string sequence",
              file=sys.stderr)
        return 2

    active = "holder_merger" in keyset
    report("epoch_holder_merger", True, "active" if active else "not active")
    if not active:
        print("HOLDER_PRODUCER_CONTRACT: NOT REQUIRED")
        return 0

    try:
        fields, equals, options = consumer_requirements(merger)
    except Exception as exc:
        print(f"HOLDER_CONTRACT_ERROR: cannot inspect holder merger: {exc}", file=sys.stderr)
        return 2

    consumer_ok = True
    for field, value in EVENT_EQUALS.items():
        ok = field in fields and value in equals.get(field, set())
        report(f"consumer_{field}_{value}", ok)
        consumer_ok &= ok
    for field in EVENT_FIELDS:
        ok = field in fields
        report(f"consumer_{field}", ok)
        consumer_ok &= ok
    option_ok = "--event-log" in options
    report("consumer_event_log_cli", option_ok)
    consumer_ok &= option_ok
    if not consumer_ok:
        print("HOLDER_PRODUCER_CONTRACT: CONSUMER CONTRACT DRIFT")
        return 2

    try:
        literals = c_string_literals(producer.read_text())
    except Exception as exc:
        print(f"HOLDER_CONTRACT_ERROR: cannot inspect device producer: {exc}", file=sys.stderr)
        return 2
    joined = "\n".join(literals)

    producer_checks = [
        ("producer_event_log_cli", "--event-log" in joined),
        ("producer_R1A_HOLDER", '"event"' in joined and "R1A_HOLDER" in joined),
        ("producer_phase_campaign", '"phase"' in joined and "campaign" in joined),
    ]
    producer_checks.extend(
        (f"producer_{field}", f'"{field}"' in joined) for field in EVENT_FIELDS
    )
    for label, ok in producer_checks:
        report(label, ok)

    if not all(ok for _, ok in producer_checks):
        print("HOLDER_PRODUCER_CONTRACT: INCOMPATIBLE")
        return 1
    print("HOLDER_PRODUCER_CONTRACT: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validator", type=Path, default=DEFAULT_VALIDATOR)
    ap.add_argument("--merger", type=Path, default=DEFAULT_MERGER)
    ap.add_argument("--producer", type=Path, default=DEFAULT_PRODUCER)
    args = ap.parse_args(argv)
    return check(args.validator.resolve(), args.merger.resolve(), args.producer.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
