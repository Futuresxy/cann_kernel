"""DIAGNOSTIC ONLY: clone frequency helpers; preserve original helpers and arithmetic."""
import hashlib,json,re,shlex
from pathlib import Path
H=Path(__file__).resolve().parent; P=H.parent; R=H.parents[4]; B=R/'build/agentic_r7_frequency';B.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def span(s,key):
 a=s.index(key);b=s.index('{',a);e=b+1;depth=1
 while depth:depth+=(s[e]=='{')-(s[e]=='}');e+=1
 return a,b,e
def fun(s,key):
 a,b,e=span(s,key);return s[a:e]
parent=R/'platform_trials/rotary_pos_emb/20261017-user-platform-wide-fma/kernel.asc';s=parent.read_text();assert sha(parent)=='817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556'
slots=['frequency_inclusive','unused1','scalar_log53_setup','scalar_loop_setup','scalar_exponent_ratio','scalar_try_q31','scalar_q53_fallback_inclusive','scalar_root_build_nested','scalar_reciprocal_pack','scalar_UB_store','vector_normalization','vector_logtheta_setup','vector_geometry','vector_exp2table','vector_chunk_inclusive','vector_ratio','vector_logproduct_range','vector_polynomial_table_power','vector_reciprocal_round','vector_restore_copy','tail_padding_drain','empty','unused22','unused23']
meta=['mode_1scalar_2vector','width','pitch','scratch_float_elements','vector_stride','Q31_fallback_count','root_build_count','Q31_attempt_count','power_reuse_count','frequency_fallback_allocation_bytes','binary_width','chunk_count']
save(H/'trace_schema.json',dict(slots=slots,metadata=meta,stride_uint64=96,tick_offset=0,calls_offset=24,elements_offset=48,metadata_offset=72,header_offset=84,magic='0x4652455144494137'))
trace='''
// DIAGNOSTIC ONLY: explicit separate GM allocation, no y-buffer borrowing, no cross-core sync.
static GM_ADDR diagnosticTrace=nullptr;
struct FrequencyTrace {
 uint64_t ticks[24]={},calls[24]={},elements[24]={},meta[12]={};
 __aicore__ inline uint64_t Begin(){PipeBarrier<PIPE_ALL>();return uint64_t(GetSystemCycle());}
 __aicore__ inline void End(uint32_t k,uint64_t begin,uint64_t count){
  PipeBarrier<PIPE_ALL>();uint64_t end=GetSystemCycle();ticks[k]+=end-begin;calls[k]++;elements[k]+=count;
 }
 __aicore__ inline void Dump(GM_ADDR address){
  for(uint32_t i=0;i<32;++i){uint64_t t=Begin();End(21,t,0);}
  GlobalTensor<uint64_t> gm;gm.SetGlobalBuffer((__gm__ uint64_t*)address);
  uint64_t row=uint64_t(GetBlockIdx())*96;
  for(uint32_t i=0;i<24;++i){gm.SetValue(row+i,ticks[i]);gm.SetValue(row+24+i,calls[i]);gm.SetValue(row+48+i,elements[i]);}
  for(uint32_t i=0;i<12;++i)gm.SetValue(row+72+i,meta[i]);
  gm.SetValue(row+84,GetBlockIdx());gm.SetValue(row+85,GetBlockNum());
  gm.SetValue(row+86,0x4652455144494137ULL);gm.SetValue(row+87,1);PipeBarrier<PIPE_ALL>();
 }
};
'''
proof={}
# The scalar clone retains the exact original integer expressions, branches and store order.
orig=fun(s,'__aicore__ inline void ScalarFrequencies('); scalar=orig.replace('ScalarFrequencies(','ScalarFrequenciesDiag(',1).replace('const LocalTensor<float>& scratch) {','const LocalTensor<float>& scratch,FrequencyTrace& trace) {',1)
scalar=scalar.replace('    int64_t log=DeviceLog2Q53(theta),log31=log/int64_t(4194304LL);','    uint64_t diagLog=trace.Begin();\n    int64_t log=DeviceLog2Q53(theta),log31=log/int64_t(4194304LL);\n    trace.End(2,diagLog,1);\n    uint64_t diagSetup=trace.Begin();',1)
scalar=scalar.replace('    for(uint32_t i=0;i<width;++i) {','    trace.End(3,diagSetup,1);\n    for(uint32_t i=0;i<width;++i) {',1)
scalar=scalar.replace('            uint32_t numerator=i,denominatorLog=widthLog;','            uint64_t diagRatio=trace.Begin();\n            uint32_t numerator=i,denominatorLog=widthLog;',1)
scalar=scalar.replace('            uint64_t pm=0;int32_t e=0;','            trace.End(4,diagRatio,1);\n            uint64_t pm=0;int32_t e=0;',1)
scalar=scalar.replace('            if(!TryExp2PowerQ31(log31,numerator,denominatorLog,pm,e)) {','            uint64_t diagQ31=trace.Begin();\n            bool diagAccepted=TryExp2PowerQ31(log31,numerator,denominatorLog,pm,e);\n            trace.End(5,diagQ31,1);++trace.meta[7];\n            if(!diagAccepted) {\n            ++trace.meta[5];uint64_t diagFallback=trace.Begin();',1)
scalar=scalar.replace('if((ki&31)!=0 && !rootsReady){BuildExp2Roots(table);rootsReady=true;}','if((ki&31)!=0 && !rootsReady){uint64_t diagRoot=trace.Begin();BuildExp2Roots(table);rootsReady=true;trace.End(7,diagRoot,1);++trace.meta[6];}',1)
scalar=scalar.replace('            pm=RoundDivide(power,uint64_t(1)<<30);\n            }','            pm=RoundDivide(power,uint64_t(1)<<30);\n            trace.End(6,diagFallback,1);\n            }\n            uint64_t diagReciprocal=trace.Begin();',1)
scalar=scalar.replace('if(powerKey==previousPower)result=previousResult;','if(powerKey==previousPower){result=previousResult;++trace.meta[8];}',1)
scalar=scalar.replace('        }\n        FloatBits f;f.bits=result;dst.SetValue(i,f.value);','            trace.End(8,diagReciprocal,1);\n        }\n        uint64_t diagStore=trace.Begin();\n        FloatBits f;f.bits=result;dst.SetValue(i,f.value);\n        trace.End(9,diagStore,1);',1)
scalar=scalar.replace('    for(uint32_t i=width;i<pitch;++i)dst.SetValue(i,0.0f);','    uint64_t diagTail=trace.Begin();\n    for(uint32_t i=width;i<pitch;++i)dst.SetValue(i,0.0f);',1)
scalar=scalar.replace('    PipeBarrier<PIPE_ALL>();\n}','    PipeBarrier<PIPE_ALL>();\n    trace.End(20,diagTail,pitch-width);\n}',1)
# Each vector segment boundary drains only this core. No arithmetic operations changed.
origchunk=fun(s,'__aicore__ inline void DeviceFrequencyChunk(')
chunk=origchunk.replace('DeviceFrequencyChunk(','DeviceFrequencyChunkDiag(',1).replace('float finishScale) {','float finishScale,FrequencyTrace& trace) {',1)
a=chunk.index('{');body=chunk[a+1:-1]
bounds=[body.index('    // Integer indices'),body.index('    Duplicate(v3,logHi,n);'),body.index('    Muls(v1,v8,0.0555036142f,n);'),body.index('    Duplicate(v7,1.0f,n);'),body.index('    DataCopy(dst,v5,n);'),len(body)]
new=body[:bounds[0]]+'\n uint64_t diagChunk=trace.Begin();++trace.meta[11];\n'
for k,(start,end) in enumerate(zip(bounds,bounds[1:])):
 slot=15+k;new+=f' uint64_t diagPart{slot}=trace.Begin();\n'+body[start:end]+f'\n trace.End({slot},diagPart{slot},n);\n'
