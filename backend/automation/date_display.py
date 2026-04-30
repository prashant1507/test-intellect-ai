from __future__ import annotations

from datetime import datetime, timezone

_EN_MONTH = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_dt_display(dt: datetime, *, with_time: bool = True) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone()
    else:
        dt = dt.astimezone()
    dmy = f"{dt.day} {_EN_MONTH[dt.month - 1]} {dt.year}"
    if not with_time:
        return dmy
    return f"{dmy} {dt.strftime('%H:%M:%S')}"
