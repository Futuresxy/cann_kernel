#!/usr/bin/env python3
"""Assert that the submission contains exactly the template files, changing only kernel.asc."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'templates/rotaryposemb_1743'
HASHES = ROOT / 'templates/rotaryposemb_1743.sha256.json'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def original_template():
    expected = json.loads(HASHES.read_text())
    payload = {p.relative_to(TEMPLATE).as_posix(): p.read_bytes()
               for p in TEMPLATE.rglob('*') if p.is_file()}
    if set(payload) != set(expected):
        raise ValueError('The original template file set has changed')
    for name, data in payload.items():
        if sha256(data) != expected[name]:
            raise ValueError(f'The original template file has changed: {name}')
    return payload


def verify(payload, source):
    original = original_template()
    if set(payload) != set(original):
        raise ValueError(f'Submission file set differs: added={sorted(set(payload)-set(original))}, '
                         f'removed={sorted(set(original)-set(payload))}')
    changed = sorted(name for name in original if original[name] != payload[name])
    if changed != ['kernel.asc']:
        raise ValueError(f'Only kernel.asc may differ; actual changes: {changed}')
    if payload['kernel.asc'] != source:
        raise ValueError('Submission kernel does not match the canonical source')
    return dict(changed=changed, added=[], removed=[],
                unchanged=sorted(set(original)-{'kernel.asc'}), kernel_sha256=sha256(source))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', default='dist/rotaryposemb_1743_submission.zip')
    ap.add_argument('--directory', default='dist/rotaryposemb_1743_submission')
    args = ap.parse_args()
    source = (ROOT/'operators/rotary_pos_emb/kernel.asc').read_bytes()
    with ZipFile(ROOT/args.archive) as z:
        regular = [i.filename for i in z.infolist() if not i.is_dir()]
        if len(regular) != len(set(regular)):
            raise ValueError('Duplicate ZIP entries')
        archive = {name: z.read(name) for name in regular}
    directory = ROOT/args.directory
    files = {p.relative_to(directory).as_posix(): p.read_bytes()
             for p in directory.rglob('*') if p.is_file()}
    result = verify(archive, source)
    if verify(files, source) != result:
        raise ValueError('Archive/directory differ')
    if (ROOT/'dist/kernel.asc').read_bytes() != source:
        raise ValueError('Standalone kernel differs')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
