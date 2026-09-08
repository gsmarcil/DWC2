#!/usr/bin/env python3
import copy, hashlib, importlib.util, json, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
GEN=HERE/'r1_verdict.py'
sys.path.insert(0,str(HERE))
from fixtures import manifest, sha

def fsha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def prepare(td,mans,kind='neg'):
    td=Path(td); paths=[]; batches=[]
    for i,m in enumerate(mans):
        p=td/f'm{i}.json'; p.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n'); paths.append(p)
        batches.append({'manifest_sha256':fsha(p),'trace_sha256':m['artifacts']['dump']['sha256'],
                        'host_attempts':m['denominator']['B_valid'],
                        'denominator':m['kernel_window']['campaign']['delta']})
    if kind=='neg':
        g={'verdict':'NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION','mode':mans[0]['session']['mode'],
           'candidates':sum(b['denominator'] for b in batches),'host_attempts':sum(b['host_attempts'] for b in batches),
           'denominator_unit':'endpoint_stop_opportunities','batches':batches}
    else:
        g={'verdict':'R1_PROVEN','mode':mans[0]['session']['mode'],'candidates':1,
           'manifest_sha256':batches[0]['manifest_sha256'],'trace_sha256':batches[0]['trace_sha256']}
    return paths,g

def run(mans,mut_gate=None,kind='neg'):
    with tempfile.TemporaryDirectory() as td:
        paths,g=prepare(td,mans,kind)
        if mut_gate: mut_gate(g)
        gp=Path(td)/'g.json'; gp.write_text(json.dumps(g))
        cmd=[sys.executable,str(GEN),'--gate',str(gp)]
        for p in paths: cmd += ['--manifest',str(p)]
        r=subprocess.run(cmd,capture_output=True,text=True)
        return r.returncode,r.stdout+r.stderr

def good(): return manifest('s001',sha('dump'),2,k=2,sens=20,mode='cfg0')
CASES=[]
def case(name,mans,want,expect,mut=None,kind='neg'): CASES.append((name,mans,want,expect,mut,kind))
case('valid negative',[good()],0,'NOT_OBSERVED')
case('valid positive',[good()],0,'R1 is established',kind='pos')
case('wrong batch manifest hash',[good()],1,'manifest_sha256',lambda g:g['batches'][0].update(manifest_sha256='0'*64))
case('wrong batch trace hash',[good()],1,'trace sha',lambda g:g['batches'][0].update(trace_sha256='1'*64))
case('wrong host attempt total',[good()],1,'host_attempts',lambda g:g.update(host_attempts=99))
case('wrong batch host attempts',[good()],1,'host_attempts',lambda g:g['batches'][0].update(host_attempts=99))
case('wrong candidate delta',[good()],1,'denominator',lambda g:g['batches'][0].update(denominator=99))
case('different gate mode',[good()],1,'but the manifests are mode',lambda g:g.update(mode='cfgn'))
ma=good(); mb=good(); mb['epoch']['epoch_id']='other'
case('two epochs',[ma,mb],1,'different epochs')
ma=good(); mb=good(); mb['session']['mode']='cfgn'; mb['kernel_window']['field']='candidate_cfgn_seen'; mb['kernel_window']['snapshots'][0]['setup_field']='setup_cfgn_seen'; mb['kernel_window']['snapshots'][1]['setup_field']='setup_cfgn_seen'; mb['kernel_window']['snapshots'][2]['setup_field']='setup_cfgn_seen'
case('two modes',[ma,mb],1,'one verdict covers one')
case('unknown verdict',[good()],1,'no frozen phrasing',lambda g:g.update(verdict='PROBABLY_FINE'))
case('gate missing batches',[good()],1,'one batch',lambda g:g.pop('batches'))
case('positive wrong manifest binding',[good()],1,'not bound',lambda g:g.update(manifest_sha256='2'*64),kind='pos')
case('positive wrong trace binding',[good()],1,'trace sha',lambda g:g.update(trace_sha256='3'*64),kind='pos')
# manifest-side failures
d=good(); d['preflight']['caps']['g_dma_desc']=1
case('invalid manifest DDMA',[d],1,'not usable')
d=good(); d['holder']['event_log_sha256']='4'*64
case('invalid holder provenance',[d],1,'not usable')
d=good(); d['wire']['extra_controls']=1
case('extra wire traffic',[d],1,'not usable')
d=good(); d['kernel_window']['record_slice']['start']=1
case('bad record slice',[d],1,'not usable')

def main():
    fails=0
    for name,mans,want,expect,mut,kind in CASES:
        rc,out=run(copy.deepcopy(mans),mut,kind)
        ok=rc==want and expect in out
        print(('ok  ' if ok else 'FAIL'),'%-42s'%name,'rc=%d'%rc)
        if not ok:
            fails+=1; print(' ',out[:500].replace('\n',' | '))
    # Import must not execute argparse/main.
    r=subprocess.run([sys.executable,'-c',f"import importlib.util; s=importlib.util.spec_from_file_location('v',r'{GEN}'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('IMPORT_OK')"],capture_output=True,text=True)
    ok=r.returncode==0 and 'IMPORT_OK' in r.stdout
    print(('ok  ' if ok else 'FAIL'),'%-42s'%'safe import','rc=%d'%r.returncode)
    fails += 0 if ok else 1
    total=len(CASES)+1
    print('VERDICT SELFTEST: %d/%d %s'%(total-fails,total,'PASS' if not fails else 'FAILED'))
    return 1 if fails else 0
if __name__=='__main__': raise SystemExit(main())
