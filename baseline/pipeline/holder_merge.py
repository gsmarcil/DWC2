#!/usr/bin/env python3
"""Bind gadget-side queued-read depth to a campaign manifest.

The event log is an independent artifact. Campaign teardown events are paired
by order, never by comparing clocks across machines. The log must explicitly
mark campaign events; unmarked preflight/re-arm disables are not guessed away.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, sys
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def load_events(path):
    out=[]
    for n,line in enumerate(Path(path).read_text().splitlines(),1):
        if not line.strip(): continue
        try: o=json.loads(line)
        except Exception as e: raise ValueError('event log line %d: %s'%(n,e))
        if o.get('event')=='R1A_HOLDER' and o.get('phase')=='campaign': out.append(o)
    return out

def merge(m,path,floor):
    sha=sha256(path); events=load_events(path)
    sess=(m.get('session') or {})
    sid,bid=sess.get('session_id'),sess.get('boot_id')
    foreign=[e for e in events if e.get('session_id') != sid or e.get('boot_id') != bid]
    if foreign:
        raise ValueError('campaign holder event belongs to a different session/boot')
    attempts=[a for a in (m.get('attempts') or []) if a.get('trigger_attempted')]
    rows=[]
    for i,a in enumerate(attempts):
        ev=events[i] if i<len(events) else None
        p=ev.get('pending_reads') if ev else None
        ok=isinstance(p,int) and p>=floor
        rows.append({'n':a.get('n'),'device_seq':ev.get('device_seq') if ev else None,
                     'pending_reads':p,'meets_floor':ok,
                     'device_t_utc':ev.get('utc') if ev else None})
    extra=max(0,len(events)-len(attempts)); meet=sum(r['meets_floor'] for r in rows)
    verdict='HOLDER_CONFIRMED' if len(events)==len(attempts) and meet==len(attempts) else 'HOLDER_BELOW_FLOOR'
    hold={'protocol':'device_teardown_depth','pairing':'by_order_not_by_clock','floor':floor,
          'session_id':sid,'boot_id':bid,
          'event_log_sha256':sha,'device_teardowns_seen':len(events),'attempts_fired':len(attempts),
          'extra_teardowns':extra,'meets_floor_count':meet,'attempts':rows,'verdict':verdict}
    return hold,sha

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--manifest',required=True); ap.add_argument('--event-log',required=True)
    ap.add_argument('--floor',type=int,default=1); ap.add_argument('-o','--out',required=True)
    a=ap.parse_args()
    if a.floor<1: ap.error('--floor must be >=1')
    try: m=json.loads(Path(a.manifest).read_text()); hold,sha=merge(m,a.event_log,a.floor)
    except Exception as e: print('HOLDER INPUT ERROR:',e,file=sys.stderr); return 2
    out=copy.deepcopy(m); out['holder']=hold
    out.setdefault('artifacts',{})['holder_event_log']={'path':a.event_log,'sha256':sha}
    Path(a.out).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('%s (%d/%d meet floor, extra=%d)'%(hold['verdict'],hold['meets_floor_count'],hold['attempts_fired'],hold['extra_teardowns']))
    return 0 if hold['verdict']=='HOLDER_CONFIRMED' else 1
if __name__=='__main__': raise SystemExit(main())
