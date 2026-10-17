"""Read-only inspection of the installed CPU oracle and CANN sqrt wrapper."""
import hashlib
import json
import platform
import subprocess
import urllib.request
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];BUILD=ROOT/'build/rope_v9_trig_internal'
binary=next((Path(np.__file__).parent/'_core').glob('_multiarray_umath*.so'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
symbols=subprocess.check_output(['nm','-C',str(binary)],text=True)
matches=[line for line in symbols.splitlines() if 'simd_sincos_f32(' in line]
start=min(int(line.split()[0],16) for line in matches)
end=int(next(line.split()[0] for line in symbols.splitlines() if line.endswith(' t FLOAT_cos')),16)
assembly=subprocess.check_output(['objdump','-d','-C',f'--start-address={start}',f'--stop-address={end}',str(binary)],text=True)
(HERE/'numpy_host_asm.txt').write_text(assembly)
assert 'fmla' in assembly
constants=subprocess.check_output(['objdump','-s','--start-address=0x3aaeb0','--stop-address=0x3aaef0',str(binary)],text=True)
(HERE/'numpy_host_quadrant_constants.txt').write_text(constants)
assert '0000404b' in constants and '83f9223f' in constants and '000040cb' in constants
sdk=Path('/usr/local/Ascend/cann-9.0.0/aarch64-linux/asc/impl/basic_api/dav_c220/kernel_operator_vec_unary_impl.h')
assert 'vsqrt(dst, src' in sdk.read_text()
source=BUILD/'numpy_2_2_6_loops_trigonometric.dispatch.cpp'
if not source.exists():
    source.write_bytes(urllib.request.urlopen('https://raw.githubusercontent.com/numpy/numpy/v2.2.6/numpy/_core/src/umath/loops_trigonometric.dispatch.cpp').read())
assert sha(source)=='fb1ca5adef328d6ac9fa645f1642bcefea86188b385f4984eb8d8338aa1cebac'
report=dict(numpy_version=np.__version__,python=platform.python_version(),machine=platform.machine(),glibc=platform.libc_ver(),
    binary_sha256=sha(binary),binary_path=str(binary),dispatch={k:{'ff':v['ff']} for k,v in np.lib.introspect.opt_func_info(func_name='^(sin|cos)$').items()},
    relevant_local_symbols=matches,host_asm='benchmarks/diagnostics/rope_v9_trig_internal/numpy_host_asm.txt',
    decoded_host_evidence=dict(quadrant_multiply_add='0x2c3b98: fmla v6.4s, v4.4s, v0.4s',
        quadrant_subtract_magic='0x2c3ba4: fadd v6.4s, v6.4s, v4.4s',
        initial_accumulator=dict(rodata='0x3aaeb0',bits='0x4b400000',value=12582912.),
        scale=dict(rodata='0x3aaec0',bits='0x3f22f983',value=float(np.float32(float.fromhex('0x1.45f306p-1')))),
        subtract_constant=dict(rodata='0x3aaed0',bits='0xcb400000',value=-12582912.),
        conclusion='The installed AArch64 NumPy binary contracts the quadrant multiply/add into FMLA before subtracting the magic constant. The exact CPU fmaf model reproduces all active reference trig values on the frozen input.'),
    pinned_upstream_source=dict(url='https://raw.githubusercontent.com/numpy/numpy/v2.2.6/numpy/_core/src/umath/loops_trigonometric.dispatch.cpp',sha256=sha(source),
        use='Numerical model reference. The installed binary is separately inspected; no assertion is made about the hidden platform version/compiler/CPU.',
        scalar_fallback_limits=dict(cosine=71476.0625,sine=117435.9921875)),
    sqrt_sdk_header=dict(path=str(sdk),sha256=sha(sdk),source_lines=[98,351],intrinsic='vsqrt'),
    limitations=['Addresses/constants bind to the recorded binary; inspect a new binary before reusing address-based extraction.',
        'Host AArch64 instructions are decoded here. The existing HiIPU disassembler limitation for Device remains unchanged.',
        'CPU libm fmaf is a mathematical diagnostic primitive; it is not invoked by the competition Host or presumed available on Device.'])
(HERE/'reference_runtime.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['numpy_version','binary_sha256','dispatch']},indent=2))
