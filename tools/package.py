#!/usr/bin/env python3
"""Produce a standalone kernel and a complete template-compatible submission."""
import argparse,hashlib,json,pathlib,subprocess,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--result',default='final');args=ap.parse_args()
    source=ROOT/'operators/rotary_pos_emb/kernel.asc';sha=hashlib.sha256(source.read_bytes()).hexdigest()
    results=json.loads((ROOT/'benchmarks/results'/f'{args.result}.json').read_text())
    names={c['name'] for c in json.loads((ROOT/'tests/cases.json').read_text())}
    if {c['name'] for c in results['cases']}!=names:raise SystemExit('Packaging requires the complete correctness suite')
    if not all(c['passed'] and c['guard_ok'] and c.get('zero_identity_ok',False) for c in results['cases']):raise SystemExit('Correctness gate failed')
    if results['source_sha256']!=sha:raise SystemExit('Results do not belong to current source; rebuild and retest')
    dest=ROOT/'dist';dest.mkdir(exist_ok=True)
    (dest/'kernel.asc').write_bytes(source.read_bytes())
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    committed=subprocess.check_output(['git','show',revision+':operators/rotary_pos_emb/kernel.asc'],cwd=ROOT)
    if hashlib.sha256(committed).hexdigest()!=sha:raise SystemExit('Commit the validated kernel before packaging')
    manifest=dict(problem=1743,operator='RotaryPosEmb',git_commit=revision,kernel_sha256=sha,
                  result=args.result,validated_case_count=len(results['cases']),soc=results['cases'][0]['soc'],
                  precision_reference='supplied NumPy FP32 golden',
                  platform_hidden_cases_tested=False)
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    payload={p.relative_to(ROOT/'templates/rotaryposemb_1743').as_posix():p.read_bytes()
             for p in (ROOT/'templates/rotaryposemb_1743').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    payload['kernel.asc']=source.read_bytes()
    payload['CMakeLists.txt']=payload['CMakeLists.txt'].replace(b'CMAKE_CXX_STANDARD 14',b'CMAKE_CXX_STANDARD 17')
    payload['main.asc']=payload['main.asc'].replace(b'int32_t deviceId = 0;',
        b'int32_t deviceId = std::getenv("TASK_DEVICE") ? std::atoi(std::getenv("TASK_DEVICE")) : 0;')
    payload['run.sh']=b'''#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source "${ASCEND_INSTALL_PATH:-/usr/local/Ascend/ascend-toolkit/latest}/set_env.sh"
cmake -S . -B build
cmake --build build -j4
cd build
python3 ../scripts/gen_data.py
cp input/case0/x.bin input/x.bin
cp input/case0/positions.bin input/positions.bin
cp output/golden_case0/golden_y.bin output/golden_y.bin
timeout 30 ./rotary_pos_emb_custom
python3 ../scripts/verify_result.py 0
'''
    payload['manifest.json']=(dest/'manifest.json').read_bytes()
    archive=dest/'rotaryposemb_1743_submission.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(payload.items()):z.writestr(name,data)
    print(json.dumps(dict(kernel=str(dest/'kernel.asc'),archive=str(archive),**manifest),indent=2))
if __name__=='__main__':main()
