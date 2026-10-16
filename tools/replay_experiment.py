#!/usr/bin/env python3
"""Reconstruct a recorded single-file candidate and build it without a device."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
RECORD=ROOT/'benchmarks/experiments'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('name')
    ap.add_argument('--source-only',action='store_true')
    ap.add_argument('--round',default='round2',choices=['round2','round3','round4'])
    args=ap.parse_args()
    record=RECORD/args.round
    manifest=json.loads((record/'manifest.json').read_text())
    candidates={c['name']:c for c in manifest['candidates']}
    if args.name not in candidates:
        ap.error('Choose one of: '+', '.join(candidates))
    c=candidates[args.name]
    base=subprocess.check_output(['git','show',manifest['baseline_revision']+
                                  ':operators/rotary_pos_emb/kernel.asc'],cwd=ROOT)
    if hashlib.sha256(base).hexdigest()!=manifest['baseline_sha256']:
        raise RuntimeError('Baseline does not match the recorded source')
    folder=ROOT/'build/replayed_experiments'/args.round/args.name
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'baseline.asc').write_bytes(base)
    source=folder/'kernel.asc'
    subprocess.run(['patch','--batch','--fuzz=0','--output',str(source),
                    str(folder/'baseline.asc'),str(record/c['patch'])],check=True)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=c['source_sha256']:
        raise RuntimeError('Reconstructed candidate does not match its recorded hash')
    print(source,flush=True)
    if args.source_only:
        return
    subprocess.run(['cmake','-S',str(ROOT),'-B',str(folder/'build'),
                    '-DROPE_KERNEL_DIR='+str(folder)],check=True)
    subprocess.run(['cmake','--build',str(folder/'build'),'-j4'],check=True)
    subprocess.run([sys.executable,str(ROOT/'tools/stamp_build.py'),
                    '--source',str(source),'--binary',str(folder/'build/rope_runner')],check=True)


if __name__=='__main__':
    main()
