# Evidence discrimination: what four artifacts cannot tell apart

A full duplicate census across `baseline/`, `r1a-host/` and `r1a-device/` found
seven byte-identical groups. Three are declared in the authenticated
`baseline/DUPLICATES.txt`. Four were not visible to any checker in the
repository, because the pinned `baseline/check_duplicates.py` can only confirm
the pairs that file already lists, and it is rooted inside `baseline/` so it
cannot see cross-tree identity at all.

The duplication is the symptom. The finding is that four artifacts carry no
content capable of discriminating the thing they are relied on to establish.

```text
census at   1cdaf8f, trees baseline/ r1a-host/ r1a-device/
groups      7 identical
declared    3 in the authenticated declaration
recorded    4 in DUPLICATES-OVERLAY.txt
```

## The build logs

```text
baseline/kernel-r3/evidence/build-v631-arm-n.log
  == .../v632-structural/build-v632-arm-n.log        86de8e468ec7

baseline/kernel-r3/evidence/build-v631-arm-y.log
  == .../v632-structural/build-v632-arm-y.log        d7bca5094932
```

`NOTES.md` presents the `v632-structural/` files as build evidence for the
structural source, with `ARM observer=y W=1: RC=0` and `observer=n W=1: RC=0`.

Each log is six lines:

```text
make[1]: Entering directory '/home/claude/b-arm-n'
  UPD     include/config/kernel.release
  UPD     include/generated/utsrelease.h
  CC      drivers/usb/dwc2/gadget.o
  AR      drivers/usb/dwc2/built-in.a
make[1]: Leaving directory '/home/claude/b-arm-n'
```

No version string, no kernel release, no timestamp, no source identity. Grepping
for `6.3.1`, `6.3.2`, `v631` or `v632` inside them returns zero hits.

**Stated precisely.** Two builds of different sources in the same build directory
would produce byte-identical logs. The identity is therefore *not* evidence of
copying. Equally, the log is *not* evidence of a v632 build: it contains nothing
that distinguishes one source version from another. It is consistent with an
honest rebuild and with a copy, and it cannot separate them.

The conclusion is about the artifact, not about anyone's conduct: this log class
is incapable of evidencing which source was built. The byte identity only makes
that visible.

## The cross-architecture ABI dumps

```text
baseline/kernel-r3/evidence/abi-layout-arm32.txt
  == baseline/kernel-r3/evidence/abi-layout-x86_64.txt   ac55fbc45a1e
```

This one is the opposite of what it first looks like, and the difference matters.

`abi-cross-arch.txt` reads `ARM32 == x86_64 layout: IDENTICAL`, and
`VERIFY_v6.3.1.sh:74` asserts that string is present. Identity between the two
dumps is the **intended** result. The record struct is fixed-width with no holes
at `size=80`, so two independently generated dumps *should* be byte-identical.
Reporting the identity as a defect would be wrong.

What the pair cannot do is demonstrate that two independent generations
occurred. Neither file records the architecture it was produced on, nor a
toolchain, nor a timestamp. Grepping either for `arm`, `x86` or `aarch` returns
nothing.

**Stated precisely.** The identity is expected and is consistent with genuine
cross-architecture agreement. It is equally consistent with one dump copied to
two filenames. The artifacts carry nothing that separates the readings, so the
cross-architecture claim rests on the filenames rather than on the contents.

## Why this could not be caught from inside

`baseline/` is authenticated. Neither `DUPLICATES.txt` nor
`check_duplicates.py` may be extended to record the missing groups, because the
edit would have to be laundered through a regenerated `SHA256SUMS`. That is the
exact failure mode `verify_archive_tracking.py` exists to catch, and it is what
`NO-BASELINE-EDIT-RULE.md` forbids.

So the census lives outside the tree, reads the authenticated declaration
read-only, and records additions in `DUPLICATES-OVERLAY.txt`. Declarations are
merged transitively before comparison, because two disjoint pairs do not cover a
group of three.

## What this costs, and what it does not

```text
does NOT   invalidate the v6.3.1 structural work, the ABI record layout, or
           any gate result. Nothing here touches the source-level findings.

does NOT   show that any artifact was fabricated. Both readings remain open
           precisely because the artifacts cannot discriminate.

DOES       remove "v632-structural is an independent build" from the set of
           things this repository can demonstrate with the files it holds.

DOES       remove "the ABI layout was verified on two architectures" from the
           same set. The agreement is asserted by a filename pair and a
           one-line report, not by discriminating content.
```

## What a future epoch should carry

Neither gap needs new research to close. Both need the artifacts to record what
they were produced from:

```text
build logs      kernel release, source commit or version string, toolchain
                triple, and the config used, inside the log itself

ABI dumps       the architecture and compiler that produced the dump, inside
                the dump, so that two files agreeing is a fact about two
                generations rather than about two filenames
```

Until then, both rows are recorded in `DUPLICATES-OVERLAY.txt` as known and
accounted for, not as harmless.

No evidence is promoted or demoted on the DWC2 ladder by this document. `K_hw`
remains `UNDETERMINED`.
