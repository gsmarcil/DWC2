#!/usr/bin/env python3
"""Derive the host-wire precondition from a usbmon text capture.

This tool never trusts the harness' inflight counter. It replays Bulk OUT URB
submit/completion events from usbmon and samples that set at each exact raw EP0
trigger submit. Campaign triggers are paired to manifest attempts by order.

Only usbmon text output is accepted. Binary pcap must be converted to the text
API first; silently guessing a capture format would turn a parse failure into a
false negative.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, sys
from pathlib import Path

LINE = re.compile(r'^(\S+)\s+(\d+)\s+([SCE])\s+([A-Za-z]{2}):(\d+):(\d+):(\d+)\s*(.*)$')
HEX4 = re.compile(r'^[0-9a-fA-F]{4}$')
HEX2 = re.compile(r'^[0-9a-fA-F]{2}$')

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def setup_from_tail(tail):
    t=tail.split()
    for i,x in enumerate(t):
        if x.lower()=='s' and i+5 < len(t):
            b0,b1,wv,wi,wl=t[i+1:i+6]
            if HEX2.match(b0) and HEX2.match(b1) and all(HEX4.match(x) for x in (wv,wi,wl)):
                return (int(b0,16),int(b1,16),int(wv,16),int(wi,16),int(wl,16))
    return None

def verify(m, cap_path):
    cap_sha=sha256(cap_path)
    art=((m.get('artifacts') or {}).get('usbmon') or {})
    errs=[]
    if art.get('sha256') != cap_sha:
        errs.append('capture sha256 does not match artifacts.usbmon.sha256')
    trig=((m.get('session') or {}).get('trigger') or {})
    try:
        want=(int(trig['bmRequestType']),int(trig['bRequest']),int(trig['wValue']),int(trig['wIndex']),int(trig['wLength']))
    except Exception:
        return None,['session.trigger is incomplete']
    mode=(m.get('session') or {}).get('mode')
    restore=(m.get('session') or {}).get('restore_cfg')
    if mode=='cfgn' and want[1]==9 and want[2]==restore:
        errs.append('cfgn campaign trigger is indistinguishable from raw restore in usbmon; use a destructive single-attempt epoch or a distinguishable trigger')

    attempts=[a for a in (m.get('attempts') or []) if a.get('trigger_attempted')]
    active={}
    rows=[]; matched=0; matching_controls=0; bulk_seen=0
    lines=Path(cap_path).read_text(errors='replace').splitlines()
    for lnno,line in enumerate(lines,1):
        mm=LINE.match(line.strip())
        if not mm: continue
        tag,ts,ev,typ,bus,dev,ep,tail=mm.groups()
        bus=int(bus); dev=int(dev); ep=int(ep)
        if typ=='Bo':
            if ev=='S':
                active[tag]=(bus,dev,ep); bulk_seen+=1
            elif ev in ('C','E'):
                active.pop(tag,None)
            continue
        if typ!='Co' or ev!='S': continue
        st=setup_from_tail(tail)
        if st != want: continue
        matching_controls += 1
        if matched >= len(attempts):
            continue
        a=attempts[matched]
        eb=a.get('usb_bus'); ed=a.get('usb_device'); eep=a.get('bulk_ep')
        if (bus,dev)!=(eb,ed):
            continue
        n=sum(1 for b,d,e in active.values() if (b,d,e)==(bus,dev,eep & 0x0f))
        internal=((a.get('outstanding') or {}).get('inflight_at_trigger'))
        agree=isinstance(internal,int) and n==internal
        qualifies=n>=1
        rows.append({'n':a.get('n'),'control_line':lnno,'control_us':int(ts),
                     'control_setup':'%02x %02x %04x %04x %04x'%want,
                     'wire_inflight_at_control':n,
                     'internal_inflight_at_trigger':internal,
                     'agree':agree,'qualifies':qualifies})
        matched += 1
    by_n={r['n']:r for r in rows}
    for a in attempts:
        if a.get('n') not in by_n:
            rows.append({'n':a.get('n'),'control_line':None,'control_us':None,
                         'control_setup':'%02x %02x %04x %04x %04x'%want,
                         'wire_inflight_at_control':None,
                         'internal_inflight_at_trigger':((a.get('outstanding') or {}).get('inflight_at_trigger')),
                         'agree':False,'qualifies':False})
    rows.sort(key=lambda r:(r['n'] is None,r['n']))
    agree=sum(r['agree'] for r in rows); qual=sum(r['qualifies'] for r in rows)
    extra=max(0,matching_controls-len(attempts))
    verdict='WIRE_CONFIRMED'
    if extra or len(rows)!=len(attempts) or agree!=len(attempts) or qual!=len(attempts):
        verdict='WIRE_PRECONDITION_FAILED'
    wire={'protocol':'usbmon_post_hoc','capture_sha256':cap_sha,
          'bulk_urbs_seen':bulk_seen,'control_submissions_seen':matching_controls,
          'attempts_fired':len(attempts),'extra_controls':extra,
          'agree_count':agree,'qualify_count':qual,'attempts':rows,'verdict':verdict}
    return wire,errs

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',required=True); ap.add_argument('--usbmon',required=True)
    ap.add_argument('-o','--out',required=True)
    a=ap.parse_args()
    try: m=json.loads(Path(a.manifest).read_text())
    except Exception as e: print('WIRE INPUT ERROR:',e,file=sys.stderr); return 2
    try: wire,errs=verify(m,a.usbmon)
    except Exception as e: print('WIRE PARSE ERROR:',e,file=sys.stderr); return 2
    if errs:
        for x in errs: print('WIRE REJECT:',x,file=sys.stderr)
        return 1
    out=copy.deepcopy(m); out['wire']=wire
    Path(a.out).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('%s (%d/%d qualify, extra=%d)'%(wire['verdict'],wire['qualify_count'],wire['attempts_fired'],wire['extra_controls']))
    return 0 if wire['verdict']=='WIRE_CONFIRMED' else 1
if __name__=='__main__': raise SystemExit(main())
