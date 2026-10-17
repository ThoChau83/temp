"""Tính tiền đơn hàng — hàm thuần, dùng chung cho API và tools/generate_seed.py.

Không import config/DB ở đây để script sinh seed dùng được độc lập.
"""
from __future__ import annotations

from datetime import date


def round_down(amount: float, step: int = 1000) -> int:
    return int(amount // step) * step


def _vnd(amount: int) -> str:
    return f"{int(amount):,}".replace(",", ".") + "đ"


def _dmy(iso_date: str) -> str:
    y, m, d = iso_date.split("-")
    return f"{d}/{m}/{y}"


def shipping_fee(zone: dict | None, subtotal: int, tier: str, policy: dict) -> int:
    """Phí ship theo khu vực; miễn phí khi đạt ngưỡng hoặc khách VIP ở Z1–Z2. Nhận tại cửa hàng = 0."""
    if zone is None:
        return 0
    tier_cfg = policy["loyalty"]["tiers"].get(tier, {})
    if zone["id"] in tier_cfg.get("free_shipping_zones", []):
        return 0
    free_from = zone.get("free_ship_min_order")
    if free_from is not None and subtotal >= free_from:
        return 0
    return int(zone["fee"])


def tier_discount(subtotal: int, tier: str, policy: dict) -> int:
    percent = policy["loyalty"]["tiers"].get(tier, {}).get("discount_percent", 0)
    return round_down(subtotal * percent / 100)


def evaluate_code(
    code: dict,
    lines: list[dict],
    subtotal: int,
    order_date: date,
    customer: dict | None,
    usage: dict,
) -> tuple[int, str | None, str | None]:
    """Kiểm tra một mã giảm giá.

    lines: [{"category": ..., "line_total": ...}]
    usage: {"customer_used": số lần khách đã dùng mã, "customer_prior_orders": số đơn trước đó}
    Trả về (số tiền giảm, mã lỗi, thông báo lỗi).
    """
    if not code.get("is_active", 1):
        return 0, "CODE_INACTIVE", "Mã đã ngừng áp dụng."
    od = order_date.isoformat()
    if od < code["valid_from"]:
        return 0, "CODE_NOT_STARTED", f"Mã chỉ áp dụng từ ngày {_dmy(code['valid_from'])}."
    if od > code["valid_to"]:
        return 0, "CODE_EXPIRED", f"Mã đã hết hạn từ sau ngày {_dmy(code['valid_to'])}."
    if code.get("usage_limit") is not None and code.get("used_count", 0) >= code["usage_limit"]:
        return 0, "CODE_USED_UP", "Mã đã hết lượt sử dụng."
    if code.get("customer_id") and (customer is None or customer.get("id") != code["customer_id"]):
        return 0, "CODE_NOT_FOR_CUSTOMER", "Mã này được cấp riêng cho một khách hàng khác."
    if code.get("per_customer_limit") and usage.get("customer_used", 0) >= code["per_customer_limit"]:
        return 0, "CODE_ALREADY_USED", "Khách hàng đã dùng mã này rồi."
    if code["kind"] == "first_order" and usage.get("customer_prior_orders", 0) > 0:
        return 0, "CODE_FIRST_ORDER_ONLY", "Mã chỉ áp dụng cho đơn hàng đầu tiên."
    if code["kind"] == "birthday":
        birthday = (customer or {}).get("birthday")
        if not birthday or int(birthday[5:7]) != order_date.month:
            return 0, "CODE_BIRTHDAY_MONTH_ONLY", "Mã sinh nhật chỉ dùng trong tháng sinh nhật của thành viên."
    if subtotal < code["min_order"]:
        return 0, "CODE_MIN_ORDER", f"Đơn cần tối thiểu {_vnd(code['min_order'])} (chưa gồm phí ship) để dùng mã."
    cats = code.get("applicable_categories")
    base = subtotal if not cats else sum(l["line_total"] for l in lines if l["category"] in cats.split(","))
    if base <= 0:
        return 0, "CODE_NOT_APPLICABLE", "Mã không áp dụng cho các sản phẩm trong đơn."
    if code["discount_type"] == "percent":
        amount = round_down(base * code["value"] / 100)
    else:
        amount = int(code["value"])
    if code.get("max_discount"):
        amount = min(amount, int(code["max_discount"]))
    return min(amount, base), None, None


def choose_discount(code_amount: int, tier_amount: int) -> tuple[str | None, int]:
    """Không cộng dồn (DSC-03): lấy mức có lợi hơn cho khách."""
    if code_amount > 0 and code_amount >= tier_amount:
        return "code", code_amount
    if tier_amount > 0:
        return "tier", tier_amount
    return None, 0
