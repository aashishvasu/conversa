"""Selfcheck: python -m selfchecks.calculator"""

import asyncio
import json
import math

from tools import CALCULATOR_TOOL
from tools.conversa_tool import ToolCall, execute_tool


def run(call_id, arguments):
    return asyncio.run(execute_tool(CALCULATOR_TOOL, ToolCall(call_id, "calculator", arguments)))


def result_of(res):
    return json.loads(res.content)["result"]


# expressions
basic = run("calc-1", {"expression": "2 + 3 * 4"})
assert basic.error is None and result_of(basic) == 14, basic

power = run("calc-2", {"expression": "2 ** 10"})
assert power.error is None and result_of(power) == 1024, power

div_mod = run("calc-3", {"expression": "10 // 3 + 10 % 3"})
assert div_mod.error is None and result_of(div_mod) == 4, div_mod

consts = run("calc-4", {"expression": "pi + e + tau"})
assert consts.error is None and math.isclose(result_of(consts), math.pi + math.e + math.tau), consts

funcs = run("calc-5", {"expression": "sqrt(16) + gcd(12, 18) + factorial(5)"})
assert funcs.error is None and result_of(funcs) == 4.0 + 6 + 120, funcs

# security and bounds
exp_overflow = run("calc-6", {"expression": "2 ** 1001"})
assert exp_overflow.error == "tool_error", exp_overflow

div_zero = run("calc-7", {"expression": "1 / 0"})
assert div_zero.error == "tool_error", div_zero

# factorial bound: 100 fits the result bit budget, 101 is rejected
fact_ok = run("calc-8", {"expression": "factorial(100)"})
assert fact_ok.error is None and result_of(fact_ok) == math.factorial(100), fact_ok
fact_bound = run("calc-9", {"expression": "factorial(101)"})
assert fact_bound.error == "tool_error", fact_bound

bool_rejected = run("calc-10", {"expression": "True + 1"})
assert bool_rejected.error == "tool_error", bool_rejected

code_injection = run("calc-11", {"expression": "__import__('os').system('ls')"})
assert code_injection.error == "tool_error", code_injection

# Field owns the length bound: malformed input is rejected before execution
long_expr = run("calc-12", {"expression": "1 + " * 300 + "1"})
assert long_expr.error == "invalid_arguments", long_expr

empty_expr = run("calc-33", {"expression": ""})
assert empty_expr.error == "invalid_arguments", empty_expr

# the AST node bound still applies within the length limit
node_bound = run("calc-34", {"expression": "1+" * 150 + "1"})
assert node_bound.error == "tool_error", node_bound

# Field owns input finiteness; output overflow stays a runtime tool_error
bool_value = run("calc-13", {"value": True, "from_unit": "m", "to_unit": "km"})
assert bool_value.error == "invalid_arguments", bool_value

nan_value = run("calc-14", {"value": float("nan"), "from_unit": "m", "to_unit": "km"})
assert nan_value.error == "invalid_arguments", nan_value

inf_value = run("calc-15", {"value": float("inf"), "from_unit": "m", "to_unit": "km"})
assert inf_value.error == "invalid_arguments", inf_value

overflow_out = run("calc-16", {"value": 1e308, "from_unit": "m", "to_unit": "nm"})
assert overflow_out.error == "tool_error", overflow_out

empty_unit = run("calc-35", {"value": 1, "from_unit": "", "to_unit": "km"})
assert empty_unit.error == "invalid_arguments", empty_unit

long_unit = run("calc-36", {"value": 1, "from_unit": "m", "to_unit": "x" * 33})
assert long_unit.error == "invalid_arguments", long_unit

# unit conversion
conv_len = run("calc-17", {"value": 100, "from_unit": "cm", "to_unit": "m"})
assert conv_len.error is None and json.loads(conv_len.content)["value"] == 1.0, conv_len

conv_mass = run("calc-18", {"value": 1, "from_unit": "kg", "to_unit": "g"})
assert conv_mass.error is None and json.loads(conv_mass.content)["value"] == 1000.0, conv_mass

conv_dur = run("calc-19", {"value": 2, "from_unit": "h", "to_unit": "min"})
assert conv_dur.error is None and json.loads(conv_dur.content)["value"] == 120.0, conv_dur

# data size: bit vs byte case sensitivity
conv_byte_bit = run("calc-20", {"value": 1, "from_unit": "MB", "to_unit": "Mb"})
assert conv_byte_bit.error is None and json.loads(conv_byte_bit.content)["value"] == 8.0, conv_byte_bit

# data size: SI vs IEC
conv_iec = run("calc-21", {"value": 1, "from_unit": "MiB", "to_unit": "KiB"})
assert conv_iec.error is None and json.loads(conv_iec.content)["value"] == 1024.0, conv_iec

conv_speed = run("calc-22", {"value": 36, "from_unit": "km/h", "to_unit": "m/s"})
assert conv_speed.error is None and math.isclose(json.loads(conv_speed.content)["value"], 10.0), conv_speed

conv_area = run("calc-23", {"value": 1, "from_unit": "ha", "to_unit": "m2"})
assert conv_area.error is None and json.loads(conv_area.content)["value"] == 10000.0, conv_area

# volume: US customary units are explicit; the bare alias is rejected
conv_vol = run("calc-24", {"value": 1, "from_unit": "gal_us", "to_unit": "l"})
assert conv_vol.error is None and math.isclose(json.loads(conv_vol.content)["value"], 3.785411784), conv_vol

ambig_vol = run("calc-25", {"value": 1, "from_unit": "gal", "to_unit": "l"})
assert ambig_vol.error == "tool_error", ambig_vol

conv_press = run("calc-26", {"value": 1, "from_unit": "atm", "to_unit": "Pa"})
assert conv_press.error is None and json.loads(conv_press.content)["value"] == 101325.0, conv_press

conv_nrg = run("calc-27", {"value": 1, "from_unit": "cal", "to_unit": "J"})
assert conv_nrg.error is None and json.loads(conv_nrg.content)["value"] == 4.184, conv_nrg

# affine temperature C/F/K
conv_temp_f = run("calc-28", {"value": 0, "from_unit": "C", "to_unit": "F"})
assert conv_temp_f.error is None and json.loads(conv_temp_f.content)["value"] == 32.0, conv_temp_f

conv_temp_c = run("calc-29", {"value": 212, "from_unit": "F", "to_unit": "C"})
assert conv_temp_c.error is None and math.isclose(json.loads(conv_temp_c.content)["value"], 100.0), conv_temp_c

conv_temp_k = run("calc-30", {"value": 0, "from_unit": "C", "to_unit": "K"})
assert conv_temp_k.error is None and json.loads(conv_temp_k.content)["value"] == 273.15, conv_temp_k

# cross-category conversion rejected
cross = run("calc-31", {"value": 1, "from_unit": "m", "to_unit": "kg"})
assert cross.error == "tool_error", cross

# expression and conversion are mutually exclusive
mix_modes = run("calc-32", {"expression": "1 + 1", "value": 1, "from_unit": "m", "to_unit": "km"})
assert mix_modes.error == "invalid_arguments", mix_modes

print("calculator selfcheck OK")