new+=' trace.End(14,diagChunk,n);\n';chunk=chunk[:a+1]+new+'}'
# Token-level vector math API call proof; count is API calls, not ISA count.
pat=r'\b(?:CreateVecIndex|Duplicate|Div|Mul|Muls|Sub|Add|Adds|Cast|Gather|ShiftLeft|DataCopy)\([^;]+;'
assert re.findall(pat,origchunk)==re.findall(pat,chunk)
proof['vector_chunk']={'all_API_calls_operands_and_order_identical':True,'API_calls_general_source':len(re.findall(pat,origchunk)),'original_sha256':hashlib.sha256(origchunk.encode()).hexdigest()}
fill=fun(s,'__aicore__ inline void FillFrequencies(').replace('FillFrequencies(','FillFrequenciesDiag(',1).replace('const LocalTensor<float>& scratch) {','const LocalTensor<float>& scratch,FrequencyTrace& trace) {',1)
fill=fill.replace('    FloatBits bits;bits.value=f.theta;','    uint64_t diagNormalize=trace.Begin();\n    FloatBits bits;bits.value=f.theta;',1)
fill=fill.replace('    float logHi,logLo;DeviceLogTheta(mantissa,exponent,scratch,logHi,logLo);','    trace.End(10,diagNormalize,1);\n    uint64_t diagLog=trace.Begin();\n    float logHi,logLo;DeviceLogTheta(mantissa,exponent,scratch,logHi,logLo);\n    trace.End(11,diagLog,1);\n    uint64_t diagGeometry=trace.Begin();',1)
fill=fill.replace('    DeviceExp2Table(table,scratch,stride);','    trace.meta[4]=stride;trace.End(12,diagGeometry,1);\n    uint64_t diagTable=trace.Begin();\n    DeviceExp2Table(table,scratch,stride);\n    trace.End(13,diagTable,32);',1)
fill=fill.replace('DeviceFrequencyChunk(dst[start],table,scratch,start,width,count,stride,logHi,logLo,shift,finish);','DeviceFrequencyChunkDiag(dst[start],table,scratch,start,width,count,stride,logHi,logLo,shift,finish,trace);',1)
fill=fill.replace('    for(uint32_t i=width;i<pitch;++i)dst.SetValue(i,0.0f);','    uint64_t diagTail=trace.Begin();\n    for(uint32_t i=width;i<pitch;++i)dst.SetValue(i,0.0f);',1).replace('    PipeBarrier<PIPE_ALL>();\n}','    PipeBarrier<PIPE_ALL>();\n    trace.End(20,diagTail,pitch-width);\n}',1)
# Preserve original allocation decisions/overloads.
a=s.index('__aicore__ inline void FillDeviceFrequencies(');b=s.index('// C++14 overloads',a);dispatch=s[a:b]
dispatch=dispatch.replace('FillDeviceFrequencies(','FillDeviceFrequenciesDiag(').replace('const LocalTensor<float>& scratch) {','const LocalTensor<float>& scratch,FrequencyTrace& trace) {')
dispatch=dispatch.replace('    if(scratch.GetSize()>=16)', '    trace.meta[0]=1;trace.meta[1]=width;trace.meta[2]=pitch;trace.meta[3]=scratch.GetSize();trace.meta[10]=((width&(width-1))==0);\n    if(scratch.GetSize()>=16)',1)
dispatch=dispatch.replace('ScalarFrequencies(dst,f.theta,width,pitch,scratch);','ScalarFrequenciesDiag(dst,f.theta,width,pitch,scratch,trace);').replace('pipe.InitBuffer(fallback,64);ScalarFrequencies(dst,f.theta,width,pitch,fallback.Get<float>());','pipe.InitBuffer(fallback,64);trace.meta[9]=64;ScalarFrequenciesDiag(dst,f.theta,width,pitch,fallback.Get<float>(),trace);')
dispatch=dispatch.replace('    uint32_t full=', '    trace.meta[0]=2;trace.meta[1]=width;trace.meta[2]=pitch;trace.meta[3]=scratch.GetSize();trace.meta[10]=((width&(width-1))==0);\n    uint32_t full=',1)
dispatch=dispatch.replace('FillFrequencies(dst,f,width,pitch,scratch);','FillFrequenciesDiag(dst,f,width,pitch,scratch,trace);').replace('pipe.InitBuffer(fallback,full*sizeof(float));FillFrequencies(dst,f,width,pitch,fallback.Get<float>());','pipe.InitBuffer(fallback,full*sizeof(float));trace.meta[9]=full*sizeof(float);FillFrequenciesDiag(dst,f,width,pitch,fallback.Get<float>(),trace);')
# Original frequency helpers, FP32 numerical helpers, trig and rotation stay intact.
insert=s.index('template <typename T> class SmallRotary');s=s[:insert]+trace+'\n'+scalar+'\n'+chunk+'\n'+fill+'\n'+dispatch+s[insert:]
classes=['AlignedRotary','LargeAlignedRotary','DirectFloatRotary','BatchedRotary','BulkPositionRotary']
for name in classes:
 a,b,e=span(s,'class '+name);cl=s[a:e];call=re.search(r'FillDeviceFrequencies\([^;]+;',cl).group()
 replacement='uint64_t diagTotal=trace_.Begin();\n'+call.replace('FillDeviceFrequencies(','FillDeviceFrequenciesDiag(',1)[:-2]+',trace_);\ntrace_.End(0,diagTotal,half_);'
 cl=cl.replace(call,replacement,1);ix=cl.index('private:');cl=cl[:ix]+'__aicore__ inline void DumpTrace(GM_ADDR p){trace_.Dump(p);}\n'+cl[ix:];cl=cl.replace('private:','private:\n FrequencyTrace trace_;',1);s=s[:a]+cl+s[e:]
