"""Pure data operations: compliance findings, immutable candidates and run state."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
RULES = (
    'host_only_validation_shape_tiling_launch',
    'no_host_tensor_read_or_reorder',
    'all_frequency_angle_trig_rotation_on_device',
    'no_precomputed_results_or_host_vectors',
    'no_testcase_or_data_pattern_shortcuts',
    'no_markers_stale_output_or_uninitialized_memory',
    'no_judge_precision_or_timing_changes',
    'no_empty_kernel_or_warmup_detection',
    'no_cross_invocation_cache',
    'exactly_one_device_kernel_per_invocation',
    'kernel_asc_is_only_template_change',
)
TERMINAL = {'accepted', 'rejected'}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def code_without_comments(source):
    # Preserve strings and line counts so a comment cannot hide Host math.
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0])
                  if m[0].startswith(('/',)) else m[0], source)


def static_audit(data):
    source = data.decode('utf-8')
    code = code_without_comments(source)
    match = re.search(r'extern\s+"C"\s+void\s+run_kernel\s*\(', code)
    issues = []
    if match is None:
        issues.append({'rule': 'entrypoint', 'detail': 'run_kernel ABI entry is missing'})
        host = code
        offset = 0
    else:
        # Intentionally include everything after the entry: this is a conservative
        # screen, not a C++ parser or a proof about transitively called helpers.
        host = code[match.start():]
        offset = code[:match.start()].count('\n')
    patterns = {
        'host_math': r'\b(?:(?:std::)?(?:powf?|sinf?|cosf?|expf?|logf?|sqrtf?))\s*\(',
        'host_tensor_access': r'\b(?:aclrtMemcpy|aclrtMemset|memcpy|memmove|GetValue|SetValue)\s*\(',
        'host_frequency_table': r'\b(?:frequencies|frequency|f)\s*\.\s*(?:value|scale|correction)\s*\[',
        'host_tensor_pointer': r'\b(?:reinterpret_cast|static_cast)\s*<[^>]*\*\s*>\s*\(\s*(?:x|y|positions)\s*\)',
    }
    for rule, pattern in patterns.items():
        for m in re.finditer(pattern, host):
            issues.append({'rule': rule, 'line': offset + host[:m.start()].count('\n') + 1,
                           'detail': m[0]})
    return {'kernel_sha256': digest(data), 'checked_at': utcnow(),
            'static_screen_passed': not issues, 'issues': issues,
            'scope': 'Conservative source screen only; device computation and Host helper calls need source review.',
            'required_review_assertions': list(RULES)}


def check_review(data, review):
    audit = static_audit(data)
    if audit['issues']:
        raise ValueError('Compliance screen blocked this source: ' + json.dumps(audit['issues'], ensure_ascii=False))
    if review.get('kernel_sha256') != digest(data):
        raise ValueError('Compliance review belongs to a different kernel')
    if not review.get('reviewer') or not review.get('reviewed_at') or not review.get('device_math_notes'):
        raise ValueError('A source review needs reviewer, reviewed_at and device_math_notes')
    if any(review.get('assertions', {}).get(rule) is not True for rule in RULES):
        raise ValueError('The source review must address every current competition rule')
    return audit


def validate_candidate(directory):
    directory = Path(directory)
    manifest = read_json(directory / 'candidate.json')
    data = (directory / 'kernel.asc').read_bytes()
    expected_evidence = {'compliance.json', 'package.json', 'correctness.json', 'launch_audit.json', 'launch_count.json'}
    if set(manifest.get('evidence_sha256', {})) != expected_evidence:
        raise ValueError('Candidate must bind every required evidence file')
    if digest(data) != manifest['kernel_sha256']:
        raise ValueError('Candidate kernel changed after staging')
    evidence = directory / 'evidence'
    for name, expected in manifest['evidence_sha256'].items():
        if Path(name).name != name or digest((evidence / name).read_bytes()) != expected:
            raise ValueError('Candidate evidence changed: ' + name)
    check_review(data, read_json(evidence / 'compliance.json'))
    package = read_json(evidence / 'package.json')
    if package.get('submission_eligible') is False:
        raise ValueError('Package has been marked ineligible under the current competition rules')
    if package.get('compliance_policy') != 'device-computation-supplement-2026-10-15' or (
            package.get('compliance_review_sha256') != manifest['evidence_sha256']['compliance.json']):
        raise ValueError('Package must bind the supplementary-rules source review')
    if package['kernel_sha256'] != digest(data) or package['git_commit'] != manifest['git_commit']:
        raise ValueError('Candidate/package mismatch')
    if package.get('single_kernel_per_iteration') is not True:
        raise ValueError('Missing one-kernel validation')
    if package.get('template_diff', {}).get('changed') != ['kernel.asc']:
        raise ValueError('Only kernel.asc may change in the original template')
    # Staging copied the locally verified reports, not just a claim of testing.
    normal = read_json(evidence / 'correctness.json')
    audit = read_json(evidence / 'launch_audit.json')
    profile = read_json(evidence / 'launch_count.json')
    if any(r.get('source_sha256') != digest(data) for r in (normal, audit, profile)):
        raise ValueError('Local test evidence belongs to another source')
    if not normal.get('cases') or len(normal['cases']) != package['validated_case_count']:
        raise ValueError('Incomplete local correctness evidence')
    if {c['name'] for c in normal['cases']} != {c['name'] for c in audit['cases']}:
        raise ValueError('Normal/audit case coverage differs')
    for report in (normal, audit):
        if not all(c.get('passed') and c.get('guard_ok') and c.get('zero_identity_ok') for c in report['cases']):
            raise ValueError('Local correctness/guard/zero-position gate failed')
    if not all(c.get('one_kernel_per_iteration') and c.get('launch_audit')
               and c['iterations'] == c['kernel_launches'] for c in audit['cases']):
        raise ValueError('Per-invocation launch audit failed')
    if not profile.get('single_kernel_rule_passed') or not profile.get('run_kernel_calls') or (
            profile['run_kernel_calls'] != profile['actual_device_kernel_tasks']):
        raise ValueError('Profiler launch count failed')
    if normal['binary_sha256'] != profile['binary_sha256']:
        raise ValueError('Correctness and profiler did not use the same binary')
    return manifest, data


class Journal:
    """One outstanding submission, durable intent-before-click, no retry of writes.

    A crash or browser timeout after intent leaves the record outstanding. Only
    reading that same result can finish it; there is no automatic re-submission.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def records(self):
        return [read_json(p) for p in sorted(self.root.glob('*/run.json'))]

    def create(self, candidate, config):
        records = self.records()
        if any(r['state'] not in TERMINAL for r in records):
            raise ValueError('An outstanding submission needs resume/reconciliation before another submit')
        if any(r['kernel_sha256'] == candidate['kernel_sha256'] for r in records):
            raise ValueError('This exact source has already been submitted; use its recorded result')
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + candidate['kernel_sha256'][:12]
        record = {'run_id': run_id, 'kernel_sha256': candidate['kernel_sha256'],
                  'git_commit': candidate['git_commit'], 'created_at': utcnow(),
                  'state': 'click_intent', 'submit_url': config['submit_url'],
                  'config_sha256': digest(json.dumps(config, sort_keys=True).encode()),
                  'result_url': None, 'submission_id': None}
        self.save(record)
        return record

    def save(self, record):
        record['updated_at'] = utcnow()
        write_json(self.root / record['run_id'] / 'run.json', record)


