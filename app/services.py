"""Nghiệp vụ dùng chung: kiểm tra khung giờ, hiển thị bản ghi, thao tác ghi (huỷ, đổi lịch, hoàn tiền...).

Router khách hàng và router nhân viên (duyệt yêu cầu) cùng gọi các hàm ở đây.
"""
from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta

from . import labels, repo, rules
from .errors import ApiError
from .policy import describe_rules
from .pricing import shipping_fee
from .schedule import delivery_schedule
from .lunar import lunar_label
from .utils import at, date_vi, hours_between, iso, is_peak_day, mask_phone, vnd

MAX_DAYS_AHEAD = 90


# ============================================================ khung giờ giao
def resolve_branch(conn, zone: dict | None, fulfillment: str, branch_id: str | None, slot: dict) -> dict | None:
    """Chi nhánh thực hiện đơn. CN02 đóng cửa 20:00 nên khung K6 được chuyển về CN01."""
    if fulfillment == "pickup":
        branch = repo.get_branch(conn, branch_id) if branch_id else None
        if branch is None or slot["start_time"] < branch["open_time"] or slot["end_time"] > branch["close_time"]:
            return None
        return branch
    branch = repo.get_branch(conn, branch_id) if branch_id else repo.get_branch(conn, zone["default_branch_id"])
    if branch and slot["end_time"] > branch["close_time"]:
        branch = repo.get_branch(conn, "CN01")
    return branch


def slot_availability(conn, *, zone: dict | None, fulfillment: str, branch_id: str | None, d: date,
                      products: list[dict], now: datetime, policy: dict,
                      exclude_code: str | None = None, min_lead_hours: int = 0) -> tuple[list[dict], int]:
    slots = repo.slots_by_code(conn)
    lead = max([policy["ordering"]["min_lead_time_hours"], min_lead_hours] + [p["lead_time_hours"] for p in products])
    allowed = zone["allowed_slots"].split(",") if (fulfillment == "delivery" and zone) else list(slots)
    result = []
    for code, slot in slots.items():
        branch = resolve_branch(conn, zone, fulfillment, branch_id, slot)
        start = at(d, slot["start_time"])
        reason = None
        if code not in allowed:
            reason = f"Khu vực {zone['id']} không giao khung giờ này."
        elif branch is None:
            reason = "Cửa hàng không mở cửa trong khung giờ này."
        elif fulfillment == "delivery" and zone and (d - now.date()).days < zone["min_days_ahead"]:
            reason = f"Khu vực {zone['id']} cần đặt trước tối thiểu {zone['min_days_ahead']} ngày."
        elif hours_between(now, start) < lead:
            reason = f"Cần đặt trước tối thiểu {lead} giờ so với đầu khung giờ."
        load = repo.slot_load(conn, branch["id"], d.isoformat(), code, exclude_code) if branch else 0
        capacity = branch["slot_capacity"] if branch else 0
        if reason is None and load >= capacity:
            reason = "Khung giờ đã kín đơn."
        result.append({
            "slot_code": code,
            "window": f"{slot['start_time']}–{slot['end_time']}",
            "branch_id": branch["id"] if branch else None,
            "capacity": capacity,
            "booked": load,
            "remaining": max(capacity - load, 0),
            "available": reason is None,
            "reason": reason,
        })
    return result, lead


