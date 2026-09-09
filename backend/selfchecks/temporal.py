"""Selfcheck: python -m selfchecks.temporal"""

import asyncio
import json

from tools import DATETIME_TOOL
from tools.conversa_tool import ToolCall, execute_tool


def run(call_id, arguments):
    return asyncio.run(execute_tool(DATETIME_TOOL, ToolCall(call_id, "datetime", arguments)))


# now
res_now = run("dt-1", {"action": "now", "timezone": "UTC"})
assert res_now.error is None, res_now
data_now = json.loads(res_now.content)
for field in ("iso", "date", "time", "day_name", "timezone", "utc_offset", "timestamp"):
    assert field in data_now, (field, data_now)
assert data_now["timezone"] == "UTC" and data_now["utc_offset"] == "+00:00", data_now

bad_tz = run("dt-2", {"action": "now", "timezone": "Invalid/Timezone"})
assert bad_tz.error == "invalid_arguments", bad_tz

# Field owns string bounds and delta finiteness; malformed input fails validation
empty_tz = run("dt-21", {"action": "now", "timezone": ""})
assert empty_tz.error == "invalid_arguments", empty_tz

long_tz = run("dt-22", {"action": "now", "timezone": "x" * 65})
assert long_tz.error == "invalid_arguments", long_tz

long_dt = run("dt-23", {"action": "add", "datetime": "x" * 65, "days": 1})
assert long_dt.error == "invalid_arguments", long_dt

inf_delta = run("dt-24", {"action": "add", "datetime": "2026-04-15T10:00:00Z", "weeks": float("inf")})
assert inf_delta.error == "invalid_arguments", inf_delta

# add elapsed
add_elapsed = run("dt-3", {"action": "add", "datetime": "2026-04-15T12:00:00Z", "hours": 2, "seconds": 30, "mode": "elapsed", "timezone": "UTC"})
assert add_elapsed.error is None, add_elapsed
data_elapsed = json.loads(add_elapsed.content)
assert data_elapsed["iso"] == "2026-04-15T14:00:30+00:00", data_elapsed
assert data_elapsed["mode"] == "elapsed"

# 24 elapsed hours across the spring-forward transition land at 11:00 EDT
add_dst_elapsed = run("dt-4", {"action": "add", "datetime": "2024-03-09T10:00:00", "days": 1, "mode": "elapsed", "timezone": "America/New_York"})
assert add_dst_elapsed.error is None, add_dst_elapsed
assert json.loads(add_dst_elapsed.content)["time"].startswith("11:00:00"), add_dst_elapsed.content

# calendar addition preserves wall time
add_dst_cal = run("dt-5", {"action": "add", "datetime": "2024-03-09T10:00:00", "days": 1, "mode": "calendar", "timezone": "America/New_York"})
assert add_dst_cal.error is None, add_dst_cal
assert json.loads(add_dst_cal.content)["time"].startswith("10:00:00"), add_dst_cal.content

# month-end clamping
clamp_leap = run("dt-6", {"action": "add", "datetime": "2024-01-31T10:00:00Z", "months": 1})
assert clamp_leap.error is None and json.loads(clamp_leap.content)["date"] == "2024-02-29", clamp_leap

clamp_nonleap = run("dt-7", {"action": "add", "datetime": "2023-01-31T10:00:00Z", "months": 1})
assert clamp_nonleap.error is None and json.loads(clamp_nonleap.content)["date"] == "2023-02-28", clamp_nonleap

# year clamping: Feb 29 + 1 year -> Feb 28
clamp_year = run("dt-8", {"action": "add", "datetime": "2024-02-29T10:00:00Z", "years": 1})
assert clamp_year.error is None and json.loads(clamp_year.content)["date"] == "2025-02-28", clamp_year

# mode mixing and fractional calendar units are rejected at validation
mix_err = run("dt-9", {"action": "add", "datetime": "2026-04-15T10:00:00Z", "months": 1, "hours": 2})
assert mix_err.error == "invalid_arguments", mix_err

frac_cal = run("dt-10", {"action": "add", "datetime": "2026-04-15T10:00:00Z", "days": 1.5, "mode": "calendar"})
assert frac_cal.error == "invalid_arguments", frac_cal

# runtime domain failures surface as structured tool_error, not raw exceptions
overflow = run("dt-11", {"action": "add", "datetime": "9999-01-01T00:00:00Z", "years": 1})
assert overflow.error == "tool_error", overflow

bad_iso = run("dt-19", {"action": "add", "datetime": "not-a-date", "hours": 1})
assert bad_iso.error == "tool_error", bad_iso

cal_overflow = run("dt-20", {"action": "add", "datetime": "2026-04-15T10:00:00Z", "weeks": 1e300, "mode": "calendar"})
assert cal_overflow.error == "tool_error", cal_overflow

# difference
diff = run("dt-12", {"action": "difference", "datetime": "2026-04-15T10:00:00Z", "target": "2026-04-16T12:30:15Z"})
assert diff.error is None, diff
diff_data = json.loads(diff.content)
assert diff_data["sign"] == 1
assert diff_data["days"] == 1 and diff_data["hours"] == 2 and diff_data["minutes"] == 30
assert diff_data["remaining_seconds"] == 15.0
assert diff_data["seconds"] == 86400 + 7200 + 1800 + 15, diff_data

diff_neg = run("dt-13", {"action": "difference", "datetime": "2026-04-16T12:00:00Z", "target": "2026-04-15T12:00:00Z"})
assert diff_neg.error is None, diff_neg
diff_neg_data = json.loads(diff_neg.content)
assert diff_neg_data["sign"] == -1 and diff_neg_data["seconds"] == -86400, diff_neg_data

# naive input is interpreted in the requested zone
naive_add = run("dt-14", {"action": "add", "datetime": "2026-04-15T10:00:00", "hours": 1, "timezone": "America/New_York"})
assert naive_add.error is None, naive_add
assert json.loads(naive_add.content)["iso"].endswith("-04:00"), naive_add.content

# DST gap: 02:30 on 2024-03-10 does not exist; resolution advances to 03:30 EDT
gap_resolve = run("dt-15", {"action": "add", "datetime": "2024-03-10T02:30:00", "seconds": 0, "timezone": "America/New_York"})
assert gap_resolve.error is None, gap_resolve
assert json.loads(gap_resolve.content)["iso"] == "2024-03-10T03:30:00-04:00", gap_resolve.content

# DST fold: 01:30 on 2024-11-03 occurs twice; fold=0 keeps the earlier (EDT) offset
fold_resolve = run("dt-16", {"action": "add", "datetime": "2024-11-03T01:30:00", "seconds": 0, "timezone": "America/New_York"})
assert fold_resolve.error is None, fold_resolve
assert json.loads(fold_resolve.content)["iso"] == "2024-11-03T01:30:00-04:00", fold_resolve.content

# calendar add onto a gap day advances the nonexistent wall time
cal_gap = run("dt-17", {"action": "add", "datetime": "2024-03-09T02:30:00", "days": 1, "mode": "calendar", "timezone": "America/New_York"})
assert cal_gap.error is None, cal_gap
assert json.loads(cal_gap.content)["iso"] == "2024-03-10T03:30:00-04:00", cal_gap.content

# calendar add onto a fold day keeps the earlier offset
cal_fold = run("dt-18", {"action": "add", "datetime": "2024-11-02T01:30:00", "days": 1, "mode": "calendar", "timezone": "America/New_York"})
assert cal_fold.error is None, cal_fold
assert json.loads(cal_fold.content)["iso"] == "2024-11-03T01:30:00-04:00", cal_fold.content

print("temporal selfcheck OK")
