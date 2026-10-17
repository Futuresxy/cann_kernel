"""Generate diagnostic-only clones. No performance candidate, reference or production writes."""
import datetime,hashlib,json,re,shlex
from pathlib import Path
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;B=R/'build/agentic_r7';B.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
parent=R/'platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc';latest=R/'platform_trials/rotary_pos_emb/20261017-user-platform-headtile-period/kernel.asc';p=parent.read_text();q=latest.read_text();assert sha(parent)=='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556';assert sha(latest)=='8d91182ab86ed3937f8127f3d427bb0777bbf94cffff83977b1bab580428eaea'

def span(s,key):
 a=s.index(key);b=s.index('{',a);depth=1;e=b+1
 while depth:
  depth+=(s[e]=='{')-(s[e]=='}');e+=1
 return a,b,e

def body(s,key):
 a,b,e=span(s,key);return s[b+1:e-1]
classes=['AlignedRotary','LargeAlignedRotary','DirectFloatRotary','BatchedRotary','BulkPositionRotary'];proof={}
for name in classes:
 a,b,e=span(p,'class '+name);aa,bb,ee=span(q,'class '+name);old=p[a:e];new=q[aa:ee];assert old==new
 proof[name]=dict(identical=True,sha256=hashlib.sha256(old.encode()).hexdigest())
a=p.index('namespace rope1743');b=p.index('template <typename T> class SmallRotary');aa=q.index('namespace rope1743');bb=q.index('template <typename T> class SmallRotary');assert p[a:b]==q[aa:bb];proof['all_shared_numerical_helpers']=dict(identical=True,sha256=hashlib.sha256(p[a:b].encode()).hexdigest())
save(H/'helper_identity_817_8d.json',dict(parent_sha256=sha(parent),latest_sha256=sha(latest),selected_classes=proof,scope='Eight actual selected entries; tiny goes through DirectFloatRotary, not SmallRotary'))
protected=['AGENTIC.md','kernel_requirement.md','forbidden.md','operators/rotary_pos_emb/kernel.asc','submissions/rotary_pos_emb/latest.json','tools/suite.py','platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc','platform_trials/rotary_pos_emb/20261017-user-platform-headtile-period/kernel.asc','tuning_requests/rotary_pos_emb/20261017T073409479470Z-8d91182ab86e.json']
save(H/'protected_hashes.json',{f:sha(R/f) for f in protected})
request=json.loads((R/'tuning_requests/rotary_pos_emb/20261017-shared-math-diagnosis.json').read_text());names=[c['name'] for c in request['scope_cases']];cases=json.loads((R/'tests/round6_performance_cases.json').read_text());cases=[next(c for c in cases if c['name']==name) for name in names];native=json.loads((R/'benchmarks/results/agentic_r6_fixed33.json').read_text());lookup={c['name']:c for c in native['cases']};records=[]
for c in cases:
 d=R/'build/data'/c['name'];old=lookup[c['name']]
 hashes={n:sha(d/n) for n in ['x.bin','positions.bin']};assert hashes==old['input_sha256']
 parent_output=R/'build/paired_profiles/agentic_r6_fixed33_forward'/(c['name']+'.bin');latest_output=R/'build/paired_profiles/agentic_r6_fixed33_reverse'/(c['name']+'.bin');assert sha(parent_output)==sha(latest_output)
 records.append(dict(case=c,directory=str(d),input_sha256=hashes,parent_output=str(parent_output),parent_output_sha256=sha(parent_output),latest_output_sha256=sha(latest_output),native_source='benchmarks/results/agentic_r6_fixed33.json',native_baseline_us=old['baseline_us'],native_raw_parent_blocks_us=old['block_medians_us']['baseline']))
