"""Lịch giao của gói hoa định kỳ (hàm thuần, dùng chung với generate_seed)."""
from __future__ import annotations

from datetime import date, timedelta

from .lunar import altar_delivery_dates

STEP_DAYS = {"weekly": 7, "biweekly": 14}


def delivery_schedule(frequency: str, on_or_after: date, weekday: int | None, count: int) -> list[date]:
    """`count` ngày giao kể từ `on_or_after` (tính cả ngày đó nếu khớp lịch)."""
    if count <= 0:
        return []
    if frequency == "lunar_1_15":
        return altar_delivery_dates(on_or_after - timedelta(days=1), count)
    if weekday is None:
        raise ValueError("Gói giao theo tuần cần delivery_weekday")
    first = on_or_after
    while first.weekday() != weekday:
        first += timedelta(days=1)
    step = STEP_DAYS[frequency]
    return [first + timedelta(days=step * i) for i in range(count)]
