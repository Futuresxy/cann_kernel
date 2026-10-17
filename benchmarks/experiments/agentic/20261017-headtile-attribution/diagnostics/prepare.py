import sys,json,hashlib,shlex
from pathlib import Path
R=Path.cwd();H=R/'benchmarks/experiments/agentic/20261017-headtile-attribution';B=R/'build/agentic_r6'
sys.path.insert(0,str(R/'tools'));from suite import generate
p=(B/'parent/kernel.asc').read_text();assert hashlib.sha256(p.encode()).hexdigest()=='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556'
a=p.index('template <typename T> class HeadTileRotary');b=p.index('template <typename T,typename F=Frequencies>',a);s=p[a:b]
def rep(old,new):
 global s
 assert s.count(old)==1,old[:70]
 s=s.replace(old,new)
rep('        x_.SetGlobalBuffer', '        last_ = GetSystemCycle();\n        x_.SetGlobalBuffer')
rep('        auto freq=freq_.Get<float>();','        Mark(0);\n        auto freq=freq_.Get<float>();')
rep('        InitIndexes();','        Mark(1);\n        InitIndexes();\n        Mark(2);')
rep('    __aicore__ inline void InitIndexes() {','    __aicore__ inline void Mark(uint32_t k) {\n        PipeBarrier<PIPE_ALL>();\n        uint64_t now = GetSystemCycle();\n        ticks_[k] += now-last_; last_=now;\n    }\n    __aicore__ inline void InitIndexes() {')
rep('        if(begin==end)return;Prefetch(begin);','        if(begin==end)return;Mark(3);Prefetch(begin);')
rep('        for(uint64_t job=begin;job<end;++job) {','        for(uint64_t job=begin;job<end;++job) {\n            Mark(14); Mark(15);')
rep('            int32_t p=pos_.GetValue(job/groups_);','            int32_t p=pos_.GetValue(job/groups_);\n            Mark(4);')
rep('                PipeBarrier<PIPE_ALL>();in_.FreeTensor(input);continue;','                PipeBarrier<PIPE_ALL>();in_.FreeTensor(input);Mark(16);continue;')
rep('            Gather(z,c,trig,0,pairs);','            Mark(5);\n            Gather(z,c,trig,0,pairs);')
rep('            PipeBarrier<PIPE_V>();LoadFp32(c,input,aligned);','            Mark(6);\n            PipeBarrier<PIPE_V>();LoadFp32(c,input,aligned);')
rep('            Gather(lo,c,index,0,pairs);','            Mark(7);\n            Gather(lo,c,index,0,pairs);')
rep('            Mul(c,lo,z,pairs);','            Mark(8);\n            Mul(c,lo,z,pairs);')
rep('            PipeBarrier<PIPE_V>();Gather(lo,c,packed,0,aligned);','            Mark(9);\n            PipeBarrier<PIPE_V>();Gather(lo,c,packed,0,aligned);')
rep('            PipeBarrier<PIPE_V>();auto output=out_.AllocTensor<T>();StoreFp32(output,lo,aligned);','            Mark(10);\n            PipeBarrier<PIPE_V>();auto output=out_.AllocTensor<T>();StoreFp32(output,lo,aligned);\n            Mark(11);')
rep('            in_.FreeTensor(input);out_.FreeTensor(output);','            in_.FreeTensor(input);out_.FreeTensor(output);\n            Mark(12);')
rep('        PipeBarrier<PIPE_ALL>();\n    }\nprivate:', '''        Mark(13);
        GlobalTensor<uint64_t> trace;
        trace.SetGlobalBuffer((__gm__ uint64_t*)y_.GetPhyAddr());
        uint64_t traceOffset=(Offset(begin)*sizeof(T)+7)/8;
        for(uint32_t k=0;k<17;++k)trace.SetValue(traceOffset+k,ticks_[k]);
        trace.SetValue(traceOffset+17,end-begin);
        trace.SetValue(traceOffset+18,GetBlockIdx());
        trace.SetValue(traceOffset+19,0x444941474f4e4c59ULL);
        PipeBarrier<PIPE_ALL>();
    }
private:
    uint64_t ticks_[17]={};uint64_t last_;''')
s='// DIAGNOSTIC ONLY: timestamps serialize stages and overwrite own first output job. Never submit.\n'+p[:a]+s+p[b:]
(B/'diagnostic/kernel.asc').write_text(s);(H/'diagnostics/instrumented.asc').write_text(s)
cases=json.loads((R/'tests/round7_performance_cases.json').read_text());target=[c for c in cases if c['name'].startswith('unaligned_h128_d30')];assert len(target)==2
for d,h in [(18,129),(62,65)]:
 for dt in ['float16','float32']:
  target.append(dict(name=f'attr_d{d}_h{h}_{dt}',shape=[1,257,h,d],dtype=dt,pmax=131073,seed=61000+len(target)))
records=[];lines=[]
for c in target:
 data=R/'build/data'/c['name']
 if not (data/'x.bin').exists():
  x,p,y=generate(c,data,c['seed']);y.tofile(data/'golden.bin')
 records.append(dict(case=c,hashes={n:hashlib.sha256((data/n).read_bytes()).hexdigest() for n in ['x.bin','positions.bin']}))
 lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],'--theta','10000','--input',str(data),'--output',str(B/(c['name']+'_trace.bin')),'--repeat','1','--warmup','1','--batches','1']))
(B/'diagnostic.txt').write_text('\n'.join(lines)+'\n');(H/'diagnostics/cases.json').write_text(json.dumps(target,indent=2)+'\n');(H/'diagnostics/input_manifest.json').write_text(json.dumps(records,indent=2)+'\n')
protected=['AGENTIC.md','kernel_requirement.md','forbidden.md','operators/rotary_pos_emb/kernel.asc','submissions/rotary_pos_emb/latest.json','tools/suite.py', 'platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc']
(H/'protected_hashes.json').write_text(json.dumps({f:hashlib.sha256((R/f).read_bytes()).hexdigest() for f in protected},indent=2)+'\n')
print('Prepared diagnostic clone and',len(target),'frozen cases')