def validate_slot(conn, *, zone, fulfillment, branch_id, d: date, slot_code: str, products, now, policy,
                  exclude_code: str | None = None, min_lead_hours: int = 0) -> tuple[dict, dict]:
    slots = repo.slots_by_code(conn)
    slot_code = (slot_code or "").upper()
    if slot_code not in slots:
        raise ApiError(422, "INVALID_SLOT", "Khung giờ không hợp lệ (K1–K6).",
                       {"slots": {c: f"{s['start_time']}–{s['end_time']}" for c, s in slots.items()}})
    if d < now.date():
        raise ApiError(422, "DATE_IN_PAST", "Ngày giao đã qua.")
    if (d - now.date()).days > MAX_DAYS_AHEAD:
        raise ApiError(422, "DATE_TOO_FAR", f"Chỉ nhận đặt trước tối đa {MAX_DAYS_AHEAD} ngày.")
    table, lead = slot_availability(conn, zone=zone, fulfillment=fulfillment, branch_id=branch_id, d=d,
                                    products=products, now=now, policy=policy, exclude_code=exclude_code,
                                    min_lead_hours=min_lead_hours)
    chosen = next(s for s in table if s["slot_code"] == slot_code)
    if not chosen["available"]:
        alternatives = [s for s in table if s["available"]]
        next_day = d + timedelta(days=1)
        next_table, _ = slot_availability(conn, zone=zone, fulfillment=fulfillment, branch_id=branch_id,
                                          d=next_day, products=products, now=now, policy=policy,
                                          exclude_code=exclude_code, min_lead_hours=min_lead_hours)
        raise ApiError(409, "SLOT_UNAVAILABLE", f"Khung giờ {slot_code} ngày {d:%d/%m/%Y} không khả dụng: {chosen['reason']}",
                       {"required_lead_time_hours": lead,
                        "alternatives_same_day": [s["slot_code"] + " " + s["window"] for s in alternatives],
                        "alternatives_next_day": {next_day.isoformat(): [s["slot_code"] + " " + s["window"]
                                                                          for s in next_table if s["available"]]}})
    branch = repo.get_branch(conn, chosen["branch_id"])
    return branch, slots[slot_code]


# ============================================================ hiển thị
def request_view(req: dict, *, brief: bool = False) -> dict:
    rule_ids = json.loads(req["approval_rules"]) if req["approval_rules"] else []
    view = {
        "code": req["code"],
        "type": req["type"],
        "type_label": labels.REQUEST_TYPE[req["type"]],
        "status": req["status"],
        "status_label": labels.REQUEST_STATUS[req["status"]],
        "ref_type": req["ref_type"],
        "ref_code": req["ref_code"],
        "reason_code": req["reason_code"],
        "amount": req["amount"],
        "amount_label": vnd(req["amount"]) if req["amount"] else None,
        "requires_approval": bool(req["requires_approval"]),
        "approval_rules": describe_rules(rule_ids),
        "issued_code": req["issued_code"],
        "resolution_note": req["resolution_note"],
        "created_at": req["created_at"],
        "decided_at": req["decided_at"],
    }
    if not brief:
        view["description"] = req["description"]
        view["payload"] = json.loads(req["payload"]) if req["payload"] else None
        view["created_by"] = req["created_by"]
        view["decided_by"] = req["decided_by"]
    return view


def pending_message(req: dict) -> str:
    rule_ids = json.loads(req["approval_rules"]) if req["approval_rules"] else []
    if not rule_ids:
        return ""
    first = describe_rules(rule_ids)[0]
    return (f"Yêu cầu đã được ghi nhận với mã {req['code']} và đang chờ {first['approver']} duyệt "
            f"(dự kiến trong {first['sla_hours']} giờ làm việc). Chưa được hứa kết quả với khách (NOT-02).")


def payment_instructions(order: dict, orderer_phone: str, min_prepay_percent: int | None = None) -> dict | None:
    if order["payment_method"] not in ("bank_transfer", "momo", "vnpay") or order["payment_status"] != "unpaid":
        return None
    info = {"method": order["payment_method"], "amount": order["total"], "amount_label": vnd(order["total"])}
    if min_prepay_percent:
        minimum = order["total"] * min_prepay_percent // 100
        info["min_prepay_amount"] = minimum
        info["min_prepay_label"] = f"Tối thiểu {min_prepay_percent}% = {vnd(minimum)} (ORD-06)"
    if order["payment_method"] == "bank_transfer":
        info.update(labels.BANK_TRANSFER_INFO)
        info["transfer_note"] = f"{order['code']} {orderer_phone[-4:]}"
    else:
        info["note"] = "Mộc Miên gửi link thanh toán qua Zalo/SMS tới số người đặt trong vòng 10 phút."
    return info


