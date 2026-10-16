#!/usr/bin/env python3
import argparse,csv,hashlib,json,pathlib,shlex,shutil,statistics,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
def analyze(label):
    dest=ROOT/'benchmarks/profiles'/label;dest.mkdir(parents=True,exist_ok=True)
    folders=sorted((ROOT/'build/profiles'/label).glob('OPPROF_*'))
    if not folders:raise RuntimeError('No operator profiling results found')
    for p in folders[-1].glob('*.csv'):shutil.copy2(p,dest/p.name)
    summary={}
    for p in dest.glob('*.csv'):
        rows=list(csv.DictReader(p.open()))
        if not rows:continue
        values={}
        for k in rows[0]:
            if not k:continue
            try:values[k]=statistics.mean(float(r[k]) for r in rows)
            except (ValueError,TypeError):pass
        summary[p.stem]=values
    (dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    pipe=summary.get('PipeUtilization',{})
    print(json.dumps(dict(label=label,task_us=summary.get('OpBasicInfo',{}).get('Task Duration(us)'),
        vec_ratio=pipe.get('aiv_vec_ratio'),mte2_active_gbs=pipe.get('aiv_mte2_active_bw(GB/s)'),
        mte3_active_gbs=pipe.get('aiv_mte3_active_bw(GB/s)')),indent=2))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--label',required=True);ap.add_argument('--case',default='deepseek_half')
    ap.add_argument('--device',type=int,default=0);ap.add_argument('--binary',default='build/rope_runner')
    ap.add_argument('--cases-file',default='tests/cases.json')
    ap.add_argument('--metrics',default='PipeUtilization,Memory,MemoryUB')
    ap.add_argument('--analyze-only',action='store_true');args=ap.parse_args()
    if not args.analyze_only:
        c=next(c for c in json.loads((ROOT/args.cases_file).read_text()) if c['name']==args.case)
        dest=ROOT/'build/data'/c['name']
        if not (dest/'x.bin').exists():raise RuntimeError('Run suite.py --generate-only first')
        app=[str(ROOT/args.binary),'--device',str(args.device),'--shape',*map(str,c['shape']),
             '--dtype',c['dtype'],'--theta',str(c.get('theta',10000)),'--input',str(dest),
             '--output',str(ROOT/'build/profile_output.bin'),'--warmup','6','--repeat','2','--batches','1']
        cmd=['msprof','op','--aic-metrics='+args.metrics,'--launch-count=1',
             '--launch-skip-before-match=5','--warm-up=2','--output='+str(ROOT/'build/profiles'/args.label),
             '--application='+shlex.join(app)]
        subprocess.run(cmd,check=True,timeout=65)
        path=ROOT/'benchmarks/profiles'/args.label;path.mkdir(parents=True,exist_ok=True)
        (path/'metadata.json').write_text(json.dumps(dict(case=c,command=cmd,
            source_sha256=json.loads(pathlib.Path(str(ROOT/args.binary)+'.meta.json').read_text())['source_sha256'],
            binary_sha256=hashlib.sha256((ROOT/args.binary).read_bytes()).hexdigest()),indent=2)+'\n')
    analyze(args.label)
if __name__=='__main__':main()
