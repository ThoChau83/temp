"""Tiện ích thời gian, số điện thoại, định dạng tiền."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .config import VN_TZ, settings

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
_PHONE_RE = re.compile(r"^0\d{9}$")


def now() -> datetime:
    if settings.mock_now is not None:
        return settings.mock_now
    return datetime.now(VN_TZ).replace(microsecond=0)


def today() -> date:
    return now().date()


def iso(dt: datetime) -> str:
    return dt.astimezone(VN_TZ).isoformat(timespec="seconds")


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=VN_TZ)


def at(d: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=VN_TZ)


def hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def normalize_phone(raw: str | None) -> str | None:
    """'0912 345 678', '+84912345678', '84912345678' -> '0912345678'. Sai định dạng -> None."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if _PHONE_RE.match(digits) else None


def mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:4]} xxx {phone[-3:]}"


def vnd(amount: int | None) -> str:
    if amount is None:
        return "-"
    return f"{int(amount):,}".replace(",", ".") + "đ"


def date_vi(d: date) -> str:
    return f"{WEEKDAYS_VI[d.weekday()]}, {d:%d/%m/%Y}"


def is_peak_day(d: date, policy: dict) -> bool:
    return d.strftime("%m-%d") in policy["ordering"]["peak_days"]


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)
