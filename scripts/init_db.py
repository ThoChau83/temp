"""Tạo lại database SQLite từ sql/schema.sql + sql/seed.sql.

    python scripts/init_db.py            # ghi vào data/moc_mien.db (hoặc DB_PATH)
    python scripts/init_db.py --db x.db  # ghi vào file khác
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR))

from app.config import settings  # noqa: E402


def init_db(db_path: Path) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        for name in ("schema.sql", "seed.sql"):
            conn.executescript((API_DIR / "sql" / name).read_text(encoding="utf-8"))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                             "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"Vi phạm khoá ngoại: {bad[:5]}")
    finally:
        conn.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=settings.db_path)
    args = parser.parse_args()
    counts = init_db(args.db)
    print(f"Đã tạo {args.db}")
    for table, n in counts.items():
        print(f"  {table:<20} {n:>5}")
