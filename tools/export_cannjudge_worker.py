#!/usr/bin/env python3
"""Export the browser worker only, excluding profiles, credentials and results."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [ROOT / 'tools/cannjudge.py', ROOT / 'docs/cannjudge_workflow.md']
    files.extend(sorted(p for p in (ROOT / 'tools/judge_workflow').iterdir()
                        if p.is_file() and p.suffix in ('.py', '.json', '.txt')))
    destination = ROOT / 'dist/cannjudge_worker.zip'
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in files:
            archive.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
        archive.writestr('README.txt',
            'Browser worker only. This archive contains no kernel, authentication or submission history.\n'
            'Read docs/cannjudge_workflow.md. Install tools/judge_workflow/requirements.txt.\n'
            'login / inspect / submit / resume / compare run on this worker.\n'
            'stage and package run in the full SSH repository. Copy the complete staged candidate directory here.\n'
            'The example configuration is uncalibrated and cannot submit.\n')
    print(destination)


if __name__ == '__main__':
    main()
