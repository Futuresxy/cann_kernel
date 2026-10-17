"""Generate an auditable trace around every unchanged V9 trig operation."""
import hashlib
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BUILD=ROOT/'build/rope_v9_trig_internal'
BUILD.mkdir(parents=True,exist_ok=True)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
kernel=ROOT/'operators/rotary_pos_emb/kernel.asc'
assert sha(kernel)=='5917d3aaeb6969619852ba56cc7934f5bae66540295cf381fc0340bc50529ecc'
text=kernel.read_text()
prefix=text.split('// Small working sets distribute independent frequency columns')[0]+'} // namespace rope1743\n'
signature,body=text.split('__aicore__ inline void SinCosFp32(',1)[1].split('{',1)
signature=signature.strip().removesuffix(')')
body=body.split('}',1)[0]
statements=[s.strip()+';' for s in body.split(';') if s.strip()]
assert len(statements)==34
stages=[dict(index=0,name='input_angle',tensor='angle',dtype='float32',operation=None)]
lines=[]
for i,stmt in enumerate(statements,1):
    op=stmt.split('(',1)[0]
    dst=re.match(r'\w+\((\w+)',stmt)[1]
    dtype='int32' if stmt.startswith('Cast(temp.') else 'float32'
    name=f'{i:02d}_{op}_{dst}'
    stages.append(dict(index=i,name=name,tensor=dst,dtype=dtype,operation=stmt))
    lines += ['    '+stmt, f'    SaveStage(trace,base,{i},{dst},n);']
wrapper='''namespace rope1743 {
constexpr uint32_t TRACE_SLOTS=8,TRACE_WIDTH=512,TRACE_STRIDE=TRACE_SLOTS*TRACE_WIDTH,TRACE_STAGES=35;
__aicore__ inline void SaveStage(const GlobalTensor<float>& trace,uint64_t base,uint32_t stage,
    const LocalTensor<float>& value,uint32_t n) {
    PipeBarrier<PIPE_ALL>();
    DataCopy(trace[base+uint64_t(stage)*TRACE_STRIDE],value,n);
    PipeBarrier<PIPE_ALL>();
}
__aicore__ inline void TraceSinCosFp32('''+signature.strip()+''',
    const GlobalTensor<float>& trace,uint64_t base) {
    SaveStage(trace,base,0,angle,n);
'''+ '\n'.join(lines)+'\n}\n} // namespace rope1743\n'
# Audit all original operation statements, byte-for-byte, after removing traces.
traced_ops=[s.strip() for s in lines if not s.strip().startswith('SaveStage')]
assert traced_ops==statements
(BUILD/'v9_traced_math.h').write_text(prefix+wrapper)
manifest=json.loads((HERE.parent/'rope_v9_system/input_manifest.json').read_text())
for name,expected in manifest['input_sha256'].items():
    assert sha(ROOT/manifest['paths']['input']/name)==expected
assert sha(ROOT/manifest['paths']['baseline_half'])==manifest['baseline_output_sha256']
info=dict(source_sha256=sha(kernel),previous_input_manifest_sha256=sha(HERE.parent/'rope_v9_system/input_manifest.json'),
    input_sha256=manifest['input_sha256'],baseline_output_sha256=manifest['baseline_output_sha256'],
    traced_math_sha256=sha(BUILD/'v9_traced_math.h'),math_statement_identity=True,
    trace_slots=8,trace_width=512,trace_stage_count=35,stages=stages,
    diagnostic_only=True,update_id='20261017T050513-trig-internals')
(HERE/'trace_schema.json').write_text(json.dumps(info,indent=2)+'\n')
print(json.dumps({k:v for k,v in info.items() if k!='stages'},indent=2))
