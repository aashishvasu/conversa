"""Model-callable datetime operations: current time, date math, and differences."""

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from .conversa_tool import ConversaTool, ToolArguments, ToolFailed, ToolOutput


class DatetimeArguments(ToolArguments):
    action: Literal["now", "add", "difference"] = "now"
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    datetime: str | None = Field(default=None, max_length=64)
    target: str | None = Field(default=None, max_length=64)
    mode: Literal["elapsed", "calendar"] | None = None
    years: int | None = None
    months: int | None = None
    weeks: float | None = Field(default=None, allow_inf_nan=False)
    days: float | None = Field(default=None, allow_inf_nan=False)
    hours: float | None = Field(default=None, allow_inf_nan=False)
    minutes: float | None = Field(default=None, allow_inf_nan=False)
    seconds: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "DatetimeArguments":
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown or invalid timezone: {self.timezone}") from error

        if self.action == "now":
            deltas = (self.datetime, self.target, self.mode, self.years, self.months, self.weeks, self.days, self.hours, self.minutes, self.seconds)
            if any(value is not None for value in deltas):
                raise ValueError("action 'now' does not accept datetime, target, mode, or delta units")

        elif self.action == "add":
            if self.datetime is None:
                raise ValueError("action 'add' requires 'datetime'")
            if self.target is not None:
                raise ValueError("action 'add' does not accept 'target'")

            elapsed_units = self.seconds is not None or self.minutes is not None or self.hours is not None
            calendar_units = self.years is not None or self.months is not None

            if elapsed_units and calendar_units:
                raise ValueError("cannot mix elapsed units (seconds/minutes/hours) and calendar units (years/months)")

            if self.mode == "elapsed" and calendar_units:
                raise ValueError("calendar units (years/months) are not allowed in elapsed mode")
            if self.mode == "calendar" and elapsed_units:
                raise ValueError("elapsed units (seconds/minutes/hours) are not allowed in calendar mode")

            all_units = (self.years, self.months, self.weeks, self.days, self.hours, self.minutes, self.seconds)
            if all(value is None for value in all_units):
                raise ValueError("action 'add' requires at least one delta unit")

            effective_mode = self.mode or ("calendar" if calendar_units else "elapsed")
            if effective_mode == "calendar":
                if self.days is not None and not float(self.days).is_integer():
                    raise ValueError("calendar days must be an integer")
                if self.weeks is not None and not float(self.weeks).is_integer():
                    raise ValueError("calendar weeks must be an integer")

        elif self.action == "difference":
            if self.datetime is None or self.target is None:
                raise ValueError("action 'difference' requires both 'datetime' and 'target'")
            deltas = (self.mode, self.years, self.months, self.weeks, self.days, self.hours, self.minutes, self.seconds)
            if any(value is not None for value in deltas):
                raise ValueError("action 'difference' does not accept delta units or mode")

        return self


