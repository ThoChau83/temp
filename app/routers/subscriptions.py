"""Gói hoa định kỳ: xem gói, đăng ký, tra cứu, tạm ngưng / tiếp tục, đổi lịch, huỷ."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response

from .. import labels, repo, rules, services
from ..db import get_db, many
from ..errors import ApiError
from ..lunar import lunar_label
from ..policy import get_policy
from ..pricing import round_down
from ..schedule import delivery_schedule
from ..schemas import CancelIn, PhoneIn, SubPauseIn, SubRescheduleIn, SubscriptionIn
from ..utils import date_vi, iso, normalize_phone, now, vnd

router = APIRouter(prefix="/subscriptions", tags=["Gói hoa định kỳ"])


@router.get("/plans", summary="Danh sách gói định kỳ và giá theo kỳ hạn")
def plans(conn=Depends(get_db)):
    policy = get_policy()
    discounts = policy["subscription"]["term_discount_percent"]
    out = []
    for p in many(conn, "SELECT * FROM subscription_plans ORDER BY id"):
        terms = {}
        for months in policy["subscription"]["term_months"]:
            n = p["deliveries_per_month"] * months
            pct = discounts[str(months)]
            terms[str(months)] = {"deliveries": n, "discount_percent": pct,
                                  "price_total": round_down(p["price_per_delivery"] * n * (100 - pct) / 100)}
        out.append({**p, "frequency_label": labels.SUB_FREQUENCY[p["frequency"]], "terms": terms})
    return {"plans": out, "allowed_zones": policy["subscription"]["allowed_zones"]}


@router.post("", status_code=201, summary="Đăng ký gói định kỳ (trả trước toàn kỳ)")
def create(body: SubscriptionIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    cfg = policy["subscription"]
    with conn:
        phone = repo.require_phone(body.customer.phone)
        plan = repo.get_plan(conn, body.plan_id)
        if not plan:
            raise ApiError(404, "PLAN_NOT_FOUND", "Không có gói định kỳ này (xem GET /subscriptions/plans).")
        zone = repo.get_zone(conn, body.zone_id)
        if not zone or zone["id"] not in cfg["allowed_zones"]:
            raise ApiError(422, "ZONE_NOT_SUPPORTED", f"Gói định kỳ chỉ giao khu vực {', '.join(cfg['allowed_zones'])}.")
        slot_code = body.slot_code.upper()
        if slot_code not in zone["allowed_slots"].split(","):
            raise ApiError(422, "INVALID_SLOT", f"Khu vực {zone['id']} chỉ giao các khung {zone['allowed_slots']}.")
        if (body.start_date - current.date()).days < cfg["min_start_days_ahead"]:
            raise ApiError(422, "START_TOO_SOON", "Ngày bắt đầu phải từ ngày mai trở đi.")
        if plan["frequency"] != "lunar_1_15" and body.delivery_weekday is None:
            raise ApiError(422, "WEEKDAY_REQUIRED", "Gói giao theo tuần cần chọn thứ giao (delivery_weekday 0–6).")
        weekday = None if plan["frequency"] == "lunar_1_15" else body.delivery_weekday
        total = plan["deliveries_per_month"] * body.term_months
        pct = cfg["term_discount_percent"][str(body.term_months)]
        price_total = round_down(plan["price_per_delivery"] * total * (100 - pct) / 100)
        schedule = delivery_schedule(plan["frequency"], body.start_date, weekday, total)
        customer = repo.upsert_customer(conn, body.customer.full_name, phone, body.customer.email, current)
        code = repo.next_code(conn, "subscriptions", "GD", 3001)
        conn.execute(
            "INSERT INTO subscriptions (code, customer_id, plan_id, term_months, total_deliveries, delivered_count, "
            "price_total, paid_amount, start_date, end_date, delivery_weekday, slot_code, zone_id, delivery_address, "
            "recipient_name, recipient_phone, next_delivery_date, status, pause_count, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_payment', 0, ?, ?, ?)",
            (code, customer["id"], plan["id"], body.term_months, total, price_total, schedule[0].isoformat(),
             schedule[-1].isoformat(), weekday, slot_code, zone["id"], body.delivery_address,
             body.recipient_name or customer["full_name"], normalize_phone(body.recipient_phone) or phone,
             schedule[0].isoformat(), body.note, iso(current), iso(current)),
        )
        sub = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (code,))
    first = schedule[0]
    lunar = f" ({lunar_label(first + timedelta(days=1))} là ngày cúng)" if plan["frequency"] == "lunar_1_15" else ""
    return {"subscription": services.subscription_view(conn, sub, current, policy),
            "payment": {"amount": price_total, "amount_label": vnd(price_total), "method": body.payment_method,
                        **(labels.BANK_TRANSFER_INFO if body.payment_method == "bank_transfer" else {}),
                        "transfer_note": f"{code} {phone[-4:]}"},
            "message": f"Đã đăng ký {plan['name']} {body.term_months} tháng ({total} lần giao), tổng {vnd(price_total)}"
                       f"{f', giảm {pct}%' if pct else ''}. Lần giao đầu: {date_vi(first)}{lunar}. "
                       "Gói kích hoạt khi nhận thanh toán."}


@router.get("/{code}", summary="Tra gói định kỳ theo mã + SĐT")
def lookup(code: str, phone: str = Query(...), conn=Depends(get_db)):
    sub = repo.find_subscription_for_phone(conn, code, phone)
    return {"subscription": services.subscription_view(conn, sub, now(), get_policy())}


def _notice_guard(conn, sub, current, policy) -> None:
    ok, hours = services.subscription_notice_ok(sub, repo.slots_by_code(conn), current, policy)
    if not ok:
        raise ApiError(409, "NOTICE_TOO_SHORT",
                       f"Kỳ giao gần nhất ({date_vi(date.fromisoformat(sub['next_delivery_date']))}) chỉ còn {hours:.1f} giờ, "
                       f"cần báo trước {policy['subscription']['change_notice_hours']} giờ (SUB-02); kỳ này vẫn giao như lịch. "
                       "Có thể tạm ngưng/đổi lịch từ kỳ sau.")


@router.post("/{code}/pause", summary="Tạm ngưng gói (tối đa 30 ngày, 2 lần/kỳ)")
def pause(code: str, body: SubPauseIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    cfg = policy["subscription"]["pause"]
    with conn:
        sub = repo.find_subscription_for_phone(conn, code, body.phone)
        if sub["status"] != "active":
            raise ApiError(409, "PAUSE_NOT_ALLOWED", f"Gói đang ở trạng thái '{labels.SUB_STATUS[sub['status']]}', không tạm ngưng được.")
        _notice_guard(conn, sub, current, policy)
        days = (body.resume_date - current.date()).days
        if days <= 0:
            raise ApiError(422, "INVALID_RESUME_DATE", "Ngày giao lại phải sau hôm nay.")
        rule_ids, reasons = [], []
        if days > cfg["max_days"]:
            rule_ids.append("APR-13")
            reasons.append(f"Tạm ngưng {days} ngày, vượt tối đa {cfg['max_days']} ngày.")
        if sub["pause_count"] >= cfg["max_times_per_term"]:
            rule_ids.append("APR-13")
            reasons.append(f"Đã tạm ngưng {sub['pause_count']} lần trong kỳ (tối đa {cfg['max_times_per_term']}).")
        if rule_ids:
            req = repo.insert_request(conn, type="reschedule", customer_id=sub["customer_id"], ref_type="subscription",
                                      ref_code=sub["code"], reason_code="pause_outside_policy", description=" ".join(reasons),
                                      amount=None, payload={"action": "pause", "resume_date": body.resume_date.isoformat()},
                                      status="pending_approval", approval_rules=list(dict.fromkeys(rule_ids)),
                                      created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "reasons": reasons, "request": services.request_view(req),
                    "message": services.pending_message(req)}
        services.apply_sub_pause(conn, sub, resume_date=body.resume_date, now=current)
        updated = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (sub["code"],))
    view = services.subscription_view(conn, updated, current, policy)
    return {"result": "paused", "subscription": view,
            "message": f"Đã tạm ngưng gói {sub['code']} đến {date_vi(body.resume_date)}; lần giao kế tiếp "
                       f"{view['next_delivery']['date_label'] if view['next_delivery'] else '-'}, hạn gói được lùi tương ứng."}


@router.post("/{code}/resume", summary="Tiếp tục gói đang tạm ngưng")
def resume(code: str, body: PhoneIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        sub = repo.find_subscription_for_phone(conn, code, body.phone)
        if sub["status"] != "paused":
            raise ApiError(409, "RESUME_NOT_ALLOWED", "Gói không ở trạng thái tạm ngưng.")
        services.apply_sub_resume(conn, sub, now=current)
        updated = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (sub["code"],))
    view = services.subscription_view(conn, updated, current, policy)
    return {"result": "resumed", "subscription": view,
            "message": f"Đã kích hoạt lại gói {sub['code']}; lần giao kế tiếp {view['next_delivery']['date_label']}."}


@router.post("/{code}/reschedule", summary="Đổi thứ giao / khung giờ giao (báo trước ≥ 24 giờ)")
def reschedule(code: str, body: SubRescheduleIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        sub = repo.find_subscription_for_phone(conn, code, body.phone)
        if sub["status"] not in ("active", "paused"):
            raise ApiError(409, "RESCHEDULE_NOT_ALLOWED", "Chỉ đổi lịch được gói đang hoạt động hoặc tạm ngưng.")
        _notice_guard(conn, sub, current, policy)
        plan = repo.get_plan(conn, sub["plan_id"])
        weekday = sub["delivery_weekday"]
        if body.delivery_weekday is not None:
            if plan["frequency"] == "lunar_1_15":
                raise ApiError(422, "WEEKDAY_NOT_APPLICABLE", "Gói Hoa Cúng giao theo lịch âm, không đổi thứ giao được.")
            weekday = body.delivery_weekday
        slot_code = (body.slot_code or sub["slot_code"]).upper()
        zone = repo.get_zone(conn, sub["zone_id"])
        if slot_code not in zone["allowed_slots"].split(","):
            raise ApiError(422, "INVALID_SLOT", f"Khu vực {zone['id']} chỉ giao các khung {zone['allowed_slots']}.")
        services.apply_sub_reschedule(conn, sub, weekday=weekday, slot_code=slot_code, now=current)
        updated = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (sub["code"],))
    view = services.subscription_view(conn, updated, current, policy)
    return {"result": "rescheduled", "subscription": view,
            "message": f"Đã cập nhật lịch giao gói {sub['code']}: {view['delivery_weekday_label'] or 'theo lịch âm'}, "
                       f"khung {view['slot']['window']}; lần giao kế tiếp {view['next_delivery']['date_label']}."}


@router.post("/{code}/cancel", summary="Huỷ gói, hoàn tiền các lần chưa giao trừ 10% (dry_run để xem trước)")
def cancel(code: str, body: CancelIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        sub = repo.find_subscription_for_phone(conn, code, body.phone)
        preview = rules.subscription_cancel_preview(sub, policy)
        if not preview["allowed"]:
            raise ApiError(409, "NOT_CANCELLABLE", preview["reason"], preview)
        if body.dry_run:
            return {"result": "preview", "dry_run": True, "preview": preview}
        if preview["requires_approval"]:
            req = repo.insert_request(conn, type="cancellation", customer_id=sub["customer_id"], ref_type="subscription",
                                      ref_code=sub["code"], reason_code="subscription_cancel", description=body.reason,
                                      amount=preview["refund_amount"], payload={"preview": preview},
                                      status="pending_approval", approval_rules=preview["approval_rules"],
                                      created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "preview": preview, "request": services.request_view(req),
                    "message": services.pending_message(req)}
        refund_req = services.apply_sub_cancel(conn, sub, refund_amount=preview["refund_amount"], reason=body.reason,
                                               now=current, policy=policy, actor=body.actor)
    return {"result": "cancelled", "preview": preview,
            "refund_request": services.request_view(refund_req) if refund_req else None,
            "message": f"Đã huỷ gói {sub['code']}." + (f" Hoàn {vnd(refund_req['amount'])} (mã {refund_req['code']})."
                                                         if refund_req else "")}