save(H/'input_manifest.json',records)
SLOTS=['init_inclusive','frequency','position_angle','trig_inclusive','range_reduction','sin_polynomial','sqrt_input','sqrt','double_angle1','double_angle2','coefficient_post','input_DMA','queue_ops','load_cast','rotation','store_cast','output_DMA_free','identity','process_inclusive','empty','position_broadcast','position_scalar_read','unused22','unused23'];save(H/'trace_schema.json',dict(slots=SLOTS,stride_uint64=96,tick_offset=0,calls_offset=24,elements_offset=48,metadata_offset=72,header_offset=84,magic='0x5348415245444d37',no_clock_conversion=True))
trace='''
// DIAGNOSTIC ONLY. No changes to frequency/trig arithmetic. Never submit this translation unit.
#ifndef DIAG_DETAIL
#define DIAG_DETAIL 0
#endif
static GM_ADDR diagnosticTrace = nullptr; // Host allocation handle; no tensor computation.
struct SharedTrace {
    uint64_t ticks[24]={},calls[24]={},elements[24]={},meta[12]={};
    __aicore__ inline uint64_t Begin() {PipeBarrier<PIPE_ALL>();return uint64_t(GetSystemCycle());}
    __aicore__ inline void End(uint32_t k,uint64_t begin,uint64_t count) {
        PipeBarrier<PIPE_ALL>();uint64_t end=GetSystemCycle();
        ticks[k]+=end-begin;calls[k]++;elements[k]+=count;
    }
    __aicore__ inline void Dump(GM_ADDR address) {
        for(uint32_t i=0;i<32;++i){uint64_t t=Begin();End(19,t,0);}
        GlobalTensor<uint64_t> trace;trace.SetGlobalBuffer((__gm__ uint64_t*)address);
        uint64_t offset=uint64_t(GetBlockIdx())*96;
        for(uint32_t i=0;i<24;++i){trace.SetValue(offset+i,ticks[i]);trace.SetValue(offset+24+i,calls[i]);trace.SetValue(offset+48+i,elements[i]);}
        for(uint32_t i=0;i<12;++i)trace.SetValue(offset+72+i,meta[i]);
        trace.SetValue(offset+84,GetBlockIdx());trace.SetValue(offset+85,GetBlockNum());
        trace.SetValue(offset+86,0x5348415245444d37ULL);trace.SetValue(offset+87,DIAG_DETAIL);
        PipeBarrier<PIPE_ALL>();
    }
};
'''
# Clone the exact arithmetic sequence into a separately named instrumented helper.
a,b,e=span(p,'__aicore__ inline void SinCosFp32(');original=p[a:e];trig=original.replace('SinCosFp32(','SinCosDiag(',1);ix=trig.index('uint32_t n)');trig=trig[:ix]+trig[ix:].replace('uint32_t n)','uint32_t n,SharedTrace& trace)',1)
phase_groups=[('    Muls(q,angle,0.15915494309189535f,n);','    Mul(q,angle,angle,n);',4),('    Mul(q,angle,angle,n);','    Mul(c,s,s,n);',5),('    Mul(c,s,s,n);','Sqrt(c,c,n);',6),('Sqrt(c,c,n);','    Mul(angle,s,c,n);',7),('    Mul(angle,s,c,n);','    Mul(c,angle,angle,n);',8),('    Mul(c,angle,angle,n);',None,9)]
# Cut phases by exact source boundaries, preserving every original vector call and order.
base=body(original,'SinCosFp32(');bounds=[base.index(x[0]) for x in phase_groups]+[len(base)];segments=[]
for i,(_,_,slot) in enumerate(phase_groups):
 segment=base[bounds[i]:bounds[i+1]];segments.append(f'\n    uint64_t diagPhase{slot}=0;if(DIAG_DETAIL)diagPhase{slot}=trace.Begin();\n'+segment+f'\n    if(DIAG_DETAIL)trace.End({slot},diagPhase{slot},n);\n')
# Preserve the leading newline and use the changed signature, not the original function name.
trig=trig[:trig.index('{')+1]+'\n    uint64_t diagWhole=trace.Begin();\n'+''.join(segments)+'\n    trace.End(3,diagWhole,n);\n}'
assert re.findall(r'\b(?:Muls|Mul|Adds|Add|Sub|Cast|Sqrt)\([^;]+;',base)==re.findall(r'\b(?:Muls|Mul|Adds|Add|Sub|Cast|Sqrt)\([^;]+;',trig)
save(H/'numeric_sequence_proof.json',dict(trig_vector_calls_unchanged=True,count=len(re.findall(r'\b(?:Muls|Mul|Adds|Add|Sub|Cast|Sqrt)\([^;]+;',base)),original_helper_sha256=hashlib.sha256(original.encode()).hexdigest()))
s=p[:e]+'\n'+trace+'\n'+trig+'\n'+p[e:]
uid=0

