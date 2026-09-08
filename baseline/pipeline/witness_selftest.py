#!/usr/bin/env python3
import copy,hashlib,json,tempfile,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
from fixtures import manifest,sha
from usbmon_verify import verify
from holder_merge import merge

def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def base(td):
 m=manifest('s001',sha('d'),1,k=1,sens=20,mode='cfg0'); a=m['attempts'][0]; a.update(usb_bus=1,usb_device=5,bulk_ep=2); a['outstanding']['inflight_at_trigger']=1
 cap=Path(td)/'c.mon'; cap.write_text('u 1 S Bo:1:5:2 -115 16 =\nctl 2 S Co:1:5:0 s 00 09 0000 0000 0000 0\nu 3 C Bo:1:5:2 0 16 =\n')
 m['artifacts']['usbmon']={'path':str(cap),'sha256':h(cap),'scope':'campaign_only'}
 ev=Path(td)/'e.jsonl'; ev.write_text(json.dumps({'event':'R1A_HOLDER','phase':'campaign','session_id':'s001','boot_id':'b-1111','device_seq':1,'pending_reads':8})+'\n')
 return m,cap,ev

def main():
 fails=0
 with tempfile.TemporaryDirectory() as td:
  m,c,e=base(td); w,er=verify(m,c); ok=not er and w['verdict']=='WIRE_CONFIRMED'; print(('ok  ' if ok else 'FAIL'),'wire good'); fails+=not ok
 with tempfile.TemporaryDirectory() as td:
  m,c,e=base(td); c.write_text('u 1 S Bo:1:5:2 -115 16 =\nu 2 C Bo:1:5:2 0 16 =\nctl 3 S Co:1:5:0 s 00 09 0000 0000 0000 0\n'); m['artifacts']['usbmon']['sha256']=h(c); w,er=verify(m,c); ok=not er and w['verdict']=='WIRE_PRECONDITION_FAILED'; print(('ok  ' if ok else 'FAIL'),'bulk completed before control'); fails+=not ok
 with tempfile.TemporaryDirectory() as td:
  m,c,e=base(td); hold,hs=merge(m,e,1); ok=hold['verdict']=='HOLDER_CONFIRMED'; print(('ok  ' if ok else 'FAIL'),'holder good'); fails+=not ok
 with tempfile.TemporaryDirectory() as td:
  m,c,e=base(td); e.write_text(json.dumps({'event':'R1A_HOLDER','phase':'campaign','session_id':'OTHER','boot_id':'b-1111','pending_reads':8})+'\n')
  try: merge(m,e,1); ok=False
  except ValueError: ok=True
  print(('ok  ' if ok else 'FAIL'),'holder cross-session rejected'); fails+=not ok
 print('WITNESS SELFTEST: %d/4 %s'%(4-fails,'PASS' if not fails else 'FAILED')); return 1 if fails else 0
if __name__=='__main__': raise SystemExit(main())
