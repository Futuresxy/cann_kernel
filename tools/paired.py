#!/usr/bin/env python3
"""Same-card alternating baseline/candidate measurements, without profiler replay."""
import argparse,hashlib,json,pathlib,statistics,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--device',type=int,default=0)
    ap.add_argument('--baseline',default='build/rope_runner_baseline')
    ap.add_argument('--candidate',default='build/rope_runner_v4');args=ap.parse_args()
    cases={c['name']:c for c in json.loads((ROOT/'tests/cases.json').read_text())}
    results=[];start=time.time()
    for name in ['deepseek_half','deepseek_float','sequence8192','large_half']:
        c=cases[name];dest=ROOT/'build/data'/name;timings={'baseline':[],'candidate':[]}
        for variant in ['baseline','candidate','candidate','baseline']:
            binary=ROOT/getattr(args,variant)
            cmd=[str(binary),'--device',str(args.device),'--shape',*map(str,c['shape']),
                 '--dtype',c['dtype'],'--input',str(dest),'--output',str(ROOT/'build/paired_output.bin'),
                 '--warmup','10','--repeat','100','--batches','5']
            proc=subprocess.run(cmd,text=True,capture_output=True,timeout=15,check=True)
            timings[variant].append(json.loads(proc.stdout.splitlines()[-1]))
        base=statistics.median(t['event_us'] for t in timings['baseline'])
        cand=statistics.median(t['event_us'] for t in timings['candidate'])
        result=dict(case=c,device=args.device,baseline_us=base,candidate_us=cand,speedup=base/cand,samples=timings)
        results.append(result);print(json.dumps(result),flush=True)
    hashes={k:hashlib.sha256((ROOT/getattr(args,k)).read_bytes()).hexdigest() for k in ['baseline','candidate']}
    (ROOT/'benchmarks/results/paired_final.json').write_text(json.dumps(dict(seconds=time.time()-start,binary_sha256=hashes,cases=results),indent=2)+'\n')
if __name__=='__main__':main()
