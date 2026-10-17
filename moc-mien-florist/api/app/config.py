"""Cấu hình đọc từ biến môi trường (hoặc file api/.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parent.parent
load_dotenv(API_DIR / ".env")

VN_TZ = timezone(timedelta(hours=7))
DEFAULT_MOCK_NOW = "2026-10-16T08:00:00+07:00"


def _parse_mock_now(raw: str | None) -> datetime | None:
    """MOCK_NOW cố định "giờ hiện tại" để dữ liệu seed và kịch bản test luôn tái lập được.

    Đặt MOCK_NOW=off (hoặc chuỗi rỗng) để dùng giờ thật.
    """
    if raw is None:
        raw = DEFAULT_MOCK_NOW
    raw = raw.strip()
    if raw.lower() in ("", "off", "real", "none", "false"):
        return None
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=VN_TZ)


@dataclass(frozen=True)
class Settings:
    db_path: Path
    policy_path: Path
    mock_now: datetime | None
    api_key: str | None
    staff_key: str


def _path(env: str, default: Path) -> Path:
    """Đường dẫn tương đối trong biến môi trường được tính từ thư mục api/."""
    raw = os.getenv(env)
    if not raw:
        return default
    p = Path(raw)
    return p if p.is_absolute() else (API_DIR / p).resolve()


def load_settings() -> Settings:
    return Settings(
        db_path=_path("DB_PATH", API_DIR / "data" / "moc_mien.db"),
        policy_path=_path("POLICY_PATH", API_DIR.parent / "policy.yaml"),
        mock_now=_parse_mock_now(os.getenv("MOCK_NOW")),
        api_key=os.getenv("API_KEY") or None,
        staff_key=os.getenv("STAFF_KEY", "mocmien-staff-2026"),
    )


settings = load_settings()
