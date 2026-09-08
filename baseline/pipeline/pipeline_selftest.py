#!/usr/bin/env python3
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from fixtures import manifest
from dwc2_r1_v9 import HDR,MAGIC,VERSION

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(cmd): return subprocess.run(cmd,capture_output=True,text=True)
def mk_trace(p):
    v=[0]*28; v[0]=MAGIC;v[1]=VERSION;v[2]=112;v[3]=80;v[4]=0;v[5]=0;v[6]=1;v[7]=1;v[8]=0x4f54300a;v[12]=7;v[13]=21;v[16]=1;v[23]=21;v[25]=1
    Path(p).write_bytes(HDR.pack(*v))
def setup(td):
    td=Path(td); tr=td/'S2.bin'; mk_trace(tr); tsha=sha(tr)
    m=manifest('s001',tsha,1,k=1,sens=20,mode='cfg0')
    for sn in m['kernel_window']['snapshots']: sn['count']=0
    m['kernel_window']['record_slice']={'start':0,'end':0}; m['kernel_window']['snapshots'][2]['path']=str(tr)
    m['preflight']['caps']['from_sha256']=tsha; m['artifacts']['dump']={'path':str(tr),'sha256':tsha}
    ea=m['epoch']['artifacts']
    names={'dwc2_r1_v9':'dwc2_r1_v9.py','r1_gate_v9':'r1_gate_v9.py','r1_gate_v9_1':'r1_gate_v9_1.py','manifest_validator':'r1a_manifest.py','usbmon_verifier':'usbmon_verify.py','holder_merger':'holder_merge.py','verdict_generator':'r1_verdict.py'}
    for k,fn in names.items(): ea[k]=sha(HERE/fn)
    cap=td/'cap.mon'; lines=[f'u{i} {100+i} S Bo:1:5:2 -115 16384 =' for i in range(8)]
    lines += ['ctl 200 S Co:1:5:0 s 00 09 0000 0000 0000 0']
    lines += [f'u{i} {300+i} C Bo:1:5:2 0 16384 =' for i in range(8)]
    cap.write_text('\n'.join(lines)+'\n'); m['artifacts']['usbmon']={'path':str(cap),'sha256':sha(cap),'scope':'campaign_only'}
    m['attempts'][0].update(usb_bus=1,usb_device=5,bulk_ep=2)
    base=td/'base.json'; base.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    ev=td/'events.jsonl'; ev.write_text(json.dumps({'event':'R1A_HOLDER','phase':'campaign','session_id':'s001','boot_id':'b-1111','device_seq':1,'pending_reads':8,'utc':'2026-09-07T10:05:00Z'})+'\n')
    return tr,cap,ev,base

def good_pipeline(td):
    tr,cap,ev,base=setup(td); td=Path(td)
    w=td/'wire.json'; b=td/'both.json'; gj=td/'gate.json'; v=td/'verdict.md'
    stages=[
      [sys.executable,str(HERE/'usbmon_verify.py'),'--manifest',str(base),'--usbmon',str(cap),'-o',str(w)],
      [sys.executable,str(HERE/'holder_merge.py'),'--manifest',str(w),'--event-log',str(ev),'--floor','1','-o',str(b)],
      [sys.executable,str(HERE/'r1a_manifest.py'),str(b)],
      [sys.executable,str(HERE/'r1_gate_v9_1.py'),'--mode','cfg0','--min-candidates','1','--manifest',str(b),'--json',str(tr)],
    ]
    for i,c in enumerate(stages,1):
        r=run(c)
        if r.returncode: return False,i,r.stdout+r.stderr,None
        if i==4: gj.write_text(r.stdout)
    r=run([sys.executable,str(HERE/'r1_verdict.py'),'--gate',str(gj),'--manifest',str(b),'--out',str(v)])
    if r.returncode: return False,5,r.stdout+r.stderr,None
    return True,5,'',dict(trace=tr,cap=cap,ev=ev,base=base,wire=w,both=b,gate=gj,verdict=v)

def main():
    fails=0
    with tempfile.TemporaryDirectory() as td:
        ok,stage,out,a=good_pipeline(td); print(('ok  ' if ok else 'FAIL'),'clean pipeline stages=5'); fails += 0 if ok else 1
    # Cross-session holder artifact must die at holder_merge, before validation/gate.
    with tempfile.TemporaryDirectory() as td:
        tr,cap,ev,base=setup(td); td=Path(td); w=td/'wire.json'
        assert run([sys.executable,str(HERE/'usbmon_verify.py'),'--manifest',str(base),'--usbmon',str(cap),'-o',str(w)]).returncode==0
        ev.write_text(json.dumps({'event':'R1A_HOLDER','phase':'campaign','session_id':'OTHER','boot_id':'b-1111','device_seq':1,'pending_reads':8})+'\n')
        r=run([sys.executable,str(HERE/'holder_merge.py'),'--manifest',str(w),'--event-log',str(ev),'-o',str(td/'x.json')])
        ok=r.returncode!=0 and 'different session/boot' in r.stderr; print(('ok  ' if ok else 'FAIL'),'cross-session holder stops at stage 2'); fails += 0 if ok else 1
    # Cross-session usbmon/capture hash must die at stage 1.
    with tempfile.TemporaryDirectory() as td:
        tr,cap,ev,base=setup(td); cap.write_text(cap.read_text()+'foreign 999 S Bo:1:5:2 -115 1 =\n')
        r=run([sys.executable,str(HERE/'usbmon_verify.py'),'--manifest',str(base),'--usbmon',str(cap),'-o',str(Path(td)/'x.json')])
        ok=r.returncode!=0 and 'sha256' in r.stderr; print(('ok  ' if ok else 'FAIL'),'changed capture stops at stage 1'); fails += 0 if ok else 1
    # Gate must catch changed S2 even if merged manifest remains unchanged.
    with tempfile.TemporaryDirectory() as td:
        ok,stage,out,a=good_pipeline(td); assert ok
        Path(a['trace']).write_bytes(Path(a['trace']).read_bytes()+b'X')
        r=run([sys.executable,str(HERE/'r1_gate_v9_1.py'),'--mode','cfg0','--min-candidates','1','--manifest',str(a['both']),'--json',str(a['trace'])])
        ok=r.returncode!=0 and 'INVALID_EVIDENCE_BINDING' in r.stdout; print(('ok  ' if ok else 'FAIL'),'changed trace stops at gate'); fails += 0 if ok else 1
    # Verdict must catch a post-gate manifest substitution.
    with tempfile.TemporaryDirectory() as td:
        ok,stage,out,a=good_pipeline(td); assert ok
        m=json.loads(Path(a['both']).read_text()); m['session']['target']['kernel_release']='other-kernel'; other=Path(td)/'other.json'; other.write_text(json.dumps(m))
        r=run([sys.executable,str(HERE/'r1_verdict.py'),'--gate',str(a['gate']),'--manifest',str(other)])
        ok=r.returncode!=0 and 'manifest_sha256' in r.stderr; print(('ok  ' if ok else 'FAIL'),'changed manifest stops at verdict'); fails += 0 if ok else 1
    print('PIPELINE SELFTEST: %d/5 %s'%(5-fails,'PASS' if not fails else 'FAILED'))
    return 1 if fails else 0
if __name__=='__main__': raise SystemExit(main())