def order_view(conn, order: dict, now: datetime, policy: dict, *, detail: bool = True) -> dict:
    slots = repo.slots_by_code(conn)
    items = repo.order_items(conn, order["code"])
    branch = repo.get_branch(conn, order["branch_id"])
    zone = repo.get_zone(conn, order["zone_id"])
    customer = repo.get_customer(conn, order["customer_id"])
    start, end = rules.slot_window(order, slots)
    d = date.fromisoformat(order["delivery_date"])
    tier_cfg = policy["loyalty"]["tiers"][customer["tier"]]
    amount_due = 0 if order["status"] in ("cancelled", "refunded") else max(order["total"] - order["paid_amount"], 0)
    view = {
        "code": order["code"],
        "status": order["status"],
        "status_label": labels.ORDER_STATUS[order["status"]],
        "channel": order["channel"],
        "occasion": order["occasion"],
        "created_at": order["created_at"],
        "customer": {"id": customer["id"], "full_name": customer["full_name"],
                     "phone_masked": mask_phone(customer["phone"]), "tier": customer["tier"],
                     "tier_label": tier_cfg["label"]},
        "fulfillment": order["fulfillment"],
        "fulfillment_label": labels.FULFILLMENT[order["fulfillment"]],
        "branch": {"id": branch["id"], "name": branch["name"], "address": branch["address"], "phone": branch["phone"]},
        "delivery": {
            "date": order["delivery_date"],
            "date_label": date_vi(d),
            "slot_code": order["slot_code"],
            "window": f"{start:%H:%M}–{end:%H:%M}",
            "is_express": bool(order["is_express"]),
            "express_deadline": order["express_deadline"],
            "peak_day": is_peak_day(d, policy),
            "zone_id": order["zone_id"],
            "zone_name": zone["name"] if zone else None,
            "recipient_name": order["recipient_name"],
            "recipient_phone_masked": mask_phone(order["recipient_phone"]),
            "address": order["delivery_address"],
            "is_surprise": bool(order["is_surprise"]),
            "delivered_at": order["delivered_at"],
        },
        "card_message": order["card_message"],
        "items": [{k: i[k] for k in ("sku", "product_name", "quantity", "unit_price", "line_total")} for i in items],
        "pricing": {
            "subtotal": order["subtotal"],
            "shipping_fee": order["shipping_fee"],
            "express_fee": order["express_fee"],
            "discount_source": order["discount_source"],
            "discount_code": order["discount_code"],
            "discount_amount": order["discount_amount"],
            "total": order["total"],
            "total_label": vnd(order["total"]),
        },
        "payment": {
            "method": order["payment_method"],
            "method_label": labels.PAYMENT_METHOD[order["payment_method"]],
            "status": order["payment_status"],
            "status_label": labels.PAYMENT_STATUS[order["payment_status"]],
            "paid_amount": order["paid_amount"],
            "refunded_amount": order["refunded_amount"],
            "amount_due": amount_due,
        },
        "reschedule_count": order["reschedule_count"],
        "cancel_reason": order["cancel_reason"],
        "note": order["note"],
    }
    if detail:
        view["timeline"] = repo.order_events(conn, order["code"])
        view["requests"] = [request_view(r, brief=True) for r in repo.requests_for(conn, "order", order["code"])]
        view["allowed_actions"] = {
            "cancel": rules.cancellation_preview(order, items, slots, now, policy),
            "reschedule": rules.reschedule_check(order, slots, now, policy),
        }
    return view


# ============================================================ thao tác đơn hàng
def refund_processing_days(order_payment_method: str, refund_method: str, policy: dict) -> int:
    days = policy["refund"]["processing_business_days"]
    if refund_method == "store_credit":
        return days["store_credit"]
    if refund_method == "bank_transfer" or order_payment_method in ("cod", "cash"):
        return days["bank_transfer"]
    return days.get(order_payment_method, days["bank_transfer"])


def create_refund_request(conn, *, order: dict, amount: int, reason_code: str, refund_method: str,
                          description: str | None, evidence_urls: list[str] | None, approval_rules: list[str],
                          created_by: str, now: datetime, policy: dict, extra: dict | None = None,
                          approved_by: str | None = None) -> dict:
    status = "pending_approval" if approval_rules and not approved_by else "approved"
    payload = {"refund_method": refund_method,
               "processing_business_days": refund_processing_days(order["payment_method"], refund_method, policy),
               "evidence_urls": evidence_urls or []}
    payload.update(extra or {})
    req = repo.insert_request(conn, type="refund", customer_id=order["customer_id"], ref_type="order",
                              ref_code=order["code"], reason_code=reason_code, description=description,
                              amount=amount, payload=payload, status=status, approval_rules=approval_rules,
                              created_by=created_by, now=now)
    if approved_by:
        conn.execute("UPDATE service_requests SET decided_at = ?, decided_by = ? WHERE code = ?",
                     (iso(now), approved_by, req["code"]))
    conn.execute("UPDATE orders SET payment_status = 'refund_pending', updated_at = ? WHERE code = ?",
                 (iso(now), order["code"]))
    return repo.get_request(conn, req["code"])


