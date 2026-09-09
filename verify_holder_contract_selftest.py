#!/usr/bin/env python3
"""Discriminating controls for verify_holder_contract.py."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKER = ROOT / "verify_holder_contract.py"
VALIDATOR = ROOT / "baseline" / "pipeline" / "r1a_manifest.py"
MERGER = ROOT / "baseline" / "pipeline" / "holder_merge.py"
CANONICAL_PRODUCER = ROOT / "r1a-device" / "r1a_ffs_out_v2.c"

# The pre-holder source, kept as bytes rather than as a sentence.  This control
# has to keep working after the canonical producer becomes compatible, so it is
# bound to a file that never changes instead of to whatever currently occupies
# the canonical path.  Its identity is asserted below: a fixture that drifted
# would still fail closed, but it would no longer be the source it claims.
LEGACY_PRODUCER = ROOT / "r1a-device" / "legacy" / "r1a_ffs_out_v2.c.pre-holder"
LEGACY_SHA256 = ("83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d"
                 "6116958f126118e")

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
                              "--producer", str(LEGACY_PRODUCER))
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

        require(LEGACY_PRODUCER.is_file(),
                f"the preserved pre-holder source is missing: {LEGACY_PRODUCER}")
        require(hashlib.sha256(LEGACY_PRODUCER.read_bytes()).hexdigest()
                == LEGACY_SHA256,
                "the preserved pre-holder source is no longer the source whose "
                "incompatibility this control asserts")
        legacy = run("--producer", str(LEGACY_PRODUCER))
        require(legacy.returncode == 1 and
                "HOLDER_PRODUCER_CONTRACT: INCOMPATIBLE" in legacy.stdout,
                "preserved pre-holder producer did not produce the expected "
                "closure artifact", legacy)

        canonical = run("--producer", str(CANONICAL_PRODUCER))
        require(canonical.returncode == 0 and
                "HOLDER_PRODUCER_CONTRACT: PASS" in canonical.stdout,
                "the canonical producer in the repository is not accepted by "
                "the checker", canonical)

    print("HOLDER_CONTRACT_SELFTEST: PASS "
          "(2 positive, 10 fail-closed controls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
