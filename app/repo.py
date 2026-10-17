"""Truy cập dữ liệu: các câu SQL dùng lại nhiều nơi."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .db import many, one
from .errors import ApiError, not_found_or_mismatch
from .utils import iso, normalize_phone

CAPACITY_STATUSES = ("pending", "confirmed", "arranging", "delivering", "delivered", "failed_delivery")


# ----------------------------------------------------------------- mã tự tăng
def next_code(conn: sqlite3.Connection, table: str, prefix: str, start: int) -> str:
    row = one(conn, f"SELECT code FROM {table} WHERE code LIKE ? ORDER BY code DESC LIMIT 1", (prefix + "%",))
    number = int(row["code"][len(prefix):]) + 1 if row else start
    return f"{prefix}{number}"


# ----------------------------------------------------------------- danh mục
def list_branches(conn) -> list[dict]:
    return many(conn, "SELECT * FROM branches ORDER BY id")


def get_branch(conn, branch_id: str) -> dict | None:
    return one(conn, "SELECT * FROM branches WHERE id = ?", (branch_id.upper(),))


def list_zones(conn) -> list[dict]:
    return many(conn, "SELECT * FROM delivery_zones ORDER BY id")


def get_zone(conn, zone_id: str | None) -> dict | None:
    if not zone_id:
        return None
    return one(conn, "SELECT * FROM delivery_zones WHERE id = ?", (zone_id.upper(),))


def slots_by_code(conn) -> dict[str, dict]:
    return {s["code"]: s for s in many(conn, "SELECT * FROM delivery_slots ORDER BY code")}


def get_product(conn, sku: str) -> dict | None:
    return one(conn, "SELECT * FROM products WHERE sku = ?", (sku.upper(),))


def stock(conn, sku: str, branch_id: str) -> int:
    row = one(conn, "SELECT quantity FROM inventory WHERE sku = ? AND branch_id = ?", (sku, branch_id))
    return row["quantity"] if row else 0


def stock_by_branch(conn, sku: str) -> dict[str, int]:
    return {r["branch_id"]: r["quantity"] for r in many(conn, "SELECT branch_id, quantity FROM inventory WHERE sku = ?", (sku,))}


def adjust_stock(conn, sku: str, branch_id: str, delta: int, now: datetime) -> None:
    conn.execute(
        "UPDATE inventory SET quantity = MAX(quantity + ?, 0), updated_at = ? WHERE sku = ? AND branch_id = ?",
        (delta, iso(now), sku, branch_id),
    )


def slot_load(conn, branch_id: str, delivery_date: str, slot_code: str, exclude_code: str | None = None) -> int:
    placeholders = ",".join("?" * len(CAPACITY_STATUSES))
    row = one(
        conn,
        f"SELECT COUNT(*) AS n FROM orders WHERE branch_id = ? AND delivery_date = ? AND slot_code = ? "
        f"AND status IN ({placeholders}) AND code != ?",
        (branch_id, delivery_date, slot_code, *CAPACITY_STATUSES, exclude_code or ""),
    )
    return row["n"]


# ----------------------------------------------------------------- khách hàng
def get_customer(conn, customer_id: str) -> dict | None:
    return one(conn, "SELECT * FROM customers WHERE id = ?", (customer_id,))


def get_customer_by_phone(conn, phone: str) -> dict | None:
    return one(conn, "SELECT * FROM customers WHERE phone = ?", (phone,))


def require_phone(raw: str) -> str:
    phone = normalize_phone(raw)
    if not phone:
        raise ApiError(422, "INVALID_PHONE", "Số điện thoại không hợp lệ (cần 10 số, bắt đầu bằng 0).")
    return phone


def upsert_customer(conn, full_name: str, phone: str, email: str | None, now: datetime) -> dict:
    existing = get_customer_by_phone(conn, phone)
    if existing:
        if email and not existing["email"]:
            conn.execute("UPDATE customers SET email = ? WHERE id = ?", (email, existing["id"]))
            existing["email"] = email
        return existing
    row = one(conn, "SELECT id FROM customers ORDER BY id DESC LIMIT 1")
    new_id = f"KH{int(row['id'][2:]) + 1:04d}" if row else "KH0001"
    conn.execute(
        "INSERT INTO customers (id, full_name, phone, email, tier, points, total_spent_12m, created_at) "
        "VALUES (?, ?, ?, ?, 'member', 0, 0, ?)",
        (new_id, full_name.strip(), phone, email, iso(now)),
    )
    return get_customer(conn, new_id)


def customer_order_count(conn, customer_id: str) -> int:
    return one(
        conn,
        "SELECT COUNT(*) AS n FROM orders WHERE customer_id = ? AND status NOT IN ('cancelled')",
        (customer_id,),
    )["n"]


# ----------------------------------------------------------------- đơn hàng
def get_order(conn, code: str) -> dict | None:
    return one(conn, "SELECT * FROM orders WHERE code = ?", (code.strip().upper(),))


def find_order_for_phone(conn, code: str, raw_phone: str) -> dict:
    phone = normalize_phone(raw_phone)
    order = get_order(conn, code)
    if not order or not phone:
        raise not_found_or_mismatch("order")
    customer = get_customer(conn, order["customer_id"])
    if customer["phone"] != phone:
        raise not_found_or_mismatch("order")
    return order


def order_items(conn, code: str) -> list[dict]:
    return many(
        conn,
        "SELECT oi.sku, oi.product_name, oi.quantity, oi.unit_price, oi.line_total, p.category, "
        "p.lead_time_hours, p.freshness_days FROM order_items oi JOIN products p ON p.sku = oi.sku "
        "WHERE oi.order_code = ? ORDER BY oi.id",
        (code,),
    )


def order_events(conn, code: str) -> list[dict]:
    return many(
        conn,
        "SELECT event_type, from_status, to_status, detail, actor, created_at FROM order_events "
        "WHERE order_code = ? ORDER BY created_at, id",
        (code,),
    )


def log_order_event(conn, code: str, event_type: str, now: datetime, *, from_status=None, to_status=None,
                    detail: str | None = None, actor: str = "agent") -> None:
    conn.execute(
        "INSERT INTO order_events (order_code, event_type, from_status, to_status, detail, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, event_type, from_status, to_status, detail, actor, iso(now)),
    )


# ----------------------------------------------------------------- yêu cầu dịch vụ
def insert_request(conn, *, type: str, customer_id: str | None, ref_type: str | None, ref_code: str | None,
                   reason_code: str | None, description: str | None, amount: int | None, payload: dict | None,
                   status: str, approval_rules: list[str], created_by: str, now: datetime,
                   issued_code: str | None = None, resolution_note: str | None = None) -> dict:
    code = next_code(conn, "service_requests", "YC", 10001)
    conn.execute(
        "INSERT INTO service_requests (code, type, customer_id, ref_type, ref_code, reason_code, description, amount, "
        "payload, status, requires_approval, approval_rules, resolution_note, issued_code, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, type, customer_id, ref_type, ref_code, reason_code, description, amount,
         json.dumps(payload, ensure_ascii=False) if payload else None, status, 1 if approval_rules else 0,
         json.dumps(approval_rules) if approval_rules else None, resolution_note, issued_code, created_by, iso(now)),
    )
    return get_request(conn, code)


def get_request(conn, code: str) -> dict | None:
    return one(conn, "SELECT * FROM service_requests WHERE code = ?", (code.strip().upper(),))


def requests_for(conn, ref_type: str, ref_code: str) -> list[dict]:
    return many(
        conn,
        "SELECT * FROM service_requests WHERE ref_type = ? AND ref_code = ? ORDER BY created_at, code",
        (ref_type, ref_code),
    )


def open_refund_total(conn, order_code: str) -> int:
    """Tổng tiền hoàn đã ghi nhận nhưng chưa chuyển xong (chờ duyệt / đã duyệt)."""
    row = one(
        conn,
        "SELECT COALESCE(SUM(amount), 0) AS s FROM service_requests WHERE ref_type = 'order' AND ref_code = ? "
        "AND type IN ('refund', 'cancellation') AND status IN ('pending_approval', 'approved') AND amount > 0",
        (order_code,),
    )
    return row["s"]


def goodwill_codes_since(conn, customer_id: str, since_iso: str) -> int:
    return one(
        conn,
        "SELECT COUNT(*) AS n FROM discount_codes WHERE kind = 'goodwill' AND customer_id = ? AND created_at >= ?",
        (customer_id, since_iso),
    )["n"]


# ----------------------------------------------------------------- tư vấn & gói định kỳ
def find_consultation_for_phone(conn, code: str, raw_phone: str) -> dict:
    phone = normalize_phone(raw_phone)
    c = one(conn, "SELECT * FROM consultations WHERE code = ?", (code.strip().upper(),))
    if not c or not phone or get_customer(conn, c["customer_id"])["phone"] != phone:
        raise not_found_or_mismatch("consultation")
    return c


def consultation_load(conn, d: str, time_str: str, exclude_code: str | None = None) -> int:
    return one(
        conn,
        "SELECT COUNT(*) AS n FROM consultations WHERE appointment_date = ? AND appointment_time = ? "
        "AND status = 'scheduled' AND code != ?",
        (d, time_str, exclude_code or ""),
    )["n"]


def get_plan(conn, plan_id: str) -> dict | None:
    return one(conn, "SELECT * FROM subscription_plans WHERE id = ?", (plan_id.upper(),))


def find_subscription_for_phone(conn, code: str, raw_phone: str) -> dict:
    phone = normalize_phone(raw_phone)
    s = one(conn, "SELECT * FROM subscriptions WHERE code = ?", (code.strip().upper(),))
    if not s or not phone or get_customer(conn, s["customer_id"])["phone"] != phone:
        raise not_found_or_mismatch("subscription")
    return s