def perform_cancel(conn, order: dict, *, refund_amount: int, reason: str | None, actor: str, now: datetime,
                   policy: dict, approved_by: str | None = None) -> dict | None:
    conn.execute("UPDATE orders SET status = 'cancelled', cancel_reason = ?, updated_at = ? WHERE code = ?",
                 (reason, iso(now), order["code"]))
    for item in repo.order_items(conn, order["code"]):
        repo.adjust_stock(conn, item["sku"], order["branch_id"], item["quantity"], now)
    repo.log_order_event(conn, order["code"], "cancelled", now, from_status=order["status"], to_status="cancelled",
                         detail=reason, actor=actor)
    if refund_amount <= 0:
        return None
    threshold = policy["refund"]["auto_approve_max_vnd"]
    rule_ids = ["APR-01"] if refund_amount > threshold else []
    created_by = actor if actor in ("agent", "staff", "customer") else "system"
    return create_refund_request(conn, order=order, amount=refund_amount, reason_code="cancelled_order",
                                 refund_method="original_payment", description=f"Hoàn tiền do huỷ đơn: {reason or ''}".strip(),
                                 evidence_urls=None, approval_rules=rule_ids, created_by=created_by, now=now,
                                 policy=policy, approved_by=approved_by)


def apply_reschedule(conn, order: dict, *, new_date: date, slot_code: str, branch_id: str, mode: str, actor: str,
                     now: datetime, policy: dict, reason: str | None = None) -> None:
    old = f"{order['delivery_date']} {order['slot_code'] or 'hỏa tốc'}"
    new = f"{new_date.isoformat()} {slot_code}"
    if branch_id != order["branch_id"]:
        for item in repo.order_items(conn, order["code"]):
            repo.adjust_stock(conn, item["sku"], order["branch_id"], item["quantity"], now)
            repo.adjust_stock(conn, item["sku"], branch_id, -item["quantity"], now)
    if mode == "redelivery":
        customer = repo.get_customer(conn, order["customer_id"])
        fee = shipping_fee(repo.get_zone(conn, order["zone_id"]), 0, customer["tier"], policy)
        total = order["total"] + fee
        paid = order["paid_amount"]
        pay_status = "paid" if paid >= total else ("partially_paid" if paid > 0 else "unpaid")
        conn.execute(
            "UPDATE orders SET status = 'confirmed', delivery_date = ?, slot_code = ?, branch_id = ?, is_express = 0, "
            "shipping_fee = shipping_fee + ?, total = ?, payment_status = ?, updated_at = ? WHERE code = ?",
            (new_date.isoformat(), slot_code, branch_id, fee, total, pay_status, iso(now), order["code"]),
        )
        repo.log_order_event(conn, order["code"], "redelivery_scheduled", now, from_status=order["status"],
                             to_status="confirmed", detail=f"Giao lại: {old} → {new}, phí giao lại {vnd(fee)}. {reason or ''}".strip(),
                             actor=actor)
    else:
        conn.execute(
            "UPDATE orders SET delivery_date = ?, slot_code = ?, branch_id = ?, reschedule_count = reschedule_count + 1, "
            "updated_at = ? WHERE code = ?",
            (new_date.isoformat(), slot_code, branch_id, iso(now), order["code"]),
        )
        repo.log_order_event(conn, order["code"], "rescheduled", now, detail=f"{old} → {new}. {reason or ''}".strip(),
                             actor=actor)


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def issue_goodwill_code(conn, *, customer_id: str, percent: int | None, amount: int | None, now: datetime,
                        policy: dict, created_by: str, max_discount: int | None = None) -> dict:
    cfg = policy["discount"]["goodwill_code"]
    while True:
        code = cfg["prefix"] + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not repo.one(conn, "SELECT 1 FROM discount_codes WHERE code = ?", (code,)):
            break
    if percent:
        dtype, value = "percent", percent
        cap = max_discount or policy["discount"]["agent_max_amount_vnd"]
        description = f"Mã xin lỗi: giảm {percent}% (tối đa {vnd(cap)}) cho 1 đơn"
    else:
        dtype, value, cap = "fixed", amount, amount
        description = f"Mã xin lỗi: giảm {vnd(amount)} cho 1 đơn"
    valid_to = now.date() + timedelta(days=cfg["validity_days"])
    conn.execute(
        "INSERT INTO discount_codes (code, description, discount_type, value, max_discount, min_order, "
        "applicable_categories, valid_from, valid_to, usage_limit, used_count, per_customer_limit, customer_id, kind, "
        "is_active, created_by, created_at) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, 1, 0, 1, ?, 'goodwill', 1, ?, ?)",
        (code, description, dtype, value, cap, now.date().isoformat(), valid_to.isoformat(), customer_id,
         created_by, iso(now)),
    )
    return {"code": code, "description": description, "valid_to": valid_to.isoformat()}


