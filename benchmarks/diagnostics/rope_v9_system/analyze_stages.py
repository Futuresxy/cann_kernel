"""Read-only CPU attribution. Acceptance reference/limits are never modified.

Run after prepare.py and the single-launch stage_probe. High-precision results
are diagnostic oracles, NOT replacements for the current FP32 acceptance chain.
"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import mpmath as mp
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUILD = ROOT / 'build/rope_v9_system'
T, H, D, W, CORES = 137, 17, 1024, 512, 48
mp.mp.dps = 80
np.seterr(invalid='ignore', over='ignore', divide='ignore')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordered(a):
    u = np.asarray(a, np.float32).view(np.uint32).astype(np.int64)
    return np.where(u & 0x80000000, 0x80000000 - (u & 0x7fffffff), u + 0x80000000)


def stats(a, b, mask=None):
    a, b = np.broadcast_arrays(np.asarray(a, np.float32), np.asarray(b, np.float32))
    mask = np.ones(a.shape, bool) if mask is None else np.broadcast_to(mask, a.shape)
    finite = np.isfinite(a) & np.isfinite(b) & mask
    e = np.abs(a[finite].astype(np.float64) - b[finite].astype(np.float64))
    u = np.abs(ordered(a[finite]) - ordered(b[finite]))
    classes = ((np.isnan(a) & np.isnan(b)) | ((a == b) & ~np.isnan(a)))
    classes |= np.isfinite(a) & np.isfinite(b)
    return dict(elements=int(mask.sum()), finite=int(finite.sum()),
                bit_differences=int(np.count_nonzero((a.view('u4') != b.view('u4')) & mask)),
                nonfinite_class_mismatches=int(np.count_nonzero(~classes & mask)),
                max_abs_error=float(e.max(initial=0)), mean_abs_error=float(e.mean()) if len(e) else 0,
                max_ulp=int(u.max(initial=0)), p99_ulp=float(np.quantile(u, .99)) if len(u) else 0,
                caveat='ULP uses ordered FP32 bit distance; near-zero cancellation magnifies ULP counts.')


def half_check(a, b):
    finite = np.isfinite(a) & np.isfinite(b)
    error = np.zeros(a.shape, np.float64)
    error[finite] = np.abs(a[finite].astype(np.float64)-b[finite].astype(np.float64))
    matched = finite & (error <= .00195 + .00195*np.abs(b.astype(np.float64)))
    matched |= (np.isnan(a) & np.isnan(b)) | (np.isinf(a) & (a == b))
    mismatch = ~finite & ~((np.isnan(a) & np.isnan(b)) | (np.isinf(a) & (a == b)))
    maximum = float('inf') if mismatch.any() else float(error.max())
    return dict(matched_ratio=float(matched.mean()), max_abs_error=maximum,
                finite_elements_above_max_abs_limit=int(np.count_nonzero(error > .1)),
                element_tolerance_failures=int(np.count_nonzero(~matched)),
                pass_current_rules=bool(matched.mean() >= .99 and maximum <= .1))


def trig_replay(a):
    # Each NumPy FP32 operation is separately rounded, in V9 source order.
    q = np.rint(a * np.float32(.15915494309189535)).astype(np.float32)
    r = a-q*np.float32(6.25)
    r = r-q*np.float32(.033203125)
    r = r-q*np.float32(-.000017817820413523074)
    z = r*np.float32(.25); u = z*z
    s = u*np.float32(1/362880)+np.float32(-1/5040)
    s = s*u+np.float32(1/120); s = s*u+np.float32(-1/6)
    s = s*u+np.float32(1); s = s*z
    c = np.sqrt(np.float32(1) + (s*s)*np.float32(-1))
    v = (s*c)*np.float32(2)
    s = (s*s)*np.float32(-2)+np.float32(1)
    c = (v*v)*np.float32(-2)+np.float32(1)
    s = (v*s)*np.float32(2)
    return q, r, c, s


def rotate(x, c, s):
    a, b = x[..., :W].astype('f4'), x[..., W:].astype('f4')
    pc = np.concatenate((a*c[:, None, :], b*c[:, None, :]), -1)
    cross = np.concatenate((-b*s[:, None, :], a*s[:, None, :]), -1)
    return pc, cross, pc+cross


raw = np.fromfile(BUILD/'stages.bin', np.float32)
layout = {}; offset = 0
for name, shape in [('frequency', (CORES, W))] + [(n, (T, W)) for n in ['angle', 'reduced', 'quotient', 'cosine', 'sine']] + [(n, (T, H, D)) for n in ['pcos', 'cross', 'fp32_y']]:
    size = int(np.prod(shape)); layout[name] = raw[offset:offset+size].reshape(shape); offset += size
assert offset == len(raw)
x = np.fromfile(BUILD/'input/x.bin', np.float16).reshape(T, H, D)
p = np.fromfile(BUILD/'input/positions.bin', np.int32)
y = np.fromfile(BUILD/'probe_half.bin', np.float16).reshape(x.shape)
assert (BUILD/'probe_half.bin').read_bytes() == (BUILD/'v9_baseline_half.bin').read_bytes()
active = p != 0
freq = np.float32(1)/np.power(np.float32(10000), np.arange(W, dtype='f4')/np.float32(W))
angle = p.astype('f4')[:, None]*freq
c, s = np.cos(angle), np.sin(angle)
pc, cross, reference32 = rotate(x, c, s)
reference32[~active] = x[~active]
gold = reference32.astype('f2'); gold[~active] = x[~active]
# Independently invoke the unchanged suite: check both frozen input hashes and
# reference bit identity before attributing any error with the analysis model.
spec = importlib.util.spec_from_file_location('unchanged_suite', ROOT/'tools/suite.py')
suite = importlib.util.module_from_spec(spec); spec.loader.exec_module(suite)
case = dict(shape=[1,T,H,D], dtype='float16', theta=10000., pmax=131073,
            scale=60000, zero_every=7, extreme=True, special=True)
_, _, suite_gold = suite.generate(case, BUILD/'regenerated_input', 175322)
for name in ['x.bin','positions.bin']:
    assert sha(BUILD/'regenerated_input'/name) == sha(BUILD/'input'/name)
assert np.array_equal(suite_gold.reshape(x.shape).view('u2'), gold.view('u2'))
acceptance = suite.compare(y, suite_gold.reshape(x.shape))
local_check = half_check(y, gold)
assert acceptance['matched_ratio'] == local_check['matched_ratio']
assert acceptance['max_abs_error'] == local_check['max_abs_error']
assert acceptance['passed'] == local_check['pass_current_rules']
dc, ds = layout['cosine'], layout['sine']
dpc, dxr, conditional32 = rotate(x, dc, ds)
q, reduced, replay_c, replay_s = trig_replay(angle)
results = dict(schema_version=1, diagnostic_only=True,
    acceptance_reference='Unchanged tools/suite.py FP32 frequency/power reciprocal, FP32 angle/trig/products/add, then FP16 cast; p=0 identity.',
    source_sha256=json.loads((HERE/'input_manifest.json').read_text())['source_sha256'],
    dump_sha256=sha(BUILD/'stages.bin'), probe_output_sha256=sha(BUILD/'probe_half.bin'),
    zero_position_tokens=int(np.count_nonzero(~active)), active_tokens=int(active.sum()),
    frequency_core_consistency=stats(layout['frequency'], layout['frequency'][0]),
    inv_freq_device_vs_current_fp32=stats(layout['frequency'][0], freq),
    angle_device_vs_current_fp32=stats(layout['angle'], angle),
    range_quotient_device_vs_cpu_replay=stats(layout['quotient'], q),
    range_reduced_device_vs_cpu_replay=stats(layout['reduced'], reduced),
    cosine_device_vs_current_fp32=stats(dc, c, active[:, None]),
    sine_device_vs_current_fp32=stats(ds, s, active[:, None]),
    cosine_device_vs_cpu_source_replay=stats(dc, replay_c, active[:, None]),
    sine_device_vs_cpu_source_replay=stats(ds, replay_s, active[:, None]),
    pcos_conditional_on_device_trig=stats(layout['pcos'], dpc, active[:, None, None]),
    cross_conditional_on_device_trig=stats(layout['cross'], dxr, active[:, None, None]),
    fp32_rotation_conditional_on_device_trig=stats(layout['fp32_y'], conditional32, active[:, None, None]),
    fp32_rotation_vs_current_fp32=stats(layout['fp32_y'], reference32),
    fp16_cast_conditional_on_device_fp32=stats(y, layout['fp32_y'].astype('f2')),
    final_vs_current_reference=half_check(y, gold),
    unchanged_suite_acceptance=acceptance,
    unchanged_suite_sha256=sha(ROOT/'tools/suite.py'),
    regenerated_input_and_reference_bit_identity=True,
    position_zero_identity_bit_mismatches=int(np.count_nonzero(y[~active].view('u2') != x[~active].view('u2'))))

# Independent high precision: distinguish the FP32 chain's required rounding
# from exact real-valued RoPE. Never substitute these arrays into acceptance.
freq_real = [mp.power(mp.mpf(10000), -mp.mpf(i)/W) for i in range(W)]
freq_contract = np.array([np.float32(float(1/mp.mpf(float(np.float32(float(mp.power(mp.mpf(10000), mp.mpf(i)/W))))))) for i in range(W)], 'f4')
results['inv_freq_vs_high_precision_rounded_power_then_reciprocal'] = stats(layout['frequency'][0], freq_contract)
results['inv_freq_vs_high_precision_direct_inverse_power'] = stats(layout['frequency'][0], np.array([float(v) for v in freq_real], 'f4'))
hp_c = np.empty((T, W), 'f8'); hp_s = np.empty_like(hp_c)
real_c = np.empty_like(hp_c); real_s = np.empty_like(hp_c)
hp_reduced = np.empty_like(hp_c)
for token in range(T):
    for i in range(W):
        a = mp.mpf(float(angle[token, i]))
        hp_c[token, i], hp_s[token, i] = float(mp.cos(a)), float(mp.sin(a))
        true_angle = int(p[token])*freq_real[i]
        real_c[token, i], real_s[token, i] = float(mp.cos(true_angle)), float(mp.sin(true_angle))
        hp_reduced[token, i] = float(a-mp.mpf(float(q[token, i]))*2*mp.pi)
results['reduced_vs_high_precision_same_quotient'] = stats(layout['reduced'], hp_reduced.astype('f4'), active[:, None])
results['cosine_vs_high_precision_same_fp32_angle'] = stats(dc, hp_c.astype('f4'), active[:, None])
results['sine_vs_high_precision_same_fp32_angle'] = stats(ds, hp_s.astype('f4'), active[:, None])
results['current_numpy_cosine_vs_high_precision_same_angle'] = stats(c, hp_c.astype('f4'), active[:, None])
results['current_numpy_sine_vs_high_precision_same_angle'] = stats(s, hp_s.astype('f4'), active[:, None])
results['cosine_vs_unrounded_real_rope'] = stats(dc, real_c.astype('f4'), active[:, None])
results['sine_vs_unrounded_real_rope'] = stats(ds, real_s.astype('f4'), active[:, None])
results['angle_vs_unrounded_real_math'] = stats(angle, (p[:, None].astype('f8')*np.array([float(v) for v in freq_real])[None, :]).astype('f4'), active[:, None])

finite = np.isfinite(y) & np.isfinite(gold)
error = np.zeros(y.shape, 'f8'); error[finite] = np.abs(y[finite].astype('f8')-gold[finite].astype('f8'))
bad = np.argwhere(error > .1)
rows = []
mp_pair_cache = {}
for token, head, col in bad:
    i = int(col % W); k = (int(token), int(head), int(col)); a = float(x[token, head, i]); b = float(x[token, head, W+i])
    key = (int(token), i)
    if key not in mp_pair_cache:
        arg = mp.mpf(float(angle[token, i])); true_arg = int(p[token])*freq_real[i]
        mp_pair_cache[key] = mp.cos(arg), mp.sin(arg), mp.cos(true_arg), mp.sin(true_arg)
    hc, hs, rc, rs = mp_pair_cache[key]
    hp_y = mp.mpf(a)*hc-mp.mpf(b)*hs if col < W else mp.mpf(b)*hc+mp.mpf(a)*hs
    real_y = mp.mpf(a)*rc-mp.mpf(b)*rs if col < W else mp.mpf(b)*rc+mp.mpf(a)*rs
    hp_y_half, real_y_half = np.float16(float(hp_y)), np.float16(float(real_y))
    ref_half = gold[k]; toward = np.float16(np.inf if y[k] > ref_half else -np.inf)
    adjacent = np.nextafter(ref_half, toward, dtype=np.float16)
    midpoint = (float(ref_half)+float(adjacent))/2
    rows.append(dict(token=int(token), position=int(p[token]), head=int(head), col=int(col), frequency_col=i,
        actual_half=float(y[k]), reference_half=float(ref_half), abs_half_error=float(error[k]),
        actual_fp32=float(layout['fp32_y'][k]), reference_fp32=float(reference32[k]),
        fp32_difference=float(layout['fp32_y'][k])-float(reference32[k]),
        half_midpoint=midpoint, reference_distance_to_midpoint=float(reference32[k])-midpoint,
        actual_distance_to_midpoint=float(layout['fp32_y'][k])-midpoint,
        adjacent_half_spacing=abs(float(adjacent)-float(ref_half)),
        reference_exactly_at_midpoint=bool(float(reference32[k]) == midpoint),
        hp_same_angle_y=float(hp_y), hp_same_angle_half=float(hp_y_half),
        hp_same_angle_prefers_actual=bool(hp_y_half == y[k]), hp_same_angle_prefers_reference=bool(hp_y_half == ref_half),
        hp_real_rope_y=float(real_y), hp_real_rope_half=float(real_y_half),
        device_cos=float(dc[token,i]), reference_cos=float(c[token,i]), hp_same_angle_cos=float(hc),
        device_sin=float(ds[token,i]), reference_sin=float(s[token,i]), hp_same_angle_sin=float(hs)))
with (HERE/'fp16_boundary_failures.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
results['half_boundary_summary'] = dict(elements_above_point_one=len(rows),
    exactly_at_reference_fp32_midpoint=sum(v['reference_exactly_at_midpoint'] for v in rows),
    max_fp32_difference_on_bad=float(max(abs(v['fp32_difference']) for v in rows)),
    max_reference_margin_to_midpoint=float(max(abs(v['reference_distance_to_midpoint']) for v in rows)),
    hp_same_angle_prefers_actual=sum(v['hp_same_angle_prefers_actual'] for v in rows),
    hp_same_angle_prefers_reference=sum(v['hp_same_angle_prefers_reference'] for v in rows),
    hp_same_angle_neither=sum(not(v['hp_same_angle_prefers_actual'] or v['hp_same_angle_prefers_reference']) for v in rows),
    hp_oracle='80 decimal digits; exact input half values and exact exported FP32 angle, then real products/addition; comparison is diagnostic, not acceptance.')
results['representative_boundaries'] = sorted(rows, key=lambda v:-v['abs_half_error'])[:8]

# CPU-only stage attribution: conditional products/add already proved above.
# This does not change the executable, reference or validation criteria.
for label, cc, ss in [('reference_cos_device_sin',c,ds),('device_cos_reference_sin',dc,s),('hp_same_angle_float32_trig',hp_c.astype('f4'),hp_s.astype('f4'))]:
    _, _, yy = rotate(x,cc,ss); yy[~active] = x[~active]; hh = yy.astype('f2'); hh[~active] = x[~active]
    results.setdefault('cpu_stage_attribution',{})[label] = half_check(hh,gold)
results['interpretation'] = [
    'All diagnostics use a frozen input and untouched production V9; instrumented final half output must equal saved V9 bit-for-bit.',
    'Position-zero trig/product NaN sentinels mean those operations are intentionally not executed by V9; they are excluded from active-stage comparisons.',
    'High-precision direct inverse power differs from rounded FP32 power followed by reciprocal; mathematical closeness is not proof of acceptance-reference agreement.',
    'A tiny pre-cast error can cross an FP16 midpoint and cause a half-ULP output step much larger than the global 0.1 cap.',
    'ULP distances near zero should be read together with absolute errors; NaN payload identity is checked separately for the original output.',
    'The single cast bit difference is the position-zero NaN payload: V9 copies original half 0x7e00, while recasting the exported NaN FP32 yields 0x7fff. All finite values, infinity signs and position-zero output bits match.',
    'The local FP32 reference uses NumPy transcendental functions, which differ from correctly rounded high-precision trig by at most one ULP on this input. No assumption is made that the inaccessible official reference uses identical libm rounding. Neither reference nor thresholds are changed.'
]
(HERE/'stage_report.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:v for k,v in results.items() if k not in ['representative_boundaries','interpretation']},indent=2))