def wrap(text,start,end,slot,count='0'):
 global uid
 a=text.index(start);b=text.index(end,a) if end is not None else len(text);uid+=1;v=f'diagStamp{uid}'
 return text[:a]+f'uint64_t {v}=trace_.Begin();\n'+text[a:b]+f'\ntrace_.End({slot},{v},{count});\n'+text[b:]

def func_transform(cls,key,fn):
 a,b,e=span(cls,key);return cls[:b+1]+fn(cls[b+1:e-1])+cls[e-1:]

for name in classes:
 a,b,e=span(s,'class '+name);cl=s[a:e];isfloat=name=='DirectFloatRotary';isbatch=name in ['BatchedRotary','BulkPositionRotary'];T='float' if isfloat else 'T'
 # One original frequency call per class, in Init or Process as in the parent.
 call=re.search(r'FillDeviceFrequencies\([^;]+;',cl).group();cl=wrap(cl,call,call+'UNREACHABLE',1) if False else cl
 uid+=1;v=f'diagFreq{uid}';cl=cl.replace(call,f'uint64_t {v}=trace_.Begin();\n'+call+f'\ntrace_.End(1,{v},half_);',1)
 def initfn(t):
  meta=[('tokens_'),('1' if isbatch else 'heads_'),'dim_',('tile_' if isbatch else 'tileHeads_'),('half_' if isbatch else 'freqSize_'),('tile_' if isbatch else 'batch_'),('1' if isbatch else 'groups_'),'size_',('pair_' if isbatch else ('workStride_' if name=='LargeAlignedRotary' else 'size_')),f'sizeof({T})','0','0']
  return '\nuint64_t diagInit=trace_.Begin();\n'+t+'\n'+''.join(f'trace_.meta[{i}]={expr};\n' for i,expr in enumerate(meta))+'trace_.End(0,diagInit,0);\n'
 cl=func_transform(cl,'void Init(',initfn)
 # All selected paths prefetch from GM; include queue API and DMA completion in that stage.
 cl=func_transform(cl,'void Prefetch(',lambda t:'\nuint64_t diagDMA=trace_.Begin();\n'+t+'\ntrace_.End(11,diagDMA,Rows(job)*dim_);\n')
 # Cache batch angle generation and coefficient postwork.
 if not isbatch:
  def batchfn(t):
   st=t.index('        for (uint32_t row=0;row<count;++row)');en=t.index('        SinCosFp32(',st)
   t=t[:st]+'uint64_t diagAngle=trace_.Begin();\n'+t[st:en]+'trace_.End(2,diagAngle,count*freqSize_);\n'+t[en:]
   st=t.index('        Muls(angle,s,');en=t.index('        return count;',st)
   t=t[:st]+'uint64_t diagPost=trace_.Begin();\n'+t[st:en]+'trace_.End(10,diagPost,count*freqSize_);\n'+t[en:]
   return t
  cl=func_transform(cl,'uint32_t TrigBatch(',batchfn)
 # Actual trig calls in these five classes, with identical operand lists.
 cl=re.sub(r'SinCosFp32\(([^;]+)\);',lambda m:'SinCosDiag('+m.group(1)+',trace_);',cl)
 def processfn(t):
  # Batched scalar position reads+Muls versus Bulk's vector position broadcast.
  if name=='BatchedRotary':
   st=t.index('            for(uint32_t row=0;row<rows;++row)');en=t.index('            SinCosDiag(',st)
   t=t[:st]+'uint64_t diagAngle=trace_.Begin();\n'+t[st:en]+'trace_.End(2,diagAngle,rows*half_);\n'+t[en:]
  if name=='BulkPositionRotary':
   st=t.index('            auto pf=positions.');en=t.index('            Mul(angle,z,',st)
   t=t[:st]+'uint64_t diagPos=trace_.Begin();\n'+t[st:en]+'trace_.End(20,diagPos,count);\n'+t[en:]
   st=t.index('            Mul(angle,z,');en=t.index('            SinCosDiag(',st)
   t=t[:st]+'uint64_t diagAngle=trace_.Begin();\n'+t[st:en]+'trace_.End(2,diagAngle,rows*half_);\n'+t[en:]
  # Rotation spans before casts: all four products and final addition/subtraction retained.
  if name=='AlignedRotary':t=wrap(t,'                if(fullCos_) {','                StoreFp32(output,r,count);',14,'count')
  elif name=='LargeAlignedRotary':
   t=wrap(t,'                    BinaryRepeatParams cosAndCross','                    output=out_.AllocTensor<T>();',14,'count')
   st=t.index('                } else {',t.index('if (useWideFma'));a2=t.index('                    for(uint32_t col=',st);b2=t.index('                    output=out_.AllocTensor<T>();',a2)
   uid=991;t=t[:a2]+'uint64_t diagFallbackRotate=trace_.Begin();\n'+t[a2:b2]+'trace_.End(14,diagFallbackRotate,count);\n'+t[b2:]
  elif name=='DirectFloatRotary':
   a2=t.index('                for(uint32_t col=');b2=t.index('            }\n            out_.EnQue(output)',a2)
   t=t[:a2]+'uint64_t diagRotate=trace_.Begin();\n'+t[a2:b2]+'trace_.End(14,diagRotate,count);\n'+t[b2:]
  else:
   a2=t.index('            for(uint32_t col=',t.index('LoadFp32('));b2=t.index('            auto output=out_.AllocTensor<T>();',a2)
   t=t[:a2]+'uint64_t diagRotate=trace_.Begin();\n'+t[a2:b2]+'trace_.End(14,diagRotate,count);\n'+t[b2:]
  # Loads/stores, scalar position reads and queue allocations/dequeues get independent markers.
  nonlocal_dummy=0
  def opwrap(m,slot,count):
   global uid
   uid+=1;v=f'diagOp{uid}';return f'uint64_t {v}=trace_.Begin();\n'+m.group()+f'\ntrace_.End({slot},{v},{count});'
  t=re.sub(r'LoadFp32\([^;]+;',lambda m:opwrap(m,13,'count'),t)
  t=re.sub(r'StoreFp32\([^;]+;',lambda m:opwrap(m,15,'count'),t)
  t=re.sub(r'auto input=in_\.DeQue<[^;]+;',lambda m:opwrap(m,12,'0'),t)
  t=re.sub(r'auto positions=positionIn_\.DeQue<[^;]+;',lambda m:opwrap(m,12,'0'),t)
  t=re.sub(r'(?:auto output|output)=out_\.AllocTensor<[^;]+;',lambda m:opwrap(m,12,'0'),t)
  t=re.sub(r'int32_t position=pos_\.GetValue\([^;]+;',lambda m:opwrap(m,21,'1'),t)
  t=re.sub(r'DataCopy\(output,input,count\);',lambda m:opwrap(m,17,'count'),t)
  if name=='BatchedRotary':
   st=t.index('            for(uint32_t row=0;row<rows;++row)',t.index('// Preserve exact identity'));en=t.index('            out_.EnQue(output)',st)
   t=t[:st]+'uint64_t diagIdentity=trace_.Begin();\n'+t[st:en]+'trace_.End(17,diagIdentity,count);\n'+t[en:]
  if name=='BulkPositionRotary':t=re.sub(r'Select\(output,zeroMask_[^;]+;',lambda m:opwrap(m,17,'count'),t)
  st=t.index('            out_.EnQue(output)');en=t.index('out_.FreeTensor(output);',st)+len('out_.FreeTensor(output);')
  t=t[:st]+'uint64_t diagWrite=trace_.Begin();\n'+t[st:en]+'\ntrace_.End(16,diagWrite,count);\n'+t[en:]
  return '\nuint64_t diagProcess=trace_.Begin();\n'+t+'\ntrace_.End(18,diagProcess,0);\n'
 cl=func_transform(cl,'void Process()',processfn)
 # Public trace export, a diagnostic-only Host-provided independent GM region.
 ix=cl.index('private:');cl=cl[:ix]+'__aicore__ inline void DumpTrace(GM_ADDR p){trace_.Dump(p);}\n'+cl[ix:];cl=cl.replace('private:','private:\n    SharedTrace trace_;',1)
 s=s[:a]+cl+s[e:]
