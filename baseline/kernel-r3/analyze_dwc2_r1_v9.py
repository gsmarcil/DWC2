#!/usr/bin/env python3
import argparse, json, sys
from dwc2_r1_v9 import *

def main():
    ap=argparse.ArgumentParser(description='Decode/classify DWC2 R1 observer semantic ABI v9 dumps')
    ap.add_argument('trace')
    ap.add_argument('--json',action='store_true')
    a=ap.parse_args()
    try:
        h,recs,sha=parse_file(a.trace)
    except Exception as e:
        print(f'INVALID_FORMAT: {e}',file=sys.stderr); return 2
    he=header_errors(h,negative_gate=False)
    aa=[assess_record(r,i) for i,r in enumerate(recs)]
    out={'sha256':sha,'header':header_to_dict(h),'header_errors':he,
         'records':[assessment_to_dict(x) for x in aa]}
    if a.json:
        print(json.dumps(out,indent=2,sort_keys=True)); return 1 if he or any(x.integrity=='INVALID' for x in aa) else 0
    print(f'sha256={sha}')
    print(f'version={h.version} header={h.header_size} record={h.record_size} count={h.count} lost={h.lost} snapshot_atomic={h.snapshot_atomic}')
    print(f'caps=0x{h.caps_flags:x} target=({h.gsnpsid:08x},{h.ghwcfg2:08x},{h.ghwcfg3:08x},{h.ghwcfg4:08x})')
    print('candidates: cfg0=%d cfgn=%d intf_sync=%d delayed_disable=%d delayed_dequeue=%d overlap=%d' % (
        h.candidate_cfg0_seen,h.candidate_cfgn_seen,h.candidate_intf_seen,
        h.candidate_delayed_disable_seen,h.candidate_delayed_dequeue_seen,h.overlap_count))
    if he: print('HEADER_INVALID: '+','.join(he))
    for x in aa:
        print(f'[{x.index}] {x.r1_state} seq={x.seq} trig={x.trigger} cause={x.cause} caller={x.caller} map={x.mapping} u={x.u_state} bounce={int(x.bounce_active)}' +
              ((' errors='+','.join(x.errors)) if x.errors else ''))
    return 1 if he or any(x.integrity=='INVALID' for x in aa) else 0

if __name__=='__main__': raise SystemExit(main())
