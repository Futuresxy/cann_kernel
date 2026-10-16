#!/usr/bin/env python3
"""Compare unrelocated device text sections embedded in two ASC executables."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sections(data):
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64')
    offset = struct.unpack_from('<Q', data, 40)[0]
    stride, count, names_index = struct.unpack_from('<HHH', data, 58)
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, offset+i*stride) for i in range(count)]
    header = headers[names_index]
    names = data[header[4]:header[4]+header[5]]
    return {names[h[0]:].split(b'\0', 1)[0].decode(): data[h[4]:h[4]+h[5]] for h in headers}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--rebuilt-baseline')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    binaries = {v: Path(getattr(args, v)).read_bytes() for v in ('baseline', 'candidate')}
    device = {v: sections(sections(b)['__aicore_rel_binary']) for v, b in binaries.items()}
    a, b = device['baseline'], device['candidate']
    rows = []
    for name in a.keys() & b.keys():
        if name.startswith('.text.'):
            rows.append(dict(section=name, baseline_bytes=len(a[name]), candidate_bytes=len(b[name]),
                             identical=a[name]==b[name], baseline_sha256=sha(a[name]), candidate_sha256=sha(b[name])))
    report = dict(shared_kernels=sorted(rows, key=lambda r:r['section']), identical_count=sum(r['identical'] for r in rows),
                  baseline_binary_sha256=sha(binaries['baseline']), candidate_binary_sha256=sha(binaries['candidate']),
                  module_metadata={n:dict(baseline_hex=a[n].hex(),candidate_hex=b[n].hex(),identical=a[n]==b[n])
                                   for n in ('.ascend.stack.size.record','.ascend.meta')})
    if args.rebuilt_baseline:
        report['fresh_v4_binary_sha256'] = sha(Path(args.rebuilt_baseline).read_bytes())
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
    print(f"Identical unrelocated device text: {report['identical_count']}/{len(rows)} shared kernels")


if __name__ == '__main__':
    main()