# Only wrappers constructing the selected instrumented classes receive an extra trace argument.
wrappers=[]
for m in list(re.finditer(r'__global__ __vector__ void (\w+)\(',s))[::-1]:
 a,b,e=span(s,m.group(0));segment=s[a:e]
 if not any(re.search(r'\b'+name+r'(?:<T>)? op;',segment) for name in classes):continue
 header=segment[:segment.index('{')];pos=header.rfind(')');header=header[:pos]+',GM_ADDR diag'+header[pos:];segment=header+segment[segment.index('{'):-1]+'op.DumpTrace(diag);\n}'
 s=s[:a]+segment+s[e:];wrappers.append(m.group(1))
for fn in wrappers:
 pattern=r'(rope1743::'+fn+r'<[^;]+?<<<[^;]+?>>>\()([^;]+?)(\);)'
 s,n=re.subn(pattern,lambda m:m.group(1)+m.group(2)+',rope1743::diagnosticTrace'+m.group(3),s)
 # Some registered wrappers are unused by this Host; zero calls is valid.
(H/'instrumented.asc').write_text('// DIAGNOSTIC ONLY: never stage/submit. Independent trace buffer; original y preserved.\n'+s)
runner=(R/'tests/runner.asc').read_text().replace('#include "kernel.asc"','#include "instrumented.asc"')
runner=runner.replace('    auto dy=(uint8_t*)dyBase+guardBytes;','''    auto dy=(uint8_t*)dyBase+guardBytes;
    const size_t traceStride=96*sizeof(uint64_t),traceBytes=(cores+2)*traceStride;
    void* dtraceBase;CHECK(aclrtMalloc(&dtraceBase,traceBytes,ACL_MEM_MALLOC_HUGE_FIRST));
    std::vector<uint8_t> htrace(traceBytes,0xa5);
    CHECK(aclrtMemcpy(dtraceBase,traceBytes,htrace.data(),traceBytes,ACL_MEMCPY_HOST_TO_DEVICE));
    rope1743::diagnosticTrace=(GM_ADDR)((uint8_t*)dtraceBase+traceStride);''')
