#!/usr/bin/env python3
"""v6.3 ABI gate: driver layout vs analyzer layout. Self-contained.

Builds its own probe from abi_probe.c -- it does not depend on a binary
someone else left lying around. Give it --gadget to regenerate the probe from
a live patched tree first, which is the only mode that proves the ABI of THAT
tree rather than of a snapshot.

Checks three things the driver's static_asserts cannot:

  1. no implicit padding holes -- every field starts where the previous ended.
     A struct can satisfy sizeof() and still put fields where an analyzer
     will not find them.
  2. the sizes and field counts the analyzer asserts
  3. a record packed with the analyzer's format string reads back correctly at
     the offsets the driver reports

  usage:
    abi_check.py                       # use the shipped abi_probe.c
    abi_check.py --gadget .../gadget.c # regenerate from a live tree first
"""
import argparse
import os
import shutil
import struct
import subprocess
import signal
import sys
import tempfile

# A gate piped into head must not die with a traceback.
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

REC_FMT = '<IHHHHHBBBBBBIIIIIIIQQIIHHHH'
HDR_FMT = '<' + 'I' * 28
EXPECT_REC, EXPECT_HDR = 80, 112

HERE = os.path.dirname(os.path.abspath(__file__))


def build_and_run(src, cc):
    """Compile the probe into a temp dir and run it. Never writes next to src."""
    tmp = tempfile.mkdtemp(prefix='abi_probe.')
    try:
        exe = os.path.join(tmp, 'abi_probe')
        r = subprocess.run([cc, '-O0', '-Wall', '-Wextra', '-Werror',
                            '-o', exe, src],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit('compiling %s with %s failed:\n%s' % (src, cc, r.stderr))
        return subprocess.run([exe], capture_output=True, text=True,
                              check=True).stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse(out):
    sections, cur = {}, None
    for line in out.split('\n'):
        if line.startswith('struct '):
            cur = line.split()[1]
            sections[cur] = {'size': int(line.split('size=')[1]),
                             'fields': []}
        elif cur and line.strip() and not line.startswith('field'):
            p = line.split()
            if len(p) == 3 and p[1].isdigit():
                sections[cur]['fields'].append((p[0], int(p[1]), int(p[2])))
    return sections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gadget', help='patched gadget.c: regenerate the probe '
                                     'from it before checking')
    ap.add_argument('--probe-src', default=os.path.join(HERE, 'abi_probe.c'))
    ap.add_argument('--cc', default=os.environ.get('CC') or
                    shutil.which('cc') or shutil.which('gcc'))
    a = ap.parse_args()

    if not a.cc:
        sys.exit('no C compiler found; set CC or install cc/gcc')

    src = a.probe_src
    tmpdir = None
    if a.gadget:
        gen = os.path.join(HERE, 'gen_abi_probe.py')
        if not os.path.exists(gen):
            sys.exit('--gadget needs gen_abi_probe.py beside this script')
        tmpdir = tempfile.mkdtemp(prefix='abi_gen.')
        src = os.path.join(tmpdir, 'abi_probe.c')
        subprocess.run([sys.executable, gen, a.gadget, '-o', src], check=True)
        print('regenerated probe from %s\n' % a.gadget)
    if not os.path.exists(src):
        sys.exit('probe source not found: %s' % src)

    try:
        sections = parse(build_and_run(src, a.cc))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    fails = []

    def need(ok, msg):
        print(('  ok   ' if ok else '  FAIL ') + msg)
        if not ok:
            fails.append(msg)

    for name, want in (('dwc2_r1_rec', EXPECT_REC),
                       ('dwc2_r1_dump_hdr', EXPECT_HDR)):
        if name not in sections:
            need(False, '%s present in probe output' % name)
            continue
        sec = sections[name]
        print('%s (size %d)' % (name, sec['size']))
        need(sec['size'] == want, 'size is %d' % want)

        pos, holes = 0, []
        for fname, off, sz in sec['fields']:
            if off != pos:
                holes.append('%s at %d, expected %d' % (fname, off, pos))
            pos = off + sz
        need(not holes,
             'no padding holes' + ('' if not holes else ': ' + '; '.join(holes)))
        need(pos == sec['size'],
             'fields fill the struct (%d of %d)' % (pos, sec['size']))
        print()

    if fails:
        print('V6.3 ABI CHECK: %d FAILURE(S)' % len(fails))
        return 1

    print('analyzer format strings')
    need(struct.calcsize(REC_FMT) == EXPECT_REC,
         'REC_FMT packs to %d' % EXPECT_REC)
    need(struct.calcsize(HDR_FMT) == EXPECT_HDR,
         'HDR_FMT packs to %d' % EXPECT_HDR)
    need(len(struct.unpack(REC_FMT, b'\0' * EXPECT_REC)) ==
         len(sections['dwc2_r1_rec']['fields']),
         'REC_FMT field count matches the struct')
    need(len(struct.unpack(HDR_FMT, b'\0' * EXPECT_HDR)) ==
         len(sections['dwc2_r1_dump_hdr']['fields']),
         'HDR_FMT field count matches the struct')
    print()

    print('round-trip: pack a record, read fields back at driver offsets')
    vals = (0x11223344, 1, 0xbeef, 0x0102, 0x0304, 0x0506, 0x21, 0x0b, 3, 4,
            2, 3, 0xaaaa0001, 0xaaaa0002, 0xaaaa0003, 0xaaaa0004, 0xaaaa0005,
            0xaaaa0006, 0xfffffff5, 0x1122334455667788, 0x00000000deadbeef,
            4096, 512, 0, 0, 0x0019, 2)
    blob = struct.pack(REC_FMT, *vals)
    need(len(blob) == EXPECT_REC, 'packed record is %d bytes' % EXPECT_REC)
    by_name = {f: (o, s) for f, o, s in sections['dwc2_r1_rec']['fields']}
    for fname, want in (('setup_cookie', 0x1122334455667788),
                        ('req_dma', 0xdeadbeef),
                        ('causal_state', 2), ('mapping_class', 3),
                        ('flags2', 0x0019), ('owner_cpu', 2),
                        ('req_length', 4096)):
        off, sz = by_name[fname]
        got = int.from_bytes(blob[off:off + sz], 'little')
        need(got == want, '%s at offset %d reads 0x%x' % (fname, off, want))

    print()
    if fails:
        print('V6.3 ABI CHECK: %d FAILURE(S)' % len(fails))
        return 1
    print('V6.3 ABI CHECK: all checks passed')
    return 0


sys.exit(main())
