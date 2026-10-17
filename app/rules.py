"""Đánh giá hành động theo policy.yaml (hàm thuần: nhận dữ liệu, trả về kết luận).

Mỗi kết luận có dạng:
    {"allowed": bool, "requires_approval": bool, "approval_rules": [APR-xx], "policy_rule": "...", "reason": "..."}
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .pricing import round_down
from .utils import at, hours_between, is_peak_day, parse_dt, vnd


# ============================================================ đơn hàng
def slot_window(order: dict, slots: dict[str, dict]) -> tuple[datetime, datetime]:
    if order["is_express"]:
        deadline = parse_dt(order["express_deadline"])
        return deadline - timedelta(hours=2), deadline
    slot = slots[order["slot_code"]]
    d = date.fromisoformat(order["delivery_date"])
    return at(d, slot["start_time"]), at(d, slot["end_time"])


def _result(allowed: bool, *, approval_rules: list[str] | None = None, **extra) -> dict:
    rules = approval_rules or []
    return {"allowed": allowed, "requires_approval": bool(rules), "approval_rules": rules, **extra}


NOT_CANCELLABLE_REASON = {
    "delivered": "Đơn đã giao xong nên không huỷ được; nếu hoa có vấn đề, vui lòng tạo yêu cầu đổi trả/hoàn tiền.",
    "failed_delivery": "Đơn giao không thành công: có thể giao lại trong 24 giờ (CHG-03) hoặc chuyển nhân viên xử lý.",
    "cancelled": "Đơn đã được huỷ trước đó.",
    "refunded": "Đơn đã được hoàn tiền.",
}


def cancellation_preview(order: dict, items: list[dict], slots: dict, now: datetime, policy: dict) -> dict:
    cfg = policy["order_changes"]["cancellation"]
    threshold = policy["refund"]["auto_approve_max_vnd"]
    status = order["status"]
    if status in cfg["not_cancellable_statuses"]:
        return _result(False, action="cancel", policy_rule="CHG-02", reason=NOT_CANCELLABLE_REASON.get(status))

    start, _ = slot_window(order, slots)
    hours = round(hours_between(now, start), 2)
    is_custom = max((i["lead_time_hours"] for i in items), default=0) >= cfg["custom_order_lead_time_hours"]
    paid = order["paid_amount"] - order["refunded_amount"]
    info = dict(action="cancel", policy_rule="CHG-02", hours_before_slot=hours, is_custom_order=is_custom,
                paid_amount=paid, refund_percent=0, refund_amount=0, refund_requires_approval=False)

    if status in cfg["in_progress_statuses"]:
        return _result(True, approval_rules=["APR-03"], **info,
                       reason="Đơn đang được cắm/giao nên cần trưởng ca duyệt huỷ; mặc định không hoàn tiền.")
    if paid <= 0:
        if hours >= cfg["unpaid_free_min_hours"]:
            return _result(True, **{**info, "refund_percent": 100},
                           reason="Đơn chưa thanh toán và còn đủ thời gian nên huỷ miễn phí.")
        return _result(True, approval_rules=["APR-03"], **info,
                       reason=f"Còn {hours:.1f} giờ (< {cfg['unpaid_free_min_hours']} giờ) trước khung giờ giao, cần trưởng ca duyệt.")

    tiers = sorted(cfg["custom_order_tiers" if is_custom else "standard_tiers"],
                   key=lambda t: -t["min_hours_before_slot"])
    for tier in tiers:
        if hours >= tier["min_hours_before_slot"]:
            pct = tier["refund_percent"]
            amount = round_down(paid * pct / 100, cfg["refund_rounding_vnd"])
            kind = "đơn đặt riêng" if is_custom else "đơn thường"
            return _result(True, **{**info, "refund_percent": pct, "refund_amount": amount,
                                    "refund_requires_approval": amount > threshold},
                           refund_approval_rules=["APR-01"] if amount > threshold else [],
                           reason=f"{kind.capitalize()}, còn {hours:.1f} giờ trước khung giờ giao → hoàn {pct}% "
                                  f"số đã thanh toán ({vnd(amount)}).")
    last = tiers[-1]["min_hours_before_slot"]
    return _result(True, approval_rules=["APR-03"], **info,
                   reason=f"Còn {hours:.1f} giờ (< {last} giờ) trước khung giờ giao: không tự huỷ được, cần trưởng ca duyệt.")


def reschedule_check(order: dict, slots: dict, now: datetime, policy: dict) -> dict:
    cfg = policy["order_changes"]["reschedule"]
    rcfg = policy["order_changes"]["redelivery"]
    status = order["status"]

    if status in rcfg["allowed_statuses"]:
        _, end = slot_window(order, slots)
        since = round(hours_between(end, now), 2)
        if since <= rcfg["hold_hours"]:
            return _result(True, action="reschedule", mode="redelivery", policy_rule="CHG-03",
                           hours_since_failed=since,
                           reason="Giao lại trong 24 giờ kể từ lần giao không thành công; thu lại phí ship theo khu vực.")
        return _result(False, action="reschedule", mode="redelivery", policy_rule="CHG-03",
                       hours_since_failed=since, reason=rcfg["after_hold"])

    if status in cfg["in_progress_statuses"]:
        return _result(True, approval_rules=["APR-04"], action="reschedule", mode="reschedule", policy_rule="CHG-01",
                       reason="Đơn đang được cắm/giao, đổi lịch cần trưởng ca duyệt.")
    if status not in cfg["allowed_statuses"]:
        return _result(False, action="reschedule", mode="reschedule", policy_rule="CHG-01",
                       reason=f"Đơn ở trạng thái '{status}' không đổi lịch được.")

    start, _ = slot_window(order, slots)
    hours = round(hours_between(now, start), 2)
    reasons, rules = [], []
    if order["is_express"]:
        rules.append("APR-04")
        reasons.append("Đơn giao hỏa tốc không đổi lịch tự động.")
    if order["reschedule_count"] >= cfg["max_times_per_order"]:
        rules.append("APR-04")
        reasons.append(f"Đơn đã đổi lịch {order['reschedule_count']} lần (tối đa {cfg['max_times_per_order']}).")
    if hours < cfg["free_min_hours_before_slot"]:
        rules.append("APR-04")
        reasons.append(f"Còn {hours:.1f} giờ (< {cfg['free_min_hours_before_slot']} giờ) trước khung giờ giao.")
    if not reasons:
        reasons.append(f"Còn {hours:.1f} giờ trước khung giờ giao, được đổi miễn phí "
                       f"(đã đổi {order['reschedule_count']}/{cfg['max_times_per_order']} lần).")
    return _result(True, approval_rules=list(dict.fromkeys(rules)), action="reschedule", mode="reschedule",
                   policy_rule="CHG-01", hours_before_slot=hours, reason=" ".join(reasons))


# ============================================================ hoàn tiền & đổi trả
def _main_fresh_item(items: list[dict]) -> dict | None:
    fresh = [i for i in items if i.get("freshness_days")]
    return max(fresh, key=lambda i: i["line_total"]) if fresh else None


def refund_assessment(order: dict, items: list[dict], slots: dict, now: datetime, policy: dict, *,
                      reason_code: str, amount: int | None, refundable: int, has_evidence: bool) -> dict:
    cfg = policy["refund"]
    threshold = cfg["auto_approve_max_vnd"]
    if order["status"] not in ("delivered", "failed_delivery"):
        hint = ("Đơn chưa giao: dùng chức năng huỷ đơn (CHG-02) thay vì hoàn tiền."
                if order["status"] in ("pending", "confirmed", "arranging", "delivering")
                else "Đơn này không còn khoản nào để hoàn.")
        return {"eligible": False, "reason": hint}
    if refundable <= 0:
        return {"eligible": False, "reason": "Đơn không còn số tiền nào có thể hoàn (chưa thanh toán hoặc đã hoàn/đang hoàn hết)."}

    _, slot_end = slot_window(order, slots)
    ref_time = parse_dt(order["delivered_at"]) if order["delivered_at"] else slot_end
    hours_since = round(hours_between(ref_time, now), 2)
    rules: list[str] = []
    notes: list[str] = []
    suggested = refundable
    offer = None

    if reason_code == "late_delivery":
        if not order["delivered_at"]:
            return {"eligible": False, "reason": "Đơn chưa có thời điểm giao thành công để tính trễ."}
        tolerance = cfg["reasons"]["late_delivery"]["grace_minutes"]
        if is_peak_day(date.fromisoformat(order["delivery_date"]), policy):
            tolerance += policy["ordering"]["peak_day_rules"]["slot_tolerance_minutes"]
        late = round((parse_dt(order["delivered_at"]) - slot_end).total_seconds() / 60)
        notes.append(f"Giao trễ {max(late, 0)} phút so với cuối khung giờ (dung sai {tolerance} phút).")
        fee_scope = order["shipping_fee"] + order["express_fee"]
        if late <= tolerance:
            suggested = 0
            notes.append("Chưa vượt dung sai nên theo REF-04 không bồi hoàn.")
        elif late <= 60:
            suggested = 0
            offer = "Tặng mã giảm 10% cho đơn sau (REF-04, DSC-02) — dùng POST /requests/discount."
            notes.append("Trễ 30–60 phút: chính sách là tặng mã giảm giá, không hoàn tiền.")
        else:
            suggested = min(fee_scope, refundable)
            offer = "Hoàn phí ship/hỏa tốc + tặng mã giảm 10% cho đơn sau (REF-04)."
        if amount is not None and amount > suggested:
            rules.append("APR-09")
            notes.append(f"Số tiền đề nghị vượt mức chính sách ({vnd(suggested)}) → bồi thường ngoài chính sách.")
    elif reason_code in ("damaged", "wrong_item", "missing_item", "failed_delivery_shop_fault"):
        window = cfg["reasons"][reason_code]["report_within_hours"]
        if hours_since > window:
            rules.append("APR-08")
            notes.append(f"Báo sau {hours_since:.1f} giờ, quá hạn {window} giờ (REF/EXC-02).")
    elif reason_code == "wilted_early":
        main = _main_fresh_item(items)
        days = main["freshness_days"] if main else policy["exchange"]["freshness_guarantee_days"]["default"]
        if hours_since > days * 24:
            rules.append("APR-08")
            notes.append(f"Đã {hours_since / 24:.1f} ngày kể từ khi nhận, quá cam kết tươi {days} ngày (EXC-04).")
        else:
            notes.append(f"Trong thời gian cam kết tươi {days} ngày (EXC-04).")
    else:
        rules.append("APR-09")
        notes.append("Lý do 'khác' luôn cần quản lý xem xét.")

    if reason_code in cfg["evidence_required_reasons"] and not has_evidence:
        rules.append("APR-08")
        notes.append("Thiếu ảnh/video bằng chứng.")

    final_amount = amount if amount is not None else suggested
    if final_amount <= 0:
        return {"eligible": False, "reason": " ".join(notes) or "Không có khoản hoàn phù hợp.",
                "compensation_offer": offer, "notes": notes}
    if final_amount > refundable:
        return {"eligible": False, "error": "AMOUNT_EXCEEDS_REFUNDABLE",
                "reason": f"Số tiền đề nghị vượt số có thể hoàn ({vnd(refundable)})."}
    if final_amount > threshold:
        rules.append("APR-01")
        notes.append(f"Số tiền hoàn > {vnd(threshold)} cần quản lý duyệt.")
    return {"eligible": True, "amount": final_amount, "suggested_amount": suggested, "refundable": refundable,
            "hours_since_delivery": hours_since, "approval_rules": list(dict.fromkeys(rules)),
            "compensation_offer": offer, "notes": notes}


def item_group(category: str, policy: dict) -> str:
    if category == "phu_kien":
        return "accessories"
    if category == "hoa_say_kho":
        return "preserved"
    if category in policy["exchange"]["event_products"]["categories"]:
        return "event"
    return "fresh"


def exchange_assessment(order: dict, lines: list[dict], now: datetime, policy: dict, *,
                        reason_code: str, has_evidence: bool) -> dict:
    """lines: các dòng sản phẩm khách muốn đổi (đã kèm category, freshness_days, quantity, line_total)."""
    cfg = policy["exchange"]
    if order["status"] != "delivered" or not order["delivered_at"]:
        return {"eligible": False, "hard_reject": True,
                "reason": "Chỉ đổi trả cho đơn đã giao thành công."}
    hours_since = round(hours_between(parse_dt(order["delivered_at"]), now), 2)
    rules: list[str] = []
    rejects: list[str] = []
    per_item = []
    for line in lines:
        group = item_group(line["category"], policy)
        evidence_needed = True
        if group == "fresh":
            if reason_code == "change_of_mind":
                rejects.append(f"{line['product_name']}: hoa tươi đã nhận đúng mẫu không đổi vì không thích (EXC-03).")
                limit_h, rule = 0, "EXC-03"
            elif reason_code == "wilted_early":
                limit_h, rule = (line["freshness_days"] or cfg["freshness_guarantee_days"]["default"]) * 24, "EXC-04"
            else:
                limit_h, rule = cfg["fresh_flowers"]["report_within_hours"], "EXC-02"
        elif group == "event":
            if reason_code == "change_of_mind":
                rejects.append(f"{line['product_name']}: hoa sự kiện/chia buồn/cưới không đổi trả theo sở thích (EXC-07).")
            limit_h, rule = cfg["event_products"]["report_within_hours"], "EXC-07"
        elif group == "accessories":
            limit_h, rule = cfg["accessories"]["return_within_days"] * 24, "EXC-05"
            evidence_needed = reason_code != "change_of_mind"
        else:  # preserved
            if reason_code == "change_of_mind":
                rejects.append(f"{line['product_name']}: hoa sáp/hoa khô chỉ đổi khi lỗi (EXC-06).")
            limit_h, rule = cfg["preserved_flowers"]["return_within_days"] * 24, "EXC-06"
        within = hours_since <= limit_h
        if not within and not rejects:
            rules.append("APR-08")
        if evidence_needed and not has_evidence:
            rules.append("APR-08")
        per_item.append({"sku": line["sku"], "product_name": line["product_name"], "group": group,
                         "policy_rule": rule, "window_hours": limit_h, "within_window": within,
                         "evidence_required": evidence_needed})
    if rejects:
        return {"eligible": False, "hard_reject": True, "reason": " ".join(rejects), "items": per_item,
                "hours_since_delivery": hours_since}
    notes = []
    if "APR-08" in rules:
        notes.append("Ngoài thời hạn đổi trả hoặc thiếu ảnh/video bằng chứng → cần quản lý duyệt (APR-08).")
    return {"eligible": True, "approval_rules": list(dict.fromkeys(rules)), "items": per_item,
            "hours_since_delivery": hours_since, "notes": notes}


# ============================================================ tư vấn sự kiện
def consult_start(c: dict) -> datetime:
    return at(date.fromisoformat(c["appointment_date"]), c["appointment_time"])


def consult_reschedule_check(c: dict, now: datetime, policy: dict) -> dict:
    cfg = policy["consultation"]["reschedule"]
    if c["status"] != "scheduled":
        return _result(False, action="reschedule", policy_rule="CON-04",
                       reason="Chỉ đổi được lịch tư vấn đang ở trạng thái 'đã đặt lịch'.")
    hours = round(hours_between(now, consult_start(c)), 2)
    rules, reasons = [], []
    if hours < cfg["free_min_hours_before"]:
        rules.append("APR-10")
        reasons.append(f"Còn {hours:.1f} giờ (< {cfg['free_min_hours_before']} giờ) trước giờ hẹn.")
    if c["reschedule_count"] >= cfg["max_times"]:
        rules.append("APR-10")
        reasons.append(f"Đã đổi lịch {c['reschedule_count']} lần (tối đa {cfg['max_times']}).")
    if not reasons:
        reasons.append(f"Còn {hours:.1f} giờ trước giờ hẹn, đổi miễn phí.")
    return _result(True, approval_rules=list(dict.fromkeys(rules)), action="reschedule", policy_rule="CON-04",
                   hours_before=hours, reason=" ".join(reasons))


def consult_cancel_preview(c: dict, today: date, policy: dict) -> dict:
    if c["status"] == "scheduled":
        return _result(True, action="cancel", policy_rule="CON-01", refund_percent=0, refund_amount=0,
                       reason="Lịch tư vấn chưa ký hợp đồng: huỷ miễn phí.")
    if c["status"] != "contracted":
        return _result(False, action="cancel", policy_rule="CON-06",
                       reason="Lịch đã kết thúc hoặc đã huỷ nên không có gì để huỷ.")
    days = (date.fromisoformat(c["event_date"]) - today).days
    pct = 0
    for tier in sorted(policy["consultation"]["deposit_refund_tiers"], key=lambda t: -t["min_days_before_event"]):
        if days >= tier["min_days_before_event"]:
            pct = tier["refund_percent"]
            break
    amount = round_down(c["deposit_amount"] * pct / 100)
    return _result(True, approval_rules=["APR-05"], action="cancel", policy_rule="CON-06",
                   days_before_event=days, deposit_amount=c["deposit_amount"], refund_percent=pct,
                   refund_amount=amount,
                   reason=f"Huỷ hợp đồng khi còn {days} ngày trước sự kiện → hoàn {pct}% tiền cọc "
                          f"({vnd(amount)}); mọi khoản hoàn cọc cần quản lý studio duyệt (APR-05).")


def event_date_change_check(c: dict, today: date, policy: dict) -> dict:
    cfg = policy["consultation"]["contract"]["free_event_date_change"]
    if c["status"] != "contracted":
        return _result(False, action="change_event_date", policy_rule="CON-07",
                       reason="Chỉ đổi ngày sự kiện cho lịch đã ký hợp đồng; lịch chưa ký chỉ cần cập nhật khi tư vấn.")
    days = (date.fromisoformat(c["event_date"]) - today).days
    rules, reasons = [], []
    if days < cfg["min_days_before"]:
        rules.append("APR-14")
        reasons.append(f"Còn {days} ngày (< {cfg['min_days_before']} ngày) trước sự kiện.")
    if c["event_date_change_count"] >= cfg["times"]:
        rules.append("APR-14")
        reasons.append(f"Đã dùng {c['event_date_change_count']}/{cfg['times']} lần đổi ngày miễn phí.")
    if not reasons:
        reasons.append("Được đổi ngày sự kiện miễn phí 1 lần (tùy lịch trống của studio).")
    return _result(True, approval_rules=list(dict.fromkeys(rules)), action="change_event_date",
                   policy_rule="CON-07", days_before_event=days, reason=" ".join(reasons))


# ============================================================ gói định kỳ
def subscription_cancel_preview(sub: dict, policy: dict) -> dict:
    if sub["status"] in ("cancelled", "expired"):
        return _result(False, action="cancel", policy_rule="SUB-03", reason="Gói đã kết thúc hoặc đã huỷ.")
    cfg = policy["subscription"]["cancellation"]
    remaining = sub["total_deliveries"] - sub["delivered_count"]
    unit = sub["price_total"] / sub["total_deliveries"]
    unused = round_down(unit * remaining)
    fee = round_down(unused * cfg["fee_percent_of_unused"] / 100)
    refund = max(min(unused - fee, sub["paid_amount"]), 0) if sub["paid_amount"] > 0 else 0
    rules = ["APR-13"] if refund > policy["refund"]["auto_approve_max_vnd"] else []
    return _result(True, approval_rules=rules, action="cancel", policy_rule="SUB-03",
                   remaining_deliveries=remaining, unused_value=unused, fee=fee, refund_amount=refund,
                   reason=f"Còn {remaining} lần giao chưa dùng ({vnd(unused)}), trừ phí {cfg['fee_percent_of_unused']}% "
                          f"({vnd(fee)}) → hoàn {vnd(refund)}."
                          + (" Số tiền hoàn > 500.000đ cần quản lý duyệt (APR-13)." if rules else ""))
