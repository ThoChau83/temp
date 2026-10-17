"""Lịch tư vấn hoa cưới / sự kiện: xem lịch trống, đặt, tra cứu, đổi lịch, huỷ, đổi ngày sự kiện."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response

from .. import labels, repo, rules, services
from ..db import get_db
from ..errors import ApiError
from ..policy import get_policy
from ..schemas import CancelIn, ConsultationIn, ConsultRescheduleIn, EventDateChangeIn
from ..utils import date_vi, iso, now, vnd

router = APIRouter(prefix="/consultations", tags=["Tư vấn hoa cưới / sự kiện"])

CONSULTANTS = ["Tư vấn viên Ngọc Hân", "Tư vấn viên Gia Huy"]


def _next_open_days(conn, start: date, mode: str, current, policy, days: int = 3) -> dict[str, list[str]]:
    out, d = {}, start
    while len(out) < days and (d - start).days < 14:
        d += timedelta(days=1)
        free = [s["time"] for s in services.consultation_slots(conn, d, mode, current, policy) if s["available"]]
        if free:
            out[d.isoformat()] = free
    return out


def _require_slot(conn, d: date, time_str: str, mode: str, current, policy, exclude_code: str | None = None) -> None:
    cfg = policy["consultation"]
    valid_times = cfg["onsite_slots"] if mode == "onsite" else cfg["slots"]
    if time_str not in valid_times:
        raise ApiError(422, "INVALID_CONSULT_TIME", f"Giờ hẹn phải là một trong: {', '.join(valid_times)}.")
    table = services.consultation_slots(conn, d, mode, current, policy, exclude_code)
    chosen = next(s for s in table if s["time"] == time_str)
    if not chosen["available"]:
        raise ApiError(409, "CONSULT_SLOT_UNAVAILABLE", f"Giờ {time_str} ngày {d:%d/%m/%Y} không khả dụng: {chosen['reason']}",
                       {"same_day": [s["time"] for s in table if s["available"]],
                        "next_open_days": _next_open_days(conn, d, mode, current, policy)})


@router.get("/availability", summary="Giờ tư vấn còn trống trong 1 ngày")
def availability(date_: date = Query(..., alias="date"), mode: str = Query("studio", pattern="^(studio|online|onsite)$"),
                 conn=Depends(get_db)):
    current, policy = now(), get_policy()
    return {"date": date_.isoformat(), "date_label": date_vi(date_), "mode": mode,
            "mode_label": labels.CONSULT_MODE[mode], "slots": services.consultation_slots(conn, date_, mode, current, policy),
            "onsite_fee": policy["consultation"]["onsite_fee_vnd"] if mode == "onsite" else 0}


@router.post("", status_code=201, summary="Đặt lịch tư vấn (miễn phí; khảo sát tận nơi 300.000đ)")
def create(body: ConsultationIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    cfg = policy["consultation"]
    warnings = []
    with conn:
        phone = repo.require_phone(body.customer.phone)
        zone = None
        if body.mode == "onsite":
            zone = repo.get_zone(conn, body.zone_id)
            if not zone or zone["id"] not in cfg["onsite_zones"]:
                raise ApiError(422, "ONSITE_ZONE_NOT_SUPPORTED",
                               f"Khảo sát tận nơi chỉ áp dụng khu vực {', '.join(cfg['onsite_zones'])}; khu vực khác chọn tư vấn online.")
            if not body.venue:
                raise ApiError(422, "VENUE_REQUIRED", "Khảo sát tận nơi cần địa chỉ địa điểm tổ chức.")
        _require_slot(conn, body.appointment_date, body.appointment_time, body.mode, current, policy)
        min_gap = cfg["min_days_between_appointment_and_event"]
        if (body.event_date - body.appointment_date).days < min_gap:
            raise ApiError(422, "EVENT_TOO_SOON", f"Ngày sự kiện phải sau buổi tư vấn tối thiểu {min_gap} ngày; "
                                                  "nhu cầu gấp vui lòng gọi hotline để studio xem khả năng nhận.")
        if body.event_type == "wedding" and (body.event_date - current.date()).days < cfg["recommended_days_before_wedding"]:
            warnings.append("Tiệc cưới còn dưới 30 ngày: một số loại hoa nhập khẩu có thể không kịp đặt.")
        busy = {c["consultant"] for c in repo.many(conn, "SELECT consultant FROM consultations WHERE appointment_date = ? "
                                                         "AND appointment_time = ? AND status = 'scheduled'",
                                                   (body.appointment_date.isoformat(), body.appointment_time))}
        consultant = next(c for c in CONSULTANTS if c not in busy)
        customer = repo.upsert_customer(conn, body.customer.full_name, phone, body.customer.email, current)
        code = repo.next_code(conn, "consultations", "TV", 2001)
        fee = cfg["onsite_fee_vnd"] if body.mode == "onsite" else 0
        conn.execute(
            "INSERT INTO consultations (code, customer_id, event_type, mode, appointment_date, appointment_time, "
            "event_date, venue, zone_id, guest_count, budget_range, status, consultant, onsite_fee, note, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?)",
            (code, customer["id"], body.event_type, body.mode, body.appointment_date.isoformat(), body.appointment_time,
             body.event_date.isoformat(), body.venue, zone["id"] if zone else None, body.guest_count, body.budget_range,
             consultant, fee, body.note, iso(current), iso(current)),
        )
        c = repo.one(conn, "SELECT * FROM consultations WHERE code = ?", (code,))
    where = {"studio": "studio tầng 2, 86 Trần Văn Hoài, phường Ninh Kiều",
             "online": "gọi video qua Zalo, link gửi trước 30 phút",
             "onsite": f"tại {body.venue}, phí khảo sát {vnd(fee)} (trừ vào hợp đồng nếu ký)"}[body.mode]
    return {"consultation": services.consultation_view(conn, c, current, policy), "warnings": warnings,
            "message": f"Đã đặt lịch tư vấn {code}: {date_vi(body.appointment_date)} lúc {body.appointment_time}, {where}."}


@router.get("/{code}", summary="Tra lịch tư vấn theo mã + SĐT")
def lookup(code: str, phone: str = Query(...), conn=Depends(get_db)):
    c = repo.find_consultation_for_phone(conn, code, phone)
    return {"consultation": services.consultation_view(conn, c, now(), get_policy())}


@router.post("/{code}/reschedule", summary="Đổi giờ hẹn tư vấn (miễn phí nếu còn ≥ 12 giờ)")
def reschedule(code: str, body: ConsultRescheduleIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        c = repo.find_consultation_for_phone(conn, code, body.phone)
        check = rules.consult_reschedule_check(c, current, policy)
        if not check["allowed"]:
            raise ApiError(409, "RESCHEDULE_NOT_ALLOWED", check["reason"], check)
        _require_slot(conn, body.new_date, body.new_time, c["mode"], current, policy, exclude_code=c["code"])
        if check["requires_approval"]:
            req = repo.insert_request(conn, type="reschedule", customer_id=c["customer_id"], ref_type="consultation",
                                      ref_code=c["code"], reason_code="consult_reschedule_outside_policy",
                                      description=body.reason, amount=None,
                                      payload={"new_date": body.new_date.isoformat(), "new_time": body.new_time},
                                      status="pending_approval", approval_rules=check["approval_rules"],
                                      created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "policy_check": check, "request": services.request_view(req),
                    "message": services.pending_message(req)}
        services.apply_consult_reschedule(conn, c, new_date=body.new_date, new_time=body.new_time, now=current)
        updated = repo.one(conn, "SELECT * FROM consultations WHERE code = ?", (c["code"],))
    return {"result": "rescheduled", "policy_check": check,
            "consultation": services.consultation_view(conn, updated, current, policy),
            "message": f"Đã đổi lịch tư vấn {c['code']} sang {date_vi(body.new_date)} lúc {body.new_time}."}


@router.post("/{code}/cancel", summary="Huỷ lịch tư vấn / huỷ hợp đồng (hoàn cọc luôn cần duyệt)")
def cancel(code: str, body: CancelIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        c = repo.find_consultation_for_phone(conn, code, body.phone)
        preview = rules.consult_cancel_preview(c, current.date(), policy)
        if not preview["allowed"]:
            raise ApiError(409, "NOT_CANCELLABLE", preview["reason"], preview)
        if body.dry_run:
            return {"result": "preview", "dry_run": True, "preview": preview}
        if preview["requires_approval"]:
            req = repo.insert_request(conn, type="cancellation", customer_id=c["customer_id"], ref_type="consultation",
                                      ref_code=c["code"], reason_code="contract_cancellation", description=body.reason,
                                      amount=preview["refund_amount"], payload={"preview": preview},
                                      status="pending_approval", approval_rules=preview["approval_rules"],
                                      created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "preview": preview, "request": services.request_view(req),
                    "message": services.pending_message(req)}
        services.apply_consult_cancel(conn, c, refund_amount=0, reason=body.reason, now=current)
    return {"result": "cancelled", "preview": preview, "message": f"Đã huỷ lịch tư vấn {c['code']}."}


@router.post("/{code}/change-event-date", summary="Đổi ngày sự kiện đã ký hợp đồng (miễn phí 1 lần nếu còn ≥ 15 ngày)")
def change_event_date(code: str, body: EventDateChangeIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        c = repo.find_consultation_for_phone(conn, code, body.phone)
        check = rules.event_date_change_check(c, current.date(), policy)
        if not check["allowed"]:
            raise ApiError(409, "EVENT_DATE_CHANGE_NOT_ALLOWED", check["reason"], check)
        if (body.new_event_date - current.date()).days < policy["consultation"]["min_days_between_appointment_and_event"]:
            raise ApiError(422, "EVENT_TOO_SOON", "Ngày sự kiện mới cần cách hôm nay tối thiểu 7 ngày.")
        if check["requires_approval"]:
            req = repo.insert_request(conn, type="reschedule", customer_id=c["customer_id"], ref_type="consultation",
                                      ref_code=c["code"], reason_code="event_date_change", description=body.reason,
                                      amount=None, payload={"action": "change_event_date",
                                                            "new_event_date": body.new_event_date.isoformat()},
                                      status="pending_approval", approval_rules=check["approval_rules"],
                                      created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "policy_check": check, "request": services.request_view(req),
                    "message": services.pending_message(req)}
        services.apply_event_date_change(conn, c, new_event_date=body.new_event_date, now=current)
    return {"result": "event_date_changed", "policy_check": check,
            "message": f"Đã đổi ngày sự kiện của {c['code']} sang {date_vi(body.new_event_date)}; "
                       "tư vấn viên sẽ xác nhận lại nguồn hoa trong 24 giờ."}