wrappers=[]
for m in list(re.finditer(r'__global__ __vector__ void (\w+)\(',s))[::-1]:
 a,b,e=span(s,m.group(0));part=s[a:e]
 if not any(re.search(r'\b'+name+r'(?:<T>)? op;',part) for name in classes):continue
 head=part[:part.index('{')];ix=head.rfind(')');part=head[:ix]+',GM_ADDR diag'+head[ix:]+part[part.index('{'):-1]+'op.DumpTrace(diag);\n}';s=s[:a]+part+s[e:];wrappers.append(m.group(1))
for fn in wrappers:
 pattern=r'(rope1743::'+fn+r'<[^;]+?<<<[^;]+?>>>\()([^;]+?)(\);)'
 s=re.sub(pattern,lambda m:m.group(1)+m.group(2)+',rope1743::diagnosticTrace'+m.group(3),s)
for key in ['DeviceLogTheta','DeviceLog2Q53','TryExp2PowerQ31','BuildExp2Roots','ScalarFrequencies','DeviceFrequencyChunk','DeviceExp2Table','FillFrequencies','SinCosFp32']:
 original=fun(parent.read_text(),('__aicore__ inline int64_t ' if key=='DeviceLog2Q53' else '__aicore__ inline bool ' if key=='TryExp2PowerQ31' else '__aicore__ inline void ')+key+'(')
 assert original in s,key
 proof[key]={'original_helper_retained_byte_identical':True,'sha256':hashlib.sha256(original.encode()).hexdigest()}
