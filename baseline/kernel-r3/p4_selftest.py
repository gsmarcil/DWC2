#!/usr/bin/env python3
import json, tempfile
from pathlib import Path
from dwc2_r1_v9 import *
from r1_gate_v9 import outcome

# Exact v9 packers for synthetic tests.
def mkrec(*,trig=TRIG_CFG0,cause=CAUSE_SYNC_OWNER,caller='DISABLE',seq=7,
          req=True,hw=True,epena=True,xfc=False,status=EINPROGRESS,dma_en=True,bulk=True,
          mapping=MAP_LINEAR,f2=None,length=4096,ns=0,nms=0,cookie=3,
          bm=None,breq=None,wv=None,wi=0,wl=0,diag=0):
    if trig==TRIG_CFG0: bm=0 if bm is None else bm; breq=0x09 if breq is None else breq; wv=0 if wv is None else wv
    elif trig==TRIG_CFGN: bm=0 if bm is None else bm; breq=0x09 if breq is None else breq; wv=1 if wv is None else wv
    elif trig==TRIG_INTF: bm=1 if bm is None else bm; breq=0x0b if breq is None else breq; wv=0 if wv is None else wv
    else: bm=0 if bm is None else bm; breq=0 if breq is None else breq; wv=0 if wv is None else wv; wi=0; wl=0
    doepctl=(EPENA if epena else 0)|(EPTYPE_BULK if bulk else (3<<18))
    doepint=XFC if xfc else 0; gahb=GAHBCFG_DMA_EN if dma_en else 0
    gint=dctl=grst=0
    flags=0
    if req: flags|=F_REQ
    if hw: flags|=F_HW
    if epena: flags|=F_EPENA
    if not xfc: flags|=F_NO_XFC
    if status==EINPROGRESS: flags|=F_EIP
    flags|=F_DISABLE if caller=='DISABLE' else F_DEQUEUE
    if length: flags|=F_NONZERO
    if dma_en: flags|=F_DMA_EN
    if bulk: flags|=F_BULK
    if f2 is None:
        if mapping==MAP_LINEAR: f2=F2_DMA_MAPPED|F2_CORE_OWNED|F2_U_ELIG_LINEAR
        elif mapping==MAP_SG: f2=F2_CORE_OWNED|F2_U_ELIG_SG
        elif mapping==MAP_NOT_CORE: f2=F2_SG_WAS_MAPPED
        else: f2=0
    if mapping==MAP_SG and nms==0: ns,nms=2,2
    return Record(seq,EV_TIMEOUT,flags,wv,wi,wl,bm,breq,trig,2,cause,mapping,gint,dctl,doepctl,doepint,grst,gahb,status&0xffffffff,cookie,0x12345000,length,0,ns,nms,f2,1)

def blob(*,recs=(),caps=CAP_DMA,lost=0,snap=1,cfg0=0,cfgn=0,intf=0,dd=0,dq=0,over=0,version=VERSION,target=1,reset=1):
    vals=[MAGIC,version,HDR.size,REC.size,len(recs),lost,100,caps,0x4f54280a,target,2,3,reset,
          cfg0,cfgn,intf,cfg0,cfgn,intf,dd,over,0,0,0,0,snap,dq,0]
    return HDR.pack(*vals)+b''.join(REC.pack(*[getattr(r,n) for n in REC_NAMES]) for r in recs)

def write(d,name,data): p=Path(d)/name; p.write_bytes(data); return str(p)
def harness(d,name,v='SENSITIVE'): p=Path(d)/name; p.write_text(json.dumps({'sensitivity':{'verdict':v}})); return str(p)