def latency_us(value):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(μs|µs|us|ms|ns|s)\s*', value)
    if not match:
        raise ValueError('Ambiguous latency: ' + repr(value))
    number = float(match[1]) * {'μs': 1, 'µs': 1, 'us': 1, 'ms': 1000, 'ns': .001, 's': 1e6}[match[2]]
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Latency must be positive and finite')
    return number


def check_origin(url, allowed):
    u, a = urlparse(url), urlparse(allowed)
    if u.username or u.password or (u.scheme, u.hostname, u.port) != (a.scheme, a.hostname, a.port):
        raise ValueError('Browser navigation left the configured judge origin')


def compare_results(baseline, candidate):
    for report in (baseline, candidate):
        if report.get('state') != 'accepted' or len(report.get('cases', [])) != 15:
            raise ValueError('Comparison requires two accepted platform records with 15 timings')
    b = {c['id']: c['latency_us'] for c in baseline['cases']}
    c = {case['id']: case['latency_us'] for case in candidate['cases']}
    if set(b) != set(range(1, 16)) or set(c) != set(b):
        raise ValueError('Platform case IDs must be unique 1..15')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
           for v in list(b.values()) + list(c.values())):
        raise ValueError('Invalid timing')
    rows = [{'id': i, 'baseline_us': b[i], 'candidate_us': c[i], 'speedup': b[i] / c[i],
             'change_percent': 100 * (c[i] / b[i] - 1)} for i in sorted(b)]
    return {'baseline_sha256': baseline['kernel_sha256'], 'candidate_sha256': candidate['kernel_sha256'],
            'cases': rows, 'geometric_mean_speedup': math.exp(sum(math.log(r['speedup']) for r in rows) / 15),
            'note': 'Descriptive timing comparison; this is not an assumed official scoring formula.'}