def _resolve_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Advance DST gaps and choose the earlier offset for repeated wall times."""
    if dt.tzinfo is not None:
        return dt.astimezone(tz)
    fold0 = dt.replace(fold=0, tzinfo=tz)
    round_trip = fold0.astimezone(timezone.utc).astimezone(tz)
    if round_trip.replace(tzinfo=None) != dt:
        return round_trip
    return fold0


def _parse_iso(value: str, tz: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise ValueError(f"invalid ISO-8601 datetime: '{value}'") from error
    resolved = _resolve_local(parsed, tz)
    if not (1 <= resolved.year <= 9999):
        raise ValueError(f"year {resolved.year} is out of bounds (1..9999)")
    return resolved


def _format_offset(dt: datetime) -> str:
    offset = dt.utcoffset()
    if offset is None:
        return "+00:00"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    abs_seconds = abs(total_seconds)
    hours, minutes = divmod(abs_seconds // 60, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _datetime_payload(dt: datetime, tz_name: str) -> dict[str, object]:
    return {
        "iso": dt.isoformat(),
        "date": dt.date().isoformat(),
        "time": dt.time().isoformat(),
        "day_name": dt.strftime("%A"),
        "timezone": tz_name,
        "utc_offset": _format_offset(dt),
        "timestamp": dt.timestamp(),
    }


async def _run_datetime(arguments: DatetimeArguments) -> ToolOutput:
    tz = ZoneInfo(arguments.timezone)

    if arguments.action == "now":
        current = datetime.now(tz)
        payload = _datetime_payload(current, arguments.timezone)
        return ToolOutput(payload, {"action": "now", "timezone": arguments.timezone})

    if arguments.action == "add":
        base_dt = _parse_iso(arguments.datetime, tz)
        effective_mode = arguments.mode or ("calendar" if (arguments.years is not None or arguments.months is not None) else "elapsed")

        if effective_mode == "elapsed":
            total_seconds = (
                (arguments.seconds or 0.0)
                + (arguments.minutes or 0.0) * 60.0
                + (arguments.hours or 0.0) * 3600.0
                + (arguments.days or 0.0) * 86400.0
                + (arguments.weeks or 0.0) * 604800.0
            )
            base_utc = base_dt.astimezone(timezone.utc)
            try:
                result_utc = base_utc + timedelta(seconds=total_seconds)
            except OverflowError as error:
                raise ValueError("datetime delta out of bounds") from error
            if not (1 <= result_utc.year <= 9999):
                raise ValueError(f"resulting year {result_utc.year} is out of bounds (1..9999)")
            result_dt = result_utc.astimezone(tz)
        else:
            orig_time = base_dt.time()
            years = arguments.years or 0
            months = arguments.months or 0
            total_months = base_dt.year * 12 + (base_dt.month - 1) + months + years * 12
            target_year = total_months // 12
            target_month = (total_months % 12) + 1
            if not (1 <= target_year <= 9999):
                raise ValueError(f"resulting year {target_year} is out of bounds (1..9999)")
            max_days = calendar.monthrange(target_year, target_month)[1]
            target_day = min(base_dt.day, max_days)
            target_date = date(target_year, target_month, target_day)

            extra_days = int(arguments.days or 0) + int(arguments.weeks or 0) * 7
            if extra_days:
                try:
                    target_date += timedelta(days=extra_days)
                except OverflowError as error:
                    raise ValueError("datetime delta out of bounds") from error
                if not (1 <= target_date.year <= 9999):
                    raise ValueError(f"resulting year {target_date.year} is out of bounds (1..9999)")

            # A calendar result preserves wall time except where the target zone skipped that time.
            result_dt = _resolve_local(datetime.combine(target_date, orig_time), tz)

        if not (1 <= result_dt.year <= 9999):
            raise ValueError(f"resulting year {result_dt.year} is out of bounds (1..9999)")

        payload = _datetime_payload(result_dt, arguments.timezone)
        payload["mode"] = effective_mode
        return ToolOutput(payload, {"action": "add", "mode": effective_mode, "timezone": arguments.timezone})

    start_dt = _parse_iso(arguments.datetime, tz)
    target_dt = _parse_iso(arguments.target, tz)
    diff_seconds = (target_dt.astimezone(timezone.utc) - start_dt.astimezone(timezone.utc)).total_seconds()
    sign = 1 if diff_seconds > 0 else (-1 if diff_seconds < 0 else 0)
    abs_seconds = abs(diff_seconds)
    days = int(abs_seconds // 86400)
    rem_after_days = abs_seconds % 86400
    hours = int(rem_after_days // 3600)
    rem_after_hours = rem_after_days % 3600
    minutes = int(rem_after_hours // 60)
    seconds = round(rem_after_hours % 60, 6)

    payload = {
        "seconds": diff_seconds,
        "sign": sign,
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "remaining_seconds": seconds,
        "absolute_seconds": abs_seconds,
    }
    return ToolOutput(payload, {"action": "difference", "seconds": diff_seconds, "sign": sign})


async def execute_datetime(arguments: DatetimeArguments) -> ToolOutput:
    try:
        return await _run_datetime(arguments)
    except (ValueError, OverflowError) as error:
        raise ToolFailed(str(error) or "datetime operation failed") from error


DATETIME_TOOL = ConversaTool(
    name="datetime",
    description="Current date and time in IANA timezones, date math (add elapsed or calendar units), and time differences between ISO-8601 timestamps.",
    arguments=DatetimeArguments,
    execute=execute_datetime,
    artifact_fresh_for=None,
)