# ============================================================ tư vấn sự kiện
def consultation_view(conn, c: dict, now: datetime, policy: dict) -> dict:
    customer = repo.get_customer(conn, c["customer_id"])
    appt = date.fromisoformat(c["appointment_date"])
    event = date.fromisoformat(c["event_date"])
    view = {
        "code": c["code"],
        "status": c["status"],
        "status_label": labels.CONSULT_STATUS[c["status"]],
        "customer": {"full_name": customer["full_name"], "phone_masked": mask_phone(customer["phone"])},
        "event_type": c["event_type"],
        "event_type_label": labels.EVENT_TYPE[c["event_type"]],
        "mode": c["mode"],
        "mode_label": labels.CONSULT_MODE[c["mode"]],
        "appointment": {"date": c["appointment_date"], "date_label": date_vi(appt), "time": c["appointment_time"],
                        "duration_minutes": policy["consultation"]["duration_minutes"]},
        "event_date": c["event_date"],
        "event_date_label": date_vi(event),
        "venue": c["venue"],
        "guest_count": c["guest_count"],
        "budget_range": c["budget_range"],
        "consultant": c["consultant"],
        "onsite_fee": c["onsite_fee"],
        "package_name": c["package_name"],
        "contract_value": c["contract_value"],
        "deposit_amount": c["deposit_amount"],
        "deposit_status": c["deposit_status"],
        "deposit_status_label": labels.DEPOSIT_STATUS[c["deposit_status"]],
        "reschedule_count": c["reschedule_count"],
        "note": c["note"],
        "cancel_reason": c["cancel_reason"],
        "requests": [request_view(r, brief=True) for r in repo.requests_for(conn, "consultation", c["code"])],
        "allowed_actions": {
            "reschedule": rules.consult_reschedule_check(c, now, policy),
            "cancel": rules.consult_cancel_preview(c, now.date(), policy),
            "change_event_date": rules.event_date_change_check(c, now.date(), policy),
        },
    }
    return view


def consultation_slots(conn, d: date, mode: str, now: datetime, policy: dict, exclude_code: str | None = None) -> list[dict]:
    cfg = policy["consultation"]
    times = cfg["onsite_slots"] if mode == "onsite" else cfg["slots"]
    result = []
    for t in times:
        reason = None
        if d.weekday() not in cfg["open_weekdays"]:
            reason = "Studio nghỉ Thứ Hai."
        elif hours_between(now, at(d, t)) < cfg["min_hours_ahead"]:
            reason = f"Cần đặt trước tối thiểu {cfg['min_hours_ahead']} giờ."
        load = repo.consultation_load(conn, d.isoformat(), t, exclude_code)
        if reason is None and load >= cfg["consultants_per_slot"]:
            reason = "Khung giờ đã kín lịch tư vấn viên."
        result.append({"time": t, "booked": load, "capacity": cfg["consultants_per_slot"],
                       "available": reason is None, "reason": reason})
    return result


def apply_consult_reschedule(conn, c: dict, *, new_date: date, new_time: str, now: datetime) -> None:
    conn.execute(
        "UPDATE consultations SET appointment_date = ?, appointment_time = ?, reschedule_count = reschedule_count + 1, "
        "updated_at = ? WHERE code = ?",
        (new_date.isoformat(), new_time, iso(now), c["code"]),
    )