def run():
    tests=[]
    with tempfile.TemporaryDirectory() as d:
        s=harness(d,'h.json')
        def gate(name,exp,**kw):
            tr=kw.pop('traces',None)
            if tr is None: tr=[write(d,name+'.bin',kw.pop('data',blob(cfg0=500)))]
            hs=kw.pop('harnesses',[s])
            got=outcome(tr,kw.pop('mode','cfg0'),kw.pop('min_candidates',500),hs)['verdict']
            tests.append((name,got,exp,got==exp))
        gate('valid_negative','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION')
        gate('no_harness','PENDING_HARNESS_SENSITIVITY',harnesses=[])
        gate('weak_harness','PENDING_HARNESS_SENSITIVITY',harnesses=[harness(d,'w.json','WEAK_DEPTH_BELOW_TARGET')])
        gate('too_few','INSUFFICIENT_CANDIDATES',data=blob(cfg0=499))
        gate('lost','INVALID_LOST_EVENTS',data=blob(cfg0=500,lost=1))
        gate('nonatomic','INVALID_HEADER',data=blob(cfg0=500,snap=0))
        gate('ddma','UNSUPPORTED_DMA_MODE',data=blob(cfg0=500,caps=CAP_DMA|CAP_DDMA))
        gate('no_dma','UNSUPPORTED_DMA_MODE',data=blob(cfg0=500,caps=0))
        gate('positive','R1_PROVEN',data=blob(cfg0=1,recs=[mkrec()]))
        gate('positive_no_harness','R1_PROVEN',data=blob(cfg0=1,recs=[mkrec()]),harnesses=[])
        gate('post_state_fail','TIMEOUT_OBSERVED_R1_NOT_MET',data=blob(cfg0=500,recs=[mkrec(xfc=True)]))
        gate('raw_setup_bad','INVALID_INCONSISTENT_RECORD',data=blob(cfg0=500,recs=[mkrec(breq=0x0b)]))
        gate('delayed_corr','R1_DELAYED_DEQUEUE_CORRELATED',mode='delayed-dequeue',data=blob(dq=1,recs=[mkrec(trig=TRIG_INTF,cause=CAUSE_DELAYED,caller='DEQUEUE')]))
        gate('delayed_negative','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION',mode='delayed-dequeue',data=blob(dq=500))
        gate('delayed_overlap','INVALID_CAUSAL_OVERLAP_FOR_DELAYED_NEGATIVE',mode='delayed-dequeue',data=blob(dq=500,over=1))
        gate('delayed_disable_not_combined','INSUFFICIENT_CANDIDATES',mode='delayed-dequeue',data=blob(dd=500,dq=0))
        gate('interface_sync_negative','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION',mode='interface-sync',data=blob(intf=500))
        gate('cfgn_negative','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION',mode='cfgn',data=blob(cfgn=500))
        # Duplicate trace detection
        p=write(d,'dup.bin',blob(cfg0=250)); gate('duplicate','INVALID_DUPLICATE_TRACE',traces=[p,p],harnesses=[s,s])
        # Target mismatch
        p1=write(d,'t1.bin',blob(cfg0=250,target=1)); p2=write(d,'t2.bin',blob(cfg0=250,target=9)); gate('target_mismatch','INVALID_TARGET_FINGERPRINT_MISMATCH',traces=[p1,p2],harnesses=[s,s])
        # Multi-batch accumulation
        p1=write(d,'a.bin',blob(cfg0=250,target=4,reset=1)); p2=write(d,'b.bin',blob(cfg0=250,target=4,reset=2)); gate('aggregate500','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION',traces=[p1,p2],harnesses=[s,s])
        # SG positive annotation remains R1 positive; integrity catches bad provenance.
        gate('sg_positive','R1_PROVEN',data=blob(cfg0=1,recs=[mkrec(mapping=MAP_SG)]))
        badsg=mkrec(mapping=MAP_SG,f2=F2_CORE_OWNED|F2_U_ELIG_SG|F2_DMA_MAPPED)
        gate('sg_bad_bits','INVALID_INCONSISTENT_RECORD',data=blob(cfg0=1,recs=[badsg]))
        ovsg=mkrec(mapping=MAP_SG,f2=F2_CORE_OWNED|F2_U_ELIG_SG|F2_SG_COUNT_OVERFLOW,ns=0,nms=0)
        gate('sg_overflow_positive','R1_PROVEN',data=blob(cfg0=1,recs=[ovsg]))
        gate('not_core_positive','R1_PROVEN',data=blob(cfg0=1,recs=[mkrec(mapping=MAP_NOT_CORE)]))
        # v8 is rejected by semantic gate.
        p=write(d,'v8.bin',blob(cfg0=500,version=8)); got=outcome([p],'cfg0',500,[s])['verdict']; tests.append(('v8_reject',got,'INVALID_TRACE_FORMAT',got=='INVALID_TRACE_FORMAT'))

    bad=0
    for n,g,e,ok in tests:
        print(f'{n}: {g} expected={e} {"PASS" if ok else "FAIL"}')
        bad += 0 if ok else 1
    print(f'P4 SELFTEST: {len(tests)-bad}/{len(tests)} PASS')
    return bad

if __name__=='__main__': raise SystemExit(1 if run() else 0)
