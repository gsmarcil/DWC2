#!/usr/bin/env python3
"""Discriminating controls for verify_holder_contract.py."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKER = ROOT / "verify_holder_contract.py"
VALIDATOR = ROOT / "baseline" / "pipeline" / "r1a_manifest.py"
MERGER = ROOT / "baseline" / "pipeline" / "holder_merge.py"
CURRENT_PRODUCER = ROOT / "r1a-device" / "r1a_ffs_out_v2.c"

VALID_SOURCE = r'''
static const char *option = "--event-log";
static const char *event =
    "{\"event\":\"R1A_HOLDER\",\"phase\":\"campaign\","
    "\"pending_reads\":1,\"session_id\":\"s\",\"boot_id\":\"b\","
    "\"device_seq\":1}\\n";
'''


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CHECKER), *args], cwd=ROOT,
                          text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)


def require(condition: bool, message: str, result=None) -> None:
    if condition:
        return
    if result is not None:
        print(result.stdout, file=sys.stderr)
    raise SystemExit(f"HOLDER_CONTRACT_SELFTEST: FAIL — {message}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dwc2-holder-contract-") as name:
        temp = Path(name)
        producer = temp / "producer.c"
        producer.write_text(VALID_SOURCE)

        positive = run("--producer", str(producer))
        require(positive.returncode == 0 and
                "HOLDER_PRODUCER_CONTRACT: PASS" in positive.stdout,
                "compatible producer was not accepted", positive)

        mutations = (
            "--event-log", "R1A_HOLDER", "campaign", "pending_reads",
            "session_id", "boot_id", "device_seq",
        )
        for token in mutations:
            producer.write_text(VALID_SOURCE.replace(token, "MISSING_TOKEN"))
            negative = run("--producer", str(producer))
            require(negative.returncode == 1 and
                    "HOLDER_PRODUCER_CONTRACT: INCOMPATIBLE" in negative.stdout,
                    f"missing producer token {token!r} did not fail closed", negative)

        inactive = temp / "inactive_validator.py"
        inactive.write_text("EPOCH_ARTIFACTS = ('harness',)\n")
        inactive_result = run("--validator", str(inactive),
                              "--producer", str(CURRENT_PRODUCER))
        require(inactive_result.returncode == 0 and
                "HOLDER_PRODUCER_CONTRACT: NOT REQUIRED" in inactive_result.stdout,
                "inactive holder merger did not bypass the producer requirement",
                inactive_result)

        drifted = temp / "holder_merge.py"
        drifted.write_text(MERGER.read_text().replace("'boot_id'", "'old_boot_id'"))
        drift_result = run("--merger", str(drifted), "--producer", str(producer))
        require(drift_result.returncode == 2 and
                "CONSUMER CONTRACT DRIFT" in drift_result.stdout,
                "consumer drift was not distinguished from producer incompatibility",
                drift_result)

        current = run("--producer", str(CURRENT_PRODUCER))
        require(current.returncode == 1 and
                "HOLDER_PRODUCER_CONTRACT: INCOMPATIBLE" in current.stdout,
                "current legacy producer did not produce the expected closure artifact",
                current)

    print("HOLDER_CONTRACT_SELFTEST: PASS (1 positive, 9 fail-closed controls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