def apply_consult_cancel(conn, c: dict, *, refund_amount: int, reason: str | None, now: datetime) -> None:
    if c["deposit_amount"] > 0:
        deposit_status = "refund_pending" if refund_amount > 0 else "forfeited"
    else:
        deposit_status = c["deposit_status"]
    conn.execute(
        "UPDATE consultations SET status = 'cancelled', deposit_status = ?, cancel_reason = ?, updated_at = ? WHERE code = ?",
        (deposit_status, reason, iso(now), c["code"]),
    )


def apply_event_date_change(conn, c: dict, *, new_event_date: date, now: datetime) -> None:
    conn.execute(
        "UPDATE consultations SET event_date = ?, event_date_change_count = event_date_change_count + 1, "
        "updated_at = ? WHERE code = ?",
        (new_event_date.isoformat(), iso(now), c["code"]),
    )


# ============================================================ gói định kỳ
def subscription_upcoming(sub: dict, plan: dict, count: int = 4) -> list[date]:
    if not sub["next_delivery_date"] or sub["status"] in ("cancelled", "expired"):
        return []
    remaining = sub["total_deliveries"] - sub["delivered_count"]
    start = date.fromisoformat(sub["next_delivery_date"])
    return delivery_schedule(plan["frequency"], start, sub["delivery_weekday"], min(count, remaining))


def subscription_notice_ok(sub: dict, slots: dict, now: datetime, policy: dict) -> tuple[bool, float | None]:
    if not sub["next_delivery_date"] or sub["status"] != "active":
        return True, None
    start = at(date.fromisoformat(sub["next_delivery_date"]), slots[sub["slot_code"]]["start_time"])
    hours = round(hours_between(now, start), 2)
    return hours >= policy["subscription"]["change_notice_hours"], hours


def subscription_view(conn, sub: dict, now: datetime, policy: dict) -> dict:
    plan = repo.get_plan(conn, sub["plan_id"])
    slots = repo.slots_by_code(conn)
    customer = repo.get_customer(conn, sub["customer_id"])
    slot = slots[sub["slot_code"]]
    upcoming = subscription_upcoming(sub, plan)
    notice_ok, hours = subscription_notice_ok(sub, slots, now, policy)
    pause_cfg = policy["subscription"]["pause"]
    return {
        "code": sub["code"],
        "status": sub["status"],
        "status_label": labels.SUB_STATUS[sub["status"]],
        "customer": {"full_name": customer["full_name"], "phone_masked": mask_phone(customer["phone"])},
        "plan": {"id": plan["id"], "name": plan["name"], "description": plan["description"],
                 "frequency": plan["frequency"], "frequency_label": labels.SUB_FREQUENCY[plan["frequency"]],
                 "price_per_delivery": plan["price_per_delivery"]},
        "term_months": sub["term_months"],
        "deliveries": {"total": sub["total_deliveries"], "delivered": sub["delivered_count"],
                       "remaining": sub["total_deliveries"] - sub["delivered_count"]},
        "price_total": sub["price_total"],
        "paid_amount": sub["paid_amount"],
        "start_date": sub["start_date"],
        "end_date": sub["end_date"],
        "delivery_weekday": sub["delivery_weekday"],
        "delivery_weekday_label": None if sub["delivery_weekday"] is None else
        ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][sub["delivery_weekday"]],
        "slot": {"code": sub["slot_code"], "window": f"{slot['start_time']}–{slot['end_time']}"},
        "zone_id": sub["zone_id"],
        "delivery_address": sub["delivery_address"],
        "recipient_name": sub["recipient_name"],
        "paused_until": sub["paused_until"],
        "pause_count": sub["pause_count"],
        "next_delivery": None if not upcoming else {
            "date": upcoming[0].isoformat(), "date_label": date_vi(upcoming[0]),
            "lunar_label": lunar_label(upcoming[0] + timedelta(days=1)) if plan["frequency"] == "lunar_1_15" else None,
            "hours_until": hours,
        },
        "upcoming_deliveries": [d.isoformat() for d in upcoming],
        "requests": [request_view(r, brief=True) for r in repo.requests_for(conn, "subscription", sub["code"])],
        "allowed_actions": {
            "change_notice_ok": notice_ok,
            "pause": {"allowed": sub["status"] == "active" and notice_ok,
                      "requires_approval": sub["pause_count"] >= pause_cfg["max_times_per_term"],
                      "max_days": pause_cfg["max_days"], "used": sub["pause_count"],
                      "max_times": pause_cfg["max_times_per_term"], "policy_rule": "SUB-02"},
            "resume": {"allowed": sub["status"] == "paused"},
            "reschedule": {"allowed": sub["status"] in ("active", "paused") and notice_ok, "policy_rule": "SUB-02"},
            "cancel": rules.subscription_cancel_preview(sub, policy),
        },
    }


