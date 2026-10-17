"""DIAGNOSTIC ONLY: one bounded scalar log/remaining-loop control, not a candidate."""
import hashlib,json,re,shlex
from pathlib import Path
H=Path(__file__).resolve().parent;R=H.parents[4];B=R/'build/agentic_r7_frequency_scalar';B.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def span(s,key):
 a=s.index(key);b=s.index('{',a);e=b+1;d=1
 while d:d+=(s[e]=='{')-(s[e]=='}');e+=1
 return a,b,e
s=(H/'instrumented.asc').read_text();parent=(R/'platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc').read_text();a,b,e=span(parent,'__aicore__ inline void ScalarFrequencies(');cl=parent[a:e]
cl=cl.replace('ScalarFrequencies(','ScalarFrequenciesDiag(',1).replace('const LocalTensor<float>& scratch) {','const LocalTensor<float>& scratch,FrequencyTrace& trace) {',1)
cl=cl.replace('    int64_t log=DeviceLog2Q53(theta),log31=log/int64_t(4194304LL);','''    // Read-write input operand is opaque to compiler but unchanged by this MOV.
    // It forces theta use after the first timestamp; end consumes both log results.
    PipeBarrier<PIPE_ALL>();FloatBits diagBits;diagBits.value=theta;
    uint64_t diagTheta=diagBits.bits,diagLogStart=0;
    asm volatile("MOV %0, SYS_CNT\\n" : "+l"(diagLogStart), "+l"(diagTheta) : : "memory");
    diagBits.bits=uint32_t(diagTheta);
    int64_t log=DeviceLog2Q53(diagBits.value),log31=log/int64_t(4194304LL);
    uint64_t diagLogEnd=0;
    asm volatile("MOV %0, SYS_CNT\\n" : "+l"(diagLogEnd) : "l"(uint64_t(log)), "l"(uint64_t(log31)) : "memory");
    trace.ticks[2]+=diagLogEnd-diagLogStart;trace.calls[2]++;trace.elements[2]++;
    uint64_t diagLog=uint64_t(log),diagLog31=uint64_t(log31),diagLoopStart=0;
    asm volatile("MOV %0, SYS_CNT\\n" : "+l"(diagLoopStart), "+l"(diagLog), "+l"(diagLog31) : : "memory");
    log=int64_t(diagLog);log31=int64_t(diagLog31);''',1)
cl=cl.replace('            if(!TryExp2PowerQ31(log31,numerator,denominatorLog,pm,e)) {','            if(!TryExp2PowerQ31(log31,numerator,denominatorLog,pm,e)) {\n            ++trace.meta[5];',1)
cl=cl.replace('if((ki&31)!=0 && !rootsReady){BuildExp2Roots(table);rootsReady=true;}','if((ki&31)!=0 && !rootsReady){BuildExp2Roots(table);rootsReady=true;++trace.meta[6];}',1)
cl=cl.replace('if(powerKey==previousPower)result=previousResult;','if(powerKey==previousPower){result=previousResult;++trace.meta[8];}',1)
cl=cl.replace('    PipeBarrier<PIPE_ALL>();\n}','''    PipeBarrier<PIPE_ALL>();
    uint64_t diagLoopEnd=0;
    asm volatile("MOV %0, SYS_CNT\\n" : "+l"(diagLoopEnd) : : "memory");
    trace.ticks[3]+=diagLoopEnd-diagLoopStart;trace.calls[3]++;trace.elements[3]+=width;
    trace.meta[7]=width-1;
}''',1)
a,b,e=span(s,'__aicore__ inline void ScalarFrequenciesDiag(');s=s[:a]+cl+s[e:]
D=H/'scalar_control';D.mkdir(exist_ok=True);(D/'instrumented.asc').write_text(s);(D/'diagnostic_runner.asc').write_text((H/'diagnostic_runner.asc').read_text());cm=(H/'CMakeLists.txt').read_text().replace('../../../../../tests','../../../../../../tests').replace('../../../../../templates','../../../../../../templates');(D/'CMakeLists.txt').write_text(cm)
records=json.loads((H.parent/'input_manifest.json').read_text());records=[r for r in records if r['case']['name'] in ['tiny','deepseek_half']];out=B/'output';out.mkdir(exist_ok=True);lines=[]
for r in records:
 c=r['case'];lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],'--theta',str(c.get('theta',10000)),'--input',r['directory'],'--output',str(out/(c['name']+'.bin')),'--warmup','1','--repeat','1','--batches','1']))
(B/'cases.txt').write_text('\n'.join(lines)+'\n')
m=dict(diagnostic_only=True,source_sha256=sha(D/'instrumented.asc'),runner_sha256=sha(D/'diagnostic_runner.asc'),original_parent_sha256=hashlib.sha256(parent.encode()).hexdigest(),cases=[r['case']['name'] for r in records],new_NPU_task_cap=1,phase2='anchored DeviceLog2Q53 + log31 division',phase3='remaining complete scalar loop incl setup/Q31/fallback/reciprocal/UB stores/drain',compiler_dependency='First SYS_CNT has opaque read-write theta operand, last SYS_CNT consumes both results; surrounding memory clobbers. Outputs remain unchanged in machine MOV.',limitation='No decoded ISA; output identity verifies preservation, but exact emitted scheduling/individual integer instruction costs remain unavailable. Register anchoring changes allocation; no native speedup or complete original fraction.')
(D/'metadata_prebuild.json').write_text(json.dumps(m,indent=2)+'\n');print(m['source_sha256'])