(H/'instrumented.asc').write_text('// DIAGNOSTIC ONLY: NEVER SUBMIT. Frequency-only counters, separate trace ABI.\n'+s)
runner=(P/'diagnostic_runner.asc').read_text();(H/'diagnostic_runner.asc').write_text(runner)
cm=(P/'CMakeLists.txt').read_text().replace('shared_probe','frequency_probe').replace('../../../../tests','../../../../../tests').replace('../../../../templates','../../../../../templates');(H/'CMakeLists.txt').write_text(cm)
records=json.loads((P/'input_manifest.json').read_text());out=B/'output';out.mkdir(exist_ok=True);lines=[]
for rec in records:
 c=rec['case'];lines.append(shlex.join(['--shape',*map(str,c['shape']),'--dtype',c['dtype'],'--theta',str(c.get('theta',10000)),'--input',rec['directory'],'--output',str(out/(c['name']+'.bin')),'--warmup','1','--repeat','1','--batches','1']))
(B/'cases.txt').write_text('\n'.join(lines)+'\n')
save(H/'source_audit.json',dict(diagnostic_only=True,parent_sha256=sha(parent),source_sha256=sha(H/'instrumented.asc'),runner_sha256=sha(H/'diagnostic_runner.asc'),helper_proofs=proof,trace_row_bytes=768,trace_cells_written=88,private_counter_state_bytes=672,extra_TPipe_UB_bytes=0,no_cross_core_synchronization=True,scope='Eight already frozen public inputs. Per-phase scalar markers perturb scheduling; no speedup claims.'))
print('Prepared frequency-only diagnostic',sha(H/'instrumented.asc'))
