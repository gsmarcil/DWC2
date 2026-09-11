#!/usr/bin/env python3
"""Discriminating controls for verify_status_sync.py.

The checker's job is to make status-document drift fail closed.  A checker that
only ever passes would silently reintroduce exactly the failure it exists to
prevent, so every rejection path below is exercised against a fixture tree.

The drift being guarded is real and already happened once: the repository
carried a declared RED gate and a producer digest attributed to the wrong path
long after the executable gate had gone green.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKER = ROOT / "verify_status_sync.py"

CANONICAL_PRODUCER = Path("r1a-device/r1a_ffs_out_v2.c")
LEGACY_PRODUCER = Path("r1a-device/legacy/r1a_ffs_out_v2.c.pre-holder")
LEGACY_SHA256 = ("83ea60d3566617eefc0a1b488c2916c0482781b57156d4f0d"
                 "6116958f126118e")

DECLARATION_FILES = (
    Path("docs/GATE-STATE.md"),
    Path("docs/CURRENT-CHECKPOINT.md"),
)

GREEN = ("PASS", "PASS", "PASS", "PASS")

passes = 0
controls = 0


def run(root: Path, *verdicts: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), *verdicts],
        cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )


def require(condition: bool, message: str, result=None) -> None:
    if condition:
        return
    if result is not None:
        print(result.stdout, file=sys.stderr)
    raise SystemExit(f"STATUS_SYNC_SELFTEST: FAIL — {message}")


def positive(root: Path, message: str) -> None:
    global passes
    result = run(root, *GREEN)
    require(result.returncode == 0 and "STATUS_SYNC: PASS" in result.stdout,
            message, result)
    passes += 1


def rejects(root: Path, verdicts, message: str, expect: str = "") -> None:
    global controls
    result = run(root, *verdicts)
    require(result.returncode == 1 and "STATUS_SYNC: FAIL" in result.stdout,
            message, result)
    if expect:
        require(expect in result.stdout,
                f"{message} (rejected, but not for the stated reason)", result)
    controls += 1


def fixture(stack: tempfile.TemporaryDirectory) -> Path:
    """A minimal tree that the checker should accept."""
    root = Path(stack) / "tree"
    if root.exists():
        shutil.rmtree(root)
    (root / "docs").mkdir(parents=True)
    (root / CANONICAL_PRODUCER.parent).mkdir(parents=True)
    (root / LEGACY_PRODUCER.parent).mkdir(parents=True)

    shutil.copy2(ROOT / CANONICAL_PRODUCER, root / CANONICAL_PRODUCER)
    shutil.copy2(ROOT / LEGACY_PRODUCER, root / LEGACY_PRODUCER)

    for rel in DECLARATION_FILES:
        (root / rel).write_text(
            "# fixture\n\n"
            "```text\n"
            "REPOSITORY_BASELINE: PASS\n"
            "SOURCE_FOUNDATION: PASS\n"
            "HOLDER_CAMPAIGN_READINESS: PASS\n"
            "REPOSITORY_GATE: PASS\n"
            "```\n",
            encoding="utf-8",
        )
    return root


def main() -> int:
    # The legacy fixture must still be the source this suite claims it is.
    actual = hashlib.sha256((ROOT / LEGACY_PRODUCER).read_bytes()).hexdigest()
    require(actual == LEGACY_SHA256,
            "preserved pre-holder source does not match the digest these "
            "controls are written against")

    with tempfile.TemporaryDirectory(prefix="dwc2-status-sync-") as name:
        root = fixture(name)
        positive(root, "a truthful declaration tree was not accepted")

        # 1. Stale GREEN: docs claim health the gate did not compute.
        rejects(root, ("PASS", "PASS", "PASS", "FAIL"),
                "a document declaring PASS while the gate computed FAIL "
                "was not rejected",
                expect="REPOSITORY_GATE")

        # 2. Stale RED, the direction that actually drifted here.  A document
        #    declaring a blocker the gate has cleared invites a reader to
        #    "repair" authenticated bytes, so it must fail closed too.
        root = fixture(name)
        (root / DECLARATION_FILES[0]).write_text(
            "```text\n"
            "REPOSITORY_BASELINE: PASS\n"
            "SOURCE_FOUNDATION: PASS\n"
            "HOLDER_CAMPAIGN_READINESS: BLOCKED / PRODUCER INCOMPATIBLE\n"
            "REPOSITORY_GATE: FAIL\n"
            "```\n",
            encoding="utf-8",
        )
        rejects(root, GREEN,
                "a stale RED declaration was not rejected against a green gate",
                expect="HOLDER_CAMPAIGN_READINESS")

        # 3. A declaration file that simply omits a key.
        root = fixture(name)
        text = (root / DECLARATION_FILES[1]).read_text(encoding="utf-8")
        (root / DECLARATION_FILES[1]).write_text(
            text.replace("SOURCE_FOUNDATION: PASS\n", ""), encoding="utf-8")
        rejects(root, GREEN, "a missing status key was not rejected",
                expect="does not declare SOURCE_FOUNDATION")

        # 4. Two disagreeing declarations of the same key in one file: the
        #    checker must not be satisfied by finding one that happens to match.
        root = fixture(name)
        text = (root / DECLARATION_FILES[0]).read_text(encoding="utf-8")
        (root / DECLARATION_FILES[0]).write_text(
            text + "\n```text\nREPOSITORY_GATE: FAIL\n```\n", encoding="utf-8")
        rejects(root, GREEN, "a duplicated, self-contradicting key was not rejected",
                expect="declares REPOSITORY_GATE 2 times")

        # 5. A declaration file deleted outright.
        root = fixture(name)
        (root / DECLARATION_FILES[0]).unlink()
        rejects(root, GREEN, "a missing declaration file was not rejected",
                expect="missing declaration file")

        # 6. The dangerous one: the legacy digest printed under the canonical
        #    path.  Acting on that text overwrites the admitted producer with
        #    the negative control that cannot emit the holder contract.
        root = fixture(name)
        (root / "docs" / "DRIFT.md").write_text(
            "The preserved legacy source is present at:\n\n"
            "```text\n"
            f"{CANONICAL_PRODUCER.as_posix()}\n"
            "```\n\n"
            "```text\n"
            f"SHA256 {LEGACY_SHA256}\n"
            "```\n",
            encoding="utf-8",
        )
        rejects(root, GREEN,
                "a producer digest attributed to the wrong path was not rejected",
                expect="belongs to")

        # 7. A digest cited with no path at all is equally unattributable.
        root = fixture(name)
        (root / "docs" / "DRIFT.md").write_text(
            f"The preserved source has SHA256:\n\n```text\n{LEGACY_SHA256}\n```\n",
            encoding="utf-8",
        )
        rejects(root, GREEN, "an unattributed producer digest was not rejected",
                expect="is not cited near it")

        # 8. Correct attribution of the same digest must still pass, or the
        #    control above would only prove the checker rejects everything.
        root = fixture(name)
        (root / "docs" / "OK.md").write_text(
            "Preserved pre-holder source:\n\n```text\n"
            f"{LEGACY_PRODUCER.as_posix()}\n"
            f"SHA256 {LEGACY_SHA256}\n```\n",
            encoding="utf-8",
        )
        positive(root, "a correctly attributed producer digest was rejected")

        # 9. A producer source that has gone missing cannot be attributed.
        root = fixture(name)
        (root / LEGACY_PRODUCER).unlink()
        rejects(root, GREEN, "a missing producer source was not rejected",
                expect="missing producer source")

        # 10. The authenticated tree is a deliberate, bounded blind spot.
        #     baseline/ may only be repaired by re-importing the same archive,
        #     so a misattribution found there would leave the gate red with no
        #     permitted repair.  The exclusion is asserted here rather than
        #     only claimed in a comment -- and the very same text outside that
        #     tree must still be caught, or the exclusion would be a hole.
        root = fixture(name)
        drift = ("Legacy source at:\n\n```text\n"
                 f"{CANONICAL_PRODUCER.as_posix()}\n```\n\n"
                 f"```text\nSHA256 {LEGACY_SHA256}\n```\n")

        (root / "baseline" / "pipeline").mkdir(parents=True, exist_ok=True)
        (root / "baseline" / "pipeline" / "NOTES.md").write_text(
            drift, encoding="utf-8")
        positive(root, "a misattribution inside the authenticated tree was "
                       "treated as repairable drift")

        (root / "docs" / "DRIFT.md").write_text(drift, encoding="utf-8")
        rejects(root, GREEN,
                "the baseline exclusion also suppressed a misattribution "
                "outside the authenticated tree",
                expect="docs/DRIFT.md")

        # 11. The mirrored misattribution.  The canonical basename is a
        #     prefix of the preserved filename, so a substring match would let
        #     the CANONICAL digest printed under the LEGACY path find its own
        #     basename inside 'r1a_ffs_out_v2.c.pre-holder' and pass.  That
        #     inverts the check silently, so it is pinned here.
        root = fixture(name)
        canonical_sha = hashlib.sha256(
            (ROOT / CANONICAL_PRODUCER).read_bytes()).hexdigest()
        (root / "docs" / "DRIFT.md").write_text(
            "Legacy source at:\n\n```text\n"
            f"{LEGACY_PRODUCER.as_posix()}\n```\n\n"
            f"```text\nSHA256 {canonical_sha}\n```\n",
            encoding="utf-8",
        )
        rejects(root, GREEN,
                "the canonical digest printed under the legacy path was not "
                "rejected; path matching has degraded to substring matching",
                expect="belongs to")

        # 12. A path written relative to the citing document's own directory
        #     is a correct citation and must not be flagged.  Without this the
        #     fix for control 11 would over-tighten into false rejections.
        root = fixture(name)
        (root / "r1a-device" / "README.md").write_text(
            "The preserved source is:\n\n```text\n"
            "legacy/r1a_ffs_out_v2.c.pre-holder\n"
            f"SHA256 {LEGACY_SHA256}\n```\n",
            encoding="utf-8",
        )
        positive(root, "a correct directory-relative citation was rejected")

        # 13. Directory sensitivity.  A same-named file in a different
        #     directory is not the canonical producer, so matching on the bare
        #     basename while ignoring the directory would accept a citation
        #     that names the wrong file.  Control 12 keeps the rule from being
        #     tightened into rejecting honest relative paths; this one keeps it
        #     from being loosened into accepting unrelated ones.
        root = fixture(name)
        (root / "docs" / "DRIFT.md").write_text(
            "Producer source:\n\n```text\n"
            "vendor/third-party/r1a_ffs_out_v2.c\n"
            f"SHA256 {canonical_sha}\n```\n",
            encoding="utf-8",
        )
        rejects(root, GREEN,
                "a digest cited beside a same-named file in an unrelated "
                "directory was not rejected",
                expect="belongs to")

        # 14. Wrong argument count must fail closed, not default to green.
        global controls
        bad = subprocess.run(
            [sys.executable, str(CHECKER), "--root", str(fixture(name)), "PASS"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
        require(bad.returncode == 2 and "STATUS_SYNC: FAIL" in bad.stdout,
                "an incomplete verdict tuple did not fail closed", bad)
        controls += 1

    # Deliberately absent: a control asserting that the LIVE tree matches an
    # all-green verdict.  Whether the live documents match the live gate is the
    # job of the status_sync check itself, which is handed the real computed
    # verdict.  Hardcoding GREEN here would fire spuriously the moment the gate
    # legitimately went red — the documents would correctly declare RED, and
    # this suite would report a guard defect that did not exist.  A selftest
    # validates the checker's logic against fixtures; it does not re-judge the
    # repository.

    print(f"STATUS_SYNC_SELFTEST: PASS "
          f"({passes} positive, {controls} fail-closed controls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
