"""CPU preparation/analysis; collect must be single-card task-submit. No golden changes."""
import argparse,hashlib,json,shlex,subprocess,sys
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;B=R/'build/agentic_r6'
sys.path.insert(0,str(R/'tools'));from suite import generate,compare

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def prepare():
 old=json.loads((R/'benchmarks/experiments/agentic/20261017T060621-unaligned-pipeline/validation_manifest.json').read_text());records=[]
 for r in old:
  r=dict(r)
  for n,h in r['hashes'].items():assert sha(Path(r['directory'])/n)==h
  assert sha(r['golden'])==r['golden_sha256'];assert sha(r['parent_output'])==r['parent_output_sha256'];records.append(r)
 new=[]
 for d in range(18,65,2):
  if d%16==0:continue
  for dt in ['float16','float32']:
   i=len(new);hh=[33,63,64,65,127,128,129,255,256][i%9]
   new.append(dict(name=f'ht_d{d}_{dt}_h{hh}',shape=[1,129,hh,d],dtype=dt,seed=62000+i,pmax=1 if i%7==0 else 131073,theta=[1,1.0000001192092896,10000,500000][i%4],zero_every=3,special=True,extreme=True))
 for c in new:
  folder=B/'data'/c['name'];x,p,y=generate(c,folder,c['seed']);y.tofile(folder/'golden.bin')
  records.append(dict(group='headtile_tails',case=c,directory=str(folder),golden=str(folder/'golden.bin'),golden_sha256=sha(folder/'golden.bin'),hashes={n:sha(folder/n) for n in ['x.bin','positions.bin']},parent_output=str(B/'output/parent/headtile_tails'/(c['name']+'.bin'))))
 (H/'validation_manifest.json').write_text(json.dumps(records,indent=2)+'\n')
 for variant in ['parent','candidate']:
  for group in sorted(set(r['group'] for r in records)):
   if variant=='parent' and group!='headtile_tails':continue
   out=B/'output'/variant/group;out.mkdir(parents=True,exist_ok=True);lines=[]
   for r in records:
    if r['group']!=group:continue
    c=r['case'];w,t=(1,2) if group=='headtile_tails' else (0,1)
    lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],'--theta',str(c.get('theta',10000)),'--input',r['directory'],'--output',str(out/(c['name']+'.bin')),'--warmup',str(w),'--repeat',str(t),'--batches','1']))
   (B/f'{variant}_{group}.txt').write_text('\n'.join(lines)+'\n')
 print('Prepared',len(records),'frozen cases;new',len(new))

def collect(v,groups,device):
 binary=R/('build/agentic_r2wide/candidate_audit_runner' if v=='parent' else 'build/agentic_r6/candidate_audit/rope_runner')
 m=json.loads(Path(str(binary)+'.meta.json').read_text());assert sha(binary)==m['binary_sha256']
 for group in groups.split(','):
  p=subprocess.run([str(binary),'--device',str(device),'--batch',str(B/f'{v}_{group}.txt')],capture_output=True,text=True,timeout=48)
  (B/f'{v}_{group}.log').write_text(p.stdout+p.stderr)
  if p.returncode:raise RuntimeError(p.stdout[-2000:]+p.stderr[-2000:])
  print(v,group,'done',flush=True)

def analyze():
 records=json.loads((H/'validation_manifest.json').read_text());out=[];audits=0
 for group in sorted(set(r['group'] for r in records)):
  rs=[r for r in records if r['group']==group];ts=[json.loads(s) for s in (B/f'candidate_{group}.log').read_text().splitlines() if s.startswith('{')];assert len(rs)==len(ts)
  for r,t in zip(rs,ts):
   c=r['case'];dt=c['dtype'];data=Path(r['directory'])
   for n,h in r['hashes'].items():assert sha(data/n)==h
   assert sha(r['golden'])==r['golden_sha256']
   if 'parent_output_sha256' in r:assert sha(r['parent_output'])==r['parent_output_sha256']
   newpath=B/'output/candidate'/group/(c['name']+'.bin');a=np.fromfile(newpath,dt).reshape(c['shape']);p=np.fromfile(r['parent_output'],dt).reshape(c['shape']);g=np.fromfile(r['golden'],dt).reshape(c['shape']);x=np.fromfile(data/'x.bin',dt).reshape(c['shape']);pos=np.fromfile(data/'positions.bin',np.int32).reshape(c['shape'][:2]);bits=np.uint16 if dt=='float16' else np.uint32
   finite=np.isfinite(a)&np.isfinite(p);finediff=int(np.count_nonzero(a.view(bits)[finite]!=p.view(bits)[finite]));allbit=int(np.count_nonzero(a.view(bits)!=p.view(bits)));classes=bool(np.array_equal(np.isnan(a),np.isnan(p)) and np.array_equal(np.isposinf(a),np.isposinf(p)) and np.array_equal(np.isneginf(a),np.isneginf(p)))
   zero=bool(np.array_equal(a[pos==0].view(bits),x[pos==0].view(bits)));cmp=compare(a,g);parent=compare(p,g)
   audit=t.get('launch_audit',False) and t.get('one_kernel_per_iteration',False);assert t['guard_ok'] and audit and zero and classes and finediff==0,(c['name'],finediff,classes,zero,t)
   assert cmp['passed']==parent['passed']
   audits+=t['iterations']
   out.append(dict(group=group,case=c,candidate=cmp,parent=parent,finite_bit_differences=finediff,all_bit_differences=allbit,nonfinite_classes_identical=classes,position0_bits=zero,runtime=t,output_sha256=dict(parent=sha(r['parent_output']),candidate=sha(newpath))))
 report=dict(request_id='20261017-headtile-attribution',source_sha256=sha(H/'kernel.asc'),cases_total=len(out),finite_bits_all_identical=all(r['finite_bit_differences']==0 for r in out),all_bits_identical_count=sum(r['all_bit_differences']==0 for r in out),original_reference_pass=sum(r['candidate']['passed'] for r in out),audited_calls=audits,failures=[r for r in out if not r['candidate']['passed']],cases=out)
 (H/'correctness.json').write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k not in ['cases','failures']})

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','collect','analyze']);ap.add_argument('--variant',default='candidate');ap.add_argument('--groups',default='base');ap.add_argument('--device',type=int,default=0);a=ap.parse_args()
 if a.action=='prepare':prepare()
 elif a.action=='collect':collect(a.variant,a.groups,a.device)
 else:analyze()
