#!/usr/bin/env python3
import copy, hashlib, json, struct, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from fixtures import manifest
from dwc2_r1_v9 import HDR,MAGIC,VERSION
from usbmon_verify import verify as verify_wire
from holder_merge import merge as merge_holder
from r1_gate_v9_1 import outcome, sha256_file

def mk_trace(path,cand=1):
    v=[0]*28
    v[0]=MAGIC; v[1]=VERSION; v[2]=112; v[3]=80; v[4]=0; v[5]=0; v[6]=1; v[7]=1
    v[8]=0x4f54300a; v[12]=7; v[13]=21; v[16]=cand; v[23]=21; v[25]=1
    Path(path).write_bytes(HDR.pack(*v))

def toolhash(fn): return sha256_file(HERE/fn)

def base(td):
    td=Path(td); tr=td/'S2.bin'; mk_trace(tr,1); tsha=sha256_file(tr)
    m=manifest('s001',tsha,b_valid=1,k=1,sens=20,mode='cfg0')
    # No timeout records; the candidate counter is independent of record count.
    for sn in m['kernel_window']['snapshots']: sn['count']=0
    m['kernel_window']['record_slice']={'start':0,'end':0}
    m['kernel_window']['snapshots'][2]['path']=str(tr)
    m['preflight']['caps']['from_sha256']=tsha
    m['artifacts']['dump']={'path':str(tr),'sha256':tsha}
    # Actual epoch hashes for every tool v9.1 can independently verify.
    ea=m['epoch']['artifacts']
    ea.update({'dwc2_r1_v9':toolhash('dwc2_r1_v9.py'),'r1_gate_v9':toolhash('r1_gate_v9.py'),
               'r1_gate_v9_1':toolhash('r1_gate_v9_1.py'),'manifest_validator':toolhash('r1a_manifest.py'),
               'usbmon_verifier':toolhash('usbmon_verify.py'),'holder_merger':toolhash('holder_merge.py'),
               'verdict_generator':toolhash('r1_verdict.py')})
    # One attempt, eight host URBs outstanding at the raw cfg0 control.
    cap=td/'cap.mon'; lines=[]
    for i in range(8): lines.append('u%d %d S Bo:1:5:2 -115 16384 ='%(i,100+i))
    lines.append('ctl 200 S Co:1:5:0 s 00 09 0000 0000 0000 0')
    for i in range(8): lines.append('u%d %d C Bo:1:5:2 0 16384 ='%(i,300+i))
    cap.write_text('\n'.join(lines)+'\n'); csha=sha256_file(cap)
    m['artifacts']['usbmon']={'path':str(cap),'sha256':csha,'scope':'campaign_only'}
    a=m['attempts'][0]; a.update(usb_bus=1,usb_device=5,bulk_ep=2)
    wire,errs=verify_wire(m,cap); assert not errs; m['wire']=wire
    ev=td/'events.jsonl'; ev.write_text(json.dumps({'event':'R1A_HOLDER','phase':'campaign','session_id':'s001','boot_id':'b-1111','device_seq':1,'pending_reads':8,'utc':'2026-09-07T10:05:00Z'})+'\n')
    hold,hsha=merge_holder(m,ev,1); m['holder']=hold; m['artifacts']['holder_event_log']={'path':str(ev),'sha256':hsha}
    mp=td/'m.json'; mp.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    return tr,mp,m

def chk(name,mut,want,substr=None):
    with tempfile.TemporaryDirectory() as td:
        tr,mp,m=base(td); mut(Path(td),tr,mp,m); mp.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
        o=outcome([str(tr)],[str(mp)],'cfg0',1); got=o['verdict']; ok=got==want and (substr is None or substr in json.dumps(o))
        print(('ok  ' if ok else 'FAIL'),name,'->',got)
        if not ok: print(json.dumps(o,indent=2))
        return ok

def noop(td,tr,mp,m): pass

def wrong_sha(td,tr,mp,m): m['artifacts']['dump']['sha256']='0'*64; m['preflight']['caps']['from_sha256']='0'*64; m['kernel_window']['snapshots'][2]['sha256']='0'*64

def other_wire(td,tr,mp,m):
    m['wire']['capture_sha256']='1'*64

def other_holder(td,tr,mp,m): m['holder']['event_log_sha256']='2'*64

def bad_tool(td,tr,mp,m): m['epoch']['artifacts']['usbmon_verifier']='3'*64

def slice_bad(td,tr,mp,m): m['kernel_window']['record_slice']['start']=1

def zero_b(td,tr,mp,m):
    m['attempts'][0]['valid']=False; m['attempts'][0]['trigger_attempted']=False; m['attempts'][0]['invalid_reason']='not_outstanding'; m['attempts'][0]['outstanding']['inflight_at_trigger']=0; m['attempts'][0]['outstanding']['urb_completed']=True
    m['denominator'].update(B_valid=0,B_invalid=1,invalid_reasons={'not_outstanding':1},kernel_delta=0,relation_ok=False)
    m['kernel_window']['campaign'].update(delta=0,expected=0,relation_ok=False); m['kernel_window']['code']='NO_VALID_ATTEMPT'
    m['kernel_window']['snapshots'][2]['field_value']=m['kernel_window']['snapshots'][1]['field_value']

def main():
    cases=[('valid bound negative',noop,'NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION',None),
           ('wrong trace sha',wrong_sha,'INVALID_EVIDENCE_BINDING','trace sha256'),
           ('wire from other capture',other_wire,'INVALID_EVIDENCE_BINDING','manifest unusable'),
           ('holder from other log',other_holder,'INVALID_EVIDENCE_BINDING','manifest unusable'),
           ('tool hash drift',bad_tool,'INVALID_EVIDENCE_BINDING','hash mismatch'),
           ('record slice drift',slice_bad,'INVALID_EVIDENCE_BINDING','manifest unusable'),
           ('B=0',zero_b,'INVALID_EVIDENCE_BINDING','NO_VALID_ATTEMPT')]
    n=0
    for c in cases: n+=chk(*c)
    print('GATE BINDING SELFTEST: %d/%d %s'%(n,len(cases),'PASS' if n==len(cases) else 'FAILED'))
    return 0 if n==len(cases) else 1
if __name__=='__main__': raise SystemExit(main())
