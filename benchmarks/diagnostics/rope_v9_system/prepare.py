"""Freeze the failed input and copy only unmodified V9 math into a dev build."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
out=ROOT/'build/rope_v9_system';out.mkdir(parents=True,exist_ok=True)
source=ROOT/'operators/rotary_pos_emb/kernel.asc';data=source.read_bytes()
assert hashlib.sha256(data).hexdigest()=='5917d3aaeb6969619852ba56cc7934f5bae66540295cf381fc0340bc50529ecc'
helper=data.split(b'// Small working sets distribute independent frequency columns')[0]+b'} // namespace rope1743\n'
(out/'v9_math_snapshot.h').write_bytes(helper)
original=ROOT/'benchmarks/experiments/agentic/20261017T041419176110Z-vector-fma/wide/amplitude_candidate_hashes.json'
hashes=json.loads(original.read_text())['float16'];inp=out/'input';inp.mkdir(exist_ok=True)
for name in ['x.bin','positions.bin']:
    src=ROOT/'build/data/r2wide_amplitude_float16'/name
    assert hashlib.sha256(src.read_bytes()).hexdigest()==hashes[name]
    shutil.copyfile(src,inp/name)
baseline=ROOT/'build/agentic_r2wide/amplitude_candidate_half.bin'
assert hashlib.sha256(baseline.read_bytes()).hexdigest()==hashes['actual.bin']
shutil.copyfile(baseline,out/'v9_baseline_half.bin')
info=dict(source_sha256=hashlib.sha256(data).hexdigest(),math_snapshot_sha256=hashlib.sha256(helper).hexdigest(),input_sha256={k:v for k,v in hashes.items() if k!='actual.bin'},baseline_output_sha256=hashes['actual.bin'],shape=[1,137,17,1024],dtype='float16',theta=10000,seed=175322,scale=60000,zero_every=7,extreme=True,special=True,paths=dict(input=str(inp.relative_to(ROOT)),baseline_half=str((out/'v9_baseline_half.bin').relative_to(ROOT))),policy_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['AGENTIC.md','kernel_requirement.md','forbidden.md']})
(Path(__file__).with_name('input_manifest.json')).write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info,indent=2))
