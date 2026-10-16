"""Generate universal exp2 coefficients; no RoPE outputs or frequencies."""
import json
from pathlib import Path
import mpmath as mp
mp.mp.dps=80
coefficients,error=mp.chebyfit(lambda x:mp.power(2,x),[-mp.mpf('.5'),mp.mpf('.5')],8,error=True)
integers=[int(mp.nint(c*(1<<31))) for c in coefficients]
# Chebyshev interpolation remainder on an interval of length one.
interpolation_bound=mp.log(2)**8*mp.sqrt(2)/(mp.factorial(8)*(1<<15))
# log truncation/product: <2 Q31 units; coefficient rounding: <1;
# Horner truncation: <2; normalization: at most x2. Original protected
# exp2 approximation and integer guard-bit error are allowed <0.5 units.
bound=2*(2*mp.log(2)*mp.sqrt(2)+1+2+interpolation_bound*(1<<31))+mp.mpf('.5')
assert integers==[32864,332210,2863343,20654553,119194167,515882507,1488522236,2147483648]
assert bound<16
report=dict(domain=[-.5,.5],coefficients_q31_descending=integers,interpolation_bound_q31=float(interpolation_bound*(1<<31)),combined_normalized_q31_bound=float(bound),selected_guard_units=16)
Path('build/round8_coefficient_bounds.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
