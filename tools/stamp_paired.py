#!/usr/bin/env python3
"""Record both sources, the shared runner and compiler flags for a paired build."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--binary', required=True)
    args = ap.parse_args()
    binary = (ROOT / args.binary).resolve()
    flags = binary.parent / 'CMakeFiles/rope_paired_runner.dir/flags.make'
    metadata = dict(binary_sha256=digest(binary),
                    runner_sha256=digest(ROOT / 'tests/paired_runner.asc'),
                    flags=flags.read_text(),
                    git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    source_paths={}, source_sha256={})
    for name in ('baseline', 'candidate'):
        path = (ROOT / getattr(args, name)).resolve()
        metadata['source_paths'][name] = str(path)
        metadata['source_sha256'][name] = digest(path)
    Path(str(binary) + '.meta.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    main()
