#!/usr/bin/env python3
"""P4 v9.1 evidence-binding gate.

The frozen v9 classifier remains byte-for-byte separate. v9.1 closes evidence
correlation: it validates the manifest, re-derives usbmon/holder witnesses from
the raw artifacts, binds S2 by sha256, restricts record classification to the
S1..S2 campaign slice, and uses the measured campaign counter delta rather than
the cumulative final header as the negative denominator.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import r1_gate_v9 as v9
import dwc2_r1_v9 as _r1_parser
import r1a_manifest as _manifest
import usbmon_verify as _usbmon
import holder_merge as _holder
import r1_verdict as _verdict
from dwc2_r1_v9 import *

validate = _manifest.validate
verify_wire = _usbmon.verify
merge_holder = _holder.merge

OK_POS=('R1_PROVEN',)
class GateError(Exception): pass

def sha256_file(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def resolve_art(manifest_path, item):
    p=Path(item['path'])
    return p if p.is_absolute() else Path(manifest_path).resolve().parent/p

def runtime_epoch_local_files():
    """Return the exact local Python files loaded by this evidence path.

    These paths come from module.__file__, not from a second filename table.
    The verdict generator is imported here deliberately so its epoch hash also
    names the exact module Python resolved beside this gate.
    """
    return {
        'dwc2_r1_v9': Path(_r1_parser.__file__).resolve(),
        'r1_gate_v9': Path(v9.__file__).resolve(),
        'r1_gate_v9_1': Path(__file__).resolve(),
        'manifest_validator': Path(_manifest.__file__).resolve(),
        'usbmon_verifier': Path(_usbmon.__file__).resolve(),
        'holder_merger': Path(_holder.__file__).resolve(),
        'verdict_generator': Path(_verdict.__file__).resolve(),
    }


def compare_tool_hashes(m):
    arts=m['epoch']['artifacts']
    bad=[]
    for k,p in sorted(runtime_epoch_local_files().items()):
        if not p.is_file():
            bad.append('%s missing (%s)'%(k,p)); continue
        got=sha256_file(p)
        if got!=arts.get(k):
            bad.append('%s hash mismatch epoch=%s actual=%s'%(k,arts.get(k),got))
    return bad

def load_bound(manifest_path, trace_path, mode):
    mp=Path(manifest_path)
    try: m=json.loads(mp.read_text())
    except Exception as e: raise GateError('manifest unreadable: %s'%e)
    errs=validate(m)
    if errs: raise GateError('manifest unusable: '+'; '.join(errs[:8]))
    if m['session']['mode']!=mode: raise GateError('manifest mode %s != gate mode %s'%(m['session']['mode'],mode))
    bad=compare_tool_hashes(m)
    if bad: raise GateError('; '.join(bad))
    trace_sha=sha256_file(trace_path)
    if trace_sha!=m['artifacts']['dump']['sha256']:
        raise GateError('trace sha256 does not match manifest dump')
    # Re-derive the two witnesses from their raw artifacts, not from the merged claims.
    usb=resolve_art(mp,m['artifacts']['usbmon'])
    wire,werrs=verify_wire(m,usb)
    if werrs: raise GateError('usbmon witness input: '+'; '.join(werrs))
    if wire!=m.get('wire'): raise GateError('wire witness in manifest does not equal re-derivation from raw capture')
    hev=resolve_art(mp,m['artifacts']['holder_event_log'])
    hold,hsha=merge_holder(m,hev,m['holder']['floor'])
    if hsha!=m['artifacts']['holder_event_log']['sha256']:
        raise GateError('holder event-log hash mismatch')
    if hold!=m.get('holder'): raise GateError('holder witness in manifest does not equal re-derivation from raw event log')
    h,recs,sha=parse_file(trace_path)
    he=header_errors(h,negative_gate=True)
    if he: raise GateError('invalid header: '+','.join(he))
    if sha!=trace_sha: raise GateError('parser sha mismatch')
    s1,s2=m['kernel_window']['snapshots'][1:3]
    start,end=m['kernel_window']['record_slice']['start'],m['kernel_window']['record_slice']['end']
    if start!=s1['count'] or end!=s2['count'] or end!=h.count:
        raise GateError('record slice does not bind S1.count..S2.count..trace.count')
    if not (0<=start<=end<=len(recs)): raise GateError('record slice out of bounds')
    return m,h,recs,start,end,trace_sha,sha256_file(mp)

def classify_records(recs,mode):
    out=[]
    for j,r in enumerate(recs): out.append((j,r,assess_record(r,j)))
    bad=[x for x in out if x[2].integrity=='INVALID']
    if bad: return {'verdict':'INVALID_INCONSISTENT_RECORD','record':bad[0][0],'errors':list(bad[0][2].errors)}
    matching=[x for x in out if v9.branch_matches(x[2],x[1],mode)]
    for j,r,a in matching:
        if a.r1_state=='R1_PROVEN_SYNC':
            return {'verdict':'R1_PROVEN','record':j,'seq':a.seq,'trigger':a.trigger,'caller':a.caller,'u_state':a.u_state,'bounce_active':a.bounce_active}
        if a.r1_state.startswith('R1_DELAYED_'):
            return {'verdict':a.r1_state,'record':j,'seq':a.seq,'u_state':a.u_state,'bounce_active':a.bounce_active,'note':'temporal correlation only; not causal R1 proof'}
        return {'verdict':'TIMEOUT_OBSERVED_R1_NOT_MET','record':j,'state':a.r1_state}
    amb=[(j,a.r1_state) for j,r,a in out if a.r1_state in ('TIMEOUT_CAUSAL_OVERLAP','TIMEOUT_UNATTRIBUTED')]
    if amb: return {'verdict':'INCONCLUSIVE_AMBIGUOUS_TIMEOUTS_PRESENT','events':amb[:8]}
    return None

def outcome(traces,manifests,mode,min_candidates):
    if not traces or len(traces)!=len(manifests): return {'verdict':'INVALID_MANIFEST_TRACE_COUNT_MISMATCH'}
    seen=set(); fp=None; total=0; host_total=0; batches=[]
    for tp,mp in zip(traces,manifests):
        try: m,h,recs,start,end,tsha,msha=load_bound(mp,tp,mode)
        except Exception as e: return {'verdict':'INVALID_EVIDENCE_BINDING','trace':str(tp),'manifest':str(mp),'error':str(e)}
        if tsha in seen: return {'verdict':'INVALID_DUPLICATE_TRACE','sha256':tsha}
        seen.add(tsha)
        thisfp=target_fingerprint(h)
        if fp is None: fp=thisfp
        elif fp!=thisfp: return {'verdict':'INVALID_TARGET_FINGERPRINT_MISMATCH'}
        # A timeout in preflight is not silently ignored to make a negative campaign.
        pre=classify_records(recs[:start],mode)
        if pre is not None:
            return {'verdict':'PRECAMPAIGN_TIMEOUT_PRESENT','classification':pre,
                    'trace':str(tp),'manifest_sha256':msha,'trace_sha256':tsha}
        camp=classify_records(recs[start:end],mode)
        if camp is not None:
            camp.update({'mode':mode,'trace':str(tp),'manifest':str(mp),'manifest_sha256':msha,
                         'trace_sha256':tsha,'record_slice':[start,end]})
            return camp
        d=m['kernel_window']['campaign']['delta']; b=m['denominator']['B_valid']
        total+=d; host_total+=b
        batches.append({'trace':str(tp),'trace_sha256':tsha,'manifest':str(mp),
                        'manifest_sha256':msha,'denominator':d,'host_attempts':b,
                        'record_slice':[start,end],'reset_generation':h.reset_generation})
    if total<min_candidates:
        return {'verdict':'INSUFFICIENT_CANDIDATES','candidates':total,'required':min_candidates,
                'host_attempts':host_total,'batches':batches}
    return {'verdict':'NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION','mode':mode,
            'candidates':total,'required':min_candidates,'denominator_unit':'endpoint_stop_opportunities',
            'host_attempts':host_total,'host_attempt_budget':host_total,
            'interpretation':'NOT_OBSERVED, not R1_DISPROVEN','target_fingerprint':fp,'batches':batches}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--mode',choices=sorted(v9.MODES),required=True)
    ap.add_argument('--min-candidates',type=int,default=500); ap.add_argument('--manifest',action='append',default=[],required=True)
    ap.add_argument('--json',action='store_true'); ap.add_argument('trace',nargs='+'); a=ap.parse_args()
    if a.min_candidates<1: ap.error('--min-candidates must be >=1')
    o=outcome(a.trace,a.manifest,a.mode,a.min_candidates)
    print(json.dumps(o,indent=2,sort_keys=True) if a.json else o['verdict'])
    ok=o['verdict'] in ('R1_PROVEN','NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION') or o['verdict'].startswith('R1_DELAYED_')
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(main())
