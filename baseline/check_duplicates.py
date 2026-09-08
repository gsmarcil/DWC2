#!/usr/bin/env python3
from pathlib import Path
import hashlib, sys
root=Path(__file__).resolve().parent
pairs=[]
for n,line in enumerate((root/'DUPLICATES.txt').read_text().splitlines(),1):
    line=line.strip()
    if not line or line.startswith('#'): continue
    parts=[x.strip() for x in line.split('|')]
    if len(parts)<2:
        print(f'DUPLICATES.txt:{n}: malformed', file=sys.stderr); sys.exit(2)
    canon=parts[0]
    for dup in parts[1:]: pairs.append((canon,dup))

def h(p): return hashlib.sha256((root/p).read_bytes()).hexdigest()
bad=0
for a,b in pairs:
    pa,pb=root/a,root/b
    if not pa.is_file() or not pb.is_file():
        print(f'MISSING {a if not pa.is_file() else b}'); bad+=1; continue
    ha,hb=h(a),h(b)
    if ha!=hb:
        print(f'MISMATCH {a} {ha} != {b} {hb}'); bad+=1
    else:
        print(f'OK {ha}  {a} == {b}')
print(f'DUPLICATE_CHECK: {"PASS" if not bad else "FAIL"} ({len(pairs)} pair(s))')
sys.exit(1 if bad else 0)