runner=runner.replace('    std::sort(measurements.begin(),measurements.end());','''    CHECK(aclrtMemcpy(htrace.data(),traceBytes,dtraceBase,traceBytes,ACL_MEMCPY_DEVICE_TO_HOST));
    for(size_t i=0;i<traceStride;++i)if(htrace[i]!=0xa5||htrace[traceBytes-traceStride+i]!=0xa5){fprintf(stderr,"trace guard corrupt\\n");return 3;}
    std::ofstream tf(output+".trace",std::ios::binary);tf.write((char*)htrace.data()+traceStride,cores*traceStride);tf.close();
    CHECK(aclrtFree(dtraceBase));rope1743::diagnosticTrace=nullptr;
    std::sort(measurements.begin(),measurements.end());''')
(H/'diagnostic_runner.asc').write_text('// DIAGNOSTIC ONLY. Unmodified original harness kept in tests/runner.asc.\n'+runner)
for mode in ['coarse','detailed']:
 out=B/mode;out.mkdir(exist_ok=True);lines=[]
 for r in records:
  c=r['case'];lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],'--theta',str(c.get('theta',10000)),'--input',r['directory'],'--output',str(out/(c['name']+'.bin')),'--warmup','1','--repeat','1','--batches','1']))
 (B/(mode+'.txt')).write_text('\n'.join(lines)+'\n')
save(R/'benchmarks/experiments/agentic/20261017-shared-math-diagnosis.json',dict(request_id=request['request_id'],state='diagnosis_in_progress',claimed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),parent_source_sha256=sha(parent),candidate_source_sha256=None,implementation_authorized=False,scope_cases=names,diagnostic_source_sha256=sha(H/'instrumented.asc'),latest_platform_result=dict(submission='887393',score=48.29,passes='15/15',baseline_score=48.78),auto_generic_request_consumed=False))
print('Prepared8 frozen cases, diagnostic wrappers',wrappers,'source',sha(H/'instrumented.asc'))