def _recompute_schedule(sub: dict, plan: dict, first_on_or_after: date, weekday: int | None) -> tuple[str, str]:
    remaining = sub["total_deliveries"] - sub["delivered_count"]
    dates = delivery_schedule(plan["frequency"], first_on_or_after, weekday, max(remaining, 1))
    return dates[0].isoformat(), dates[-1].isoformat()


def apply_sub_pause(conn, sub: dict, *, resume_date: date, now: datetime) -> None:
    plan = repo.get_plan(conn, sub["plan_id"])
    nxt, end = _recompute_schedule(sub, plan, resume_date, sub["delivery_weekday"])
    conn.execute(
        "UPDATE subscriptions SET status = 'paused', paused_until = ?, pause_count = pause_count + 1, "
        "next_delivery_date = ?, end_date = ?, updated_at = ? WHERE code = ?",
        (resume_date.isoformat(), nxt, end, iso(now), sub["code"]),
    )


def apply_sub_resume(conn, sub: dict, *, now: datetime) -> None:
    plan = repo.get_plan(conn, sub["plan_id"])
    nxt, end = _recompute_schedule(sub, plan, now.date() + timedelta(days=1), sub["delivery_weekday"])
    conn.execute(
        "UPDATE subscriptions SET status = 'active', paused_until = NULL, next_delivery_date = ?, end_date = ?, "
        "updated_at = ? WHERE code = ?",
        (nxt, end, iso(now), sub["code"]),
    )


def apply_sub_reschedule(conn, sub: dict, *, weekday: int | None, slot_code: str, now: datetime) -> None:
    plan = repo.get_plan(conn, sub["plan_id"])
    start = date.fromisoformat(sub["paused_until"]) if sub["status"] == "paused" else now.date() + timedelta(days=1)
    nxt, end = _recompute_schedule(sub, plan, start, weekday)
    conn.execute(
        "UPDATE subscriptions SET delivery_weekday = ?, slot_code = ?, next_delivery_date = ?, end_date = ?, "
        "updated_at = ? WHERE code = ?",
        (weekday, slot_code, nxt, end, iso(now), sub["code"]),
    )


def apply_sub_cancel(conn, sub: dict, *, refund_amount: int, reason: str | None, now: datetime, policy: dict,
                     actor: str, approved_by: str | None = None) -> dict | None:
    conn.execute(
        "UPDATE subscriptions SET status = 'cancelled', next_delivery_date = NULL, note = COALESCE(note || ' | ', '') || ?, "
        "updated_at = ? WHERE code = ?",
        (f"Huỷ: {reason or 'không nêu lý do'}", iso(now), sub["code"]),
    )
    if refund_amount <= 0:
        return None
    req = repo.insert_request(conn, type="refund", customer_id=sub["customer_id"], ref_type="subscription",
                              ref_code=sub["code"], reason_code="subscription_cancelled",
                              description="Hoàn tiền các lần giao chưa dùng khi huỷ gói (SUB-03).",
                              amount=refund_amount, payload={"refund_method": "bank_transfer",
                                                             "processing_business_days": policy["refund"]["processing_business_days"]["bank_transfer"]},
                              status="approved", approval_rules=[], created_by=actor if actor in ("agent", "staff", "customer") else "system",
                              now=now)
    if approved_by:
        conn.execute("UPDATE service_requests SET decided_at = ?, decided_by = ? WHERE code = ?",
                     (iso(now), approved_by, req["code"]))
    return repo.get_request(conn, req["code"])
