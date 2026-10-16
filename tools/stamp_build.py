#!/usr/bin/env python3
import argparse,hashlib,json,pathlib,subprocess
root=pathlib.Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--source',default='operators/rotary_pos_emb/kernel.asc');ap.add_argument('--binary',default='build/rope_runner');ap.add_argument('--ref');args=ap.parse_args()
meta=dict(runner_sha256=hashlib.sha256((root/'tests/runner.asc').read_bytes()).hexdigest(),
          audit_header_sha256=hashlib.sha256((root/'tests/launch_audit.h').read_bytes()).hexdigest(),
          source_sha256=hashlib.sha256((root/args.source).read_bytes()).hexdigest(),
          binary_sha256=hashlib.sha256((root/args.binary).read_bytes()).hexdigest(),
          git_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()),
          git_commit=args.ref or subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip())
pathlib.Path(str(root/args.binary)+'.meta.json').write_text(json.dumps(meta,indent=2)+'\n')
