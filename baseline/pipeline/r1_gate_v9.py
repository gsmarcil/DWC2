#!/usr/bin/env python3
"""P4 fail-closed negative gate for DWC2 R1 observer semantic ABI v9.

A negative result is never derived from absence of timeout records alone.
It requires:
  * ABI v9 / atomic snapshot / no lost records / buffer DMA, non-DDMA
  * a mode-specific target-side candidate denominator
  * >= --min-candidates candidate endpoint-stop opportunities
  * matching harness artifacts whose sensitivity.verdict == SENSITIVE
  * no branch-matching timeout record that should be investigated first

Delayed branches additionally require overlap_count == 0 because the known
f_mass_storage early-worker window can otherwise turn a causal dequeue into an
OVERLAP before setup() returns USB_GADGET_DELAYED_STATUS.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from dwc2_r1_v9 import *

MODES={
 'cfg0': ('candidate_cfg0_seen',TRIG_CFG0,'DISABLE',False),
 'cfgn': ('candidate_cfgn_seen',TRIG_CFGN,'DISABLE',False),
 'interface-sync': ('candidate_intf_seen',TRIG_INTF,'DISABLE',False),
 'delayed-disable': ('candidate_delayed_disable_seen',None,'DISABLE',True),
 'delayed-dequeue': ('candidate_delayed_dequeue_seen',None,'DEQUEUE',True),
}

class GateError(Exception): pass

def load_harness(path):
    obj=json.loads(Path(path).read_text())
    try: verdict=obj['sensitivity']['verdict']
    except Exception: raise GateError(f'{path}: missing sensitivity.verdict')
    return verdict,obj

def branch_matches(a, r, mode):
    field,trig,caller,delayed=MODES[mode]
    if a.caller!=caller: return False
    if delayed:
        return r.causal_state==CAUSE_DELAYED
    return r.causal_state==CAUSE_SYNC_OWNER and r.trigger==trig

def outcome(traces, mode, min_candidates, harnesses):
    if not traces: return {'verdict':'INVALID_NO_TRACES'}
    if harnesses and len(harnesses)!=len(traces):
        return {'verdict':'INVALID_HARNESS_TRACE_COUNT_MISMATCH','traces':len(traces),'harnesses':len(harnesses)}

    seen_sha=set(); fp=None; total=0; batches=[]; matching=[]; all_ass=[]
    for i,path in enumerate(traces):
        try: h,recs,sha=parse_file(path)
        except Exception as e: return {'verdict':'INVALID_TRACE_FORMAT','trace':str(path),'error':str(e)}
        if sha in seen_sha: return {'verdict':'INVALID_DUPLICATE_TRACE','sha256':sha}
        seen_sha.add(sha)
        he=header_errors(h,negative_gate=True)
        if he: return {'verdict':'INVALID_HEADER','trace':str(path),'errors':he}
        if h.lost: return {'verdict':'INVALID_LOST_EVENTS','trace':str(path)}
        if not (h.caps_flags&CAP_DMA) or (h.caps_flags&CAP_DDMA):
            return {'verdict':'UNSUPPORTED_DMA_MODE','trace':str(path),'caps_flags':h.caps_flags}
        thisfp=target_fingerprint(h)
        if fp is None: fp=thisfp
        elif thisfp!=fp: return {'verdict':'INVALID_TARGET_FINGERPRINT_MISMATCH','trace':str(path)}

        ass=[assess_record(r,j) for j,r in enumerate(recs)]
        bad=[x for x in ass if x.integrity=='INVALID']
        if bad:
            return {'verdict':'INVALID_INCONSISTENT_RECORD','trace':str(path),
                    'record':bad[0].index,'errors':list(bad[0].errors)}

        denom=getattr(h,MODES[mode][0])
        total+=denom
        delayed=MODES[mode][3]
        if delayed and h.overlap_count:
            return {'verdict':'INVALID_CAUSAL_OVERLAP_FOR_DELAYED_NEGATIVE','trace':str(path),'overlap_count':h.overlap_count}

        # Any matching timeout gets inspected before an absence claim.
        for j,(r,a) in enumerate(zip(recs,ass)):
            if branch_matches(a,r,mode): matching.append((str(path),j,r,a))
        all_ass.extend((str(path),j,r,a) for j,(r,a) in enumerate(zip(recs,ass)))
        batches.append({'trace':str(path),'sha256':sha,'denominator':denom,
                        'count':h.count,'overlap_count':h.overlap_count,
                        'reset_generation':h.reset_generation})

    # Positive sync evidence supersedes P4 negative gating.
    for path,j,r,a in matching:
        if a.r1_state=='R1_PROVEN_SYNC':
            return {'verdict':'R1_PROVEN','trace':path,'record':j,'seq':a.seq,
                    'trigger':a.trigger,'caller':a.caller,'u_state':a.u_state,
                    'bounce_active':a.bounce_active,'candidates':total,'denominator_unit':'endpoint_stop_opportunities','batches':batches}
        if a.r1_state.startswith('R1_DELAYED_'):
            return {'verdict':a.r1_state,'trace':path,'record':j,'seq':a.seq,
                    'u_state':a.u_state,'bounce_active':a.bounce_active,
                    'note':'temporal correlation only; not causal R1 proof',
                    'candidates':total,'denominator_unit':'endpoint_stop_opportunities','batches':batches}
        # Matching natural timeout exists but the frozen post-timeout active predicate failed.
        return {'verdict':'TIMEOUT_OBSERVED_R1_NOT_MET','trace':path,'record':j,
                'state':a.r1_state,'candidates':total,'denominator_unit':'endpoint_stop_opportunities','batches':batches}

    # Overlap/unattributed timeout records do not become a negative result silently.
    ambiguous=[(p,j,a.r1_state) for p,j,r,a in all_ass if a.r1_state in ('TIMEOUT_CAUSAL_OVERLAP','TIMEOUT_UNATTRIBUTED')]
    if ambiguous:
        return {'verdict':'INCONCLUSIVE_AMBIGUOUS_TIMEOUTS_PRESENT','events':ambiguous[:8],
                'candidates':total,'denominator_unit':'endpoint_stop_opportunities','batches':batches}

    if total < min_candidates:
        return {'verdict':'INSUFFICIENT_CANDIDATES','candidates':total,'required':min_candidates,'denominator_unit':'endpoint_stop_opportunities','batches':batches}

    if not harnesses:
        return {'verdict':'PENDING_HARNESS_SENSITIVITY','candidates':total,'required':min_candidates,'denominator_unit':'endpoint_stop_opportunities','batches':batches}
    hv=[]
    for p in harnesses:
        try: v,o=load_harness(p)
        except Exception as e: return {'verdict':'INVALID_HARNESS_ARTIFACT','error':str(e)}
        hv.append({'path':str(p),'verdict':v})
        if v!='SENSITIVE':
            return {'verdict':'PENDING_HARNESS_SENSITIVITY','harness':str(p),'harness_verdict':v,
                    'candidates':total,'denominator_unit':'endpoint_stop_opportunities','batches':batches}

    return {'verdict':'NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION',
            'mode':mode,'candidates':total,'required':min_candidates,
            'denominator_unit':'endpoint_stop_opportunities',
            'host_attempt_budget':'NOT_ESTABLISHED_BY_KERNEL_COUNTERS',
            'interpretation':'NOT_OBSERVED, not R1_DISPROVEN',
            'target_fingerprint':fp,'batches':batches,'harnesses':hv}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--mode',choices=sorted(MODES),required=True)
    ap.add_argument('--min-candidates',type=int,default=500)
    ap.add_argument('--harness',action='append',default=[],help='one JSON per trace; sensitivity.verdict must be SENSITIVE for a negative result')
    ap.add_argument('--json',action='store_true')
    ap.add_argument('trace',nargs='+')
    a=ap.parse_args()
    if a.min_candidates<1: ap.error('--min-candidates must be >=1')
    out=outcome(a.trace,a.mode,a.min_candidates,a.harness)
    print(json.dumps(out,indent=2,sort_keys=True) if a.json else out['verdict'])
    # Positive and valid negative are successful classifications; pending/invalid returns non-zero.
    ok=out['verdict'] in ('R1_PROVEN','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION') or out['verdict'].startswith('R1_DELAYED_')
    return 0 if ok else 1

if __name__=='__main__': raise SystemExit(main())
