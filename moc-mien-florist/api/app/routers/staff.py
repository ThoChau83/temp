"""Endpoint nội bộ cho nhân viên/quản lý (header X-Staff-Key).

Dùng để mô phỏng vòng duyệt human-in-the-loop: agent tạo yêu cầu "chờ duyệt",
quản lý approve/reject, sau đó "complete" khi đã chuyển tiền / giao lại xong.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from .. import repo, services
from ..config import settings
from ..db import get_db, many
from ..errors import ApiError
from ..policy import get_policy
from ..schemas import StaffDecisionIn
from ..utils import iso, now, vnd


def require_staff(x_staff_key: str = Header(..., description="Khoá nhân viên (STAFF_KEY)")) -> None:
    if x_staff_key != settings.staff_key:
        raise ApiError(401, "STAFF_UNAUTHORIZED", "Sai khoá nhân viên.")


router = APIRouter(prefix="/staff", tags=["Nội bộ nhân viên"], dependencies=[Depends(require_staff)])


def _recompute_payment_status(conn, order_code: str) -> None:
    o = repo.get_order(conn, order_code)
    if repo.open_refund_total(conn, order_code) > 0:
        status = "refund_pending"
    elif o["refunded_amount"] > 0:
        status = "refunded" if o["refunded_amount"] >= o["paid_amount"] else "partially_refunded"
    elif o["paid_amount"] >= o["total"]:
        status = "paid"
    elif o["paid_amount"] > 0:
        status = "partially_paid"
    else:
        status = "unpaid"
    conn.execute("UPDATE orders SET payment_status = ? WHERE code = ?", (status, order_code))


def _decide(conn, req: dict, status: str, staff: str, note: str | None, current, **extra) -> None:
    sets = ["status = ?", "decided_at = ?", "decided_by = ?", "resolution_note = COALESCE(?, resolution_note)"]
    params = [status, iso(current), staff, note]
    for k, v in extra.items():
        sets.append(f"{k} = ?")
        params.append(v)
    conn.execute(f"UPDATE service_requests SET {', '.join(sets)} WHERE code = ?", (*params, req["code"]))


@router.get("/requests", summary="Danh sách yêu cầu (lọc theo trạng thái / loại)")
def list_requests(status: str | None = Query(None, description="pending_approval | approved | open | ..."),
                  type: str | None = None, limit: int = Query(50, le=500), conn=Depends(get_db)):
    sql, params = "SELECT * FROM service_requests WHERE 1 = 1", []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if type:
        sql += " AND type = ?"
        params.append(type)
    rows = many(conn, sql + " ORDER BY created_at DESC, code DESC LIMIT ?", (*params, limit))
    return {"count": len(rows), "requests": [services.request_view(r) for r in rows]}


@router.post("/requests/{code}/decision", summary="Duyệt / từ chối / hoàn tất một yêu cầu")
def decide(code: str, body: StaffDecisionIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        req = repo.get_request(conn, code)
        if not req:
            raise ApiError(404, "REQUEST_NOT_FOUND", "Không có yêu cầu này.")
        payload = json.loads(req["payload"]) if req["payload"] else {}
        kind, ref = req["type"], req["ref_type"]

        if body.decision == "reject":
            if req["status"] not in ("pending_approval", "open", "approved"):
                raise ApiError(409, "ALREADY_DECIDED", f"Yêu cầu đang ở trạng thái {req['status']}.")
            _decide(conn, req, "rejected", body.staff_name, body.note, current)
            if ref == "order" and kind in ("refund", "cancellation"):
                _recompute_payment_status(conn, req["ref_code"])

        elif body.decision == "approve":
            if req["status"] not in ("pending_approval", "open"):
                raise ApiError(409, "ALREADY_DECIDED", f"Yêu cầu đang ở trạng thái {req['status']}.")
            amount = body.approved_amount if body.approved_amount is not None else (req["amount"] or 0)
            new_status, extra = "approved", {}
            if kind == "refund":
                extra["amount"] = amount
            elif kind == "exchange":
                pass
            elif kind == "discount":
                issued = services.issue_goodwill_code(
                    conn, customer_id=req["customer_id"], percent=payload.get("percent") if body.approved_amount is None else None,
                    amount=payload.get("amount") if body.approved_amount is None else body.approved_amount,
                    now=current, policy=policy, created_by="staff",
                    max_discount=None if payload.get("amount") else 200000)
                new_status, extra["issued_code"] = "completed", issued["code"]
            elif kind == "cancellation" and ref == "order":
                order = repo.get_order(conn, req["ref_code"])
                services.perform_cancel(conn, order, refund_amount=amount, reason=req["description"] or "Huỷ theo duyệt",
                                        actor="staff", now=current, policy=policy, approved_by=body.staff_name)
                new_status, extra["amount"] = "completed", amount
            elif kind == "cancellation" and ref == "consultation":
                c = repo.one(conn, "SELECT * FROM consultations WHERE code = ?", (req["ref_code"],))
                services.apply_consult_cancel(conn, c, refund_amount=amount, reason=req["description"], now=current)
                extra["amount"] = amount
                if amount == 0:
                    new_status = "completed"
            elif kind == "cancellation" and ref == "subscription":
                sub = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (req["ref_code"],))
                services.apply_sub_cancel(conn, sub, refund_amount=amount, reason=req["description"], now=current,
                                          policy=policy, actor="staff", approved_by=body.staff_name)
                new_status, extra["amount"] = "completed", amount
            elif kind == "reschedule" and ref == "order":
                order = repo.get_order(conn, req["ref_code"])
                branch = repo.get_branch(conn, payload["branch_id"])
                if repo.slot_load(conn, branch["id"], payload["new_date"], payload["new_slot_code"], order["code"]) >= branch["slot_capacity"]:
                    raise ApiError(409, "SLOT_FULL", "Khung giờ khách chọn đã kín, cần liên hệ khách chọn khung khác.")
                services.apply_reschedule(conn, order, new_date=date.fromisoformat(payload["new_date"]),
                                          slot_code=payload["new_slot_code"], branch_id=branch["id"],
                                          mode=payload.get("mode", "reschedule"), actor="staff", now=current,
                                          policy=policy, reason=f"Duyệt bởi {body.staff_name}")
                new_status = "completed"
            elif kind == "reschedule" and ref == "consultation":
                c = repo.one(conn, "SELECT * FROM consultations WHERE code = ?", (req["ref_code"],))
                if payload.get("action") == "change_event_date":
                    services.apply_event_date_change(conn, c, new_event_date=date.fromisoformat(payload["new_event_date"]), now=current)
                else:
                    services.apply_consult_reschedule(conn, c, new_date=date.fromisoformat(payload["new_date"]),
                                                      new_time=payload["new_time"], now=current)
                new_status = "completed"
            elif kind == "reschedule" and ref == "subscription":
                sub = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (req["ref_code"],))
                services.apply_sub_pause(conn, sub, resume_date=date.fromisoformat(payload["resume_date"]), now=current)
                new_status = "completed"
            elif kind == "escalation":
                new_status = "closed"
            _decide(conn, req, new_status, body.staff_name, body.note, current, **extra)

        else:  # complete
            if req["status"] != "approved":
                raise ApiError(409, "NOT_APPROVED", "Chỉ hoàn tất được yêu cầu đã duyệt.")
            if kind == "refund" and ref == "order":
                order = repo.get_order(conn, req["ref_code"])
                _decide(conn, req, "completed", body.staff_name, body.note, current)
                refunded = order["refunded_amount"] + req["amount"]
                conn.execute("UPDATE orders SET refunded_amount = ?, updated_at = ? WHERE code = ?",
                             (refunded, iso(current), order["code"]))
                if order["status"] == "delivered" and refunded >= order["paid_amount"]:
                    conn.execute("UPDATE orders SET status = 'refunded' WHERE code = ?", (order["code"],))
                    repo.log_order_event(conn, order["code"], "status_changed", current, from_status="delivered",
                                         to_status="refunded", detail=f"Hoàn {vnd(req['amount'])}", actor="staff")
                _recompute_payment_status(conn, order["code"])
            elif kind == "cancellation" and ref == "consultation":
                c = repo.one(conn, "SELECT * FROM consultations WHERE code = ?", (req["ref_code"],))
                status = "refunded" if req["amount"] >= c["deposit_amount"] else "partially_refunded"
                conn.execute("UPDATE consultations SET deposit_status = ?, updated_at = ? WHERE code = ?",
                             (status, iso(current), c["code"]))
                _decide(conn, req, "completed", body.staff_name, body.note, current)
            else:
                _decide(conn, req, "completed", body.staff_name, body.note, current)
        updated = repo.get_request(conn, code)
    return {"request": services.request_view(updated)}


class PaymentIn(BaseModel):
    amount: int = Field(..., gt=0)


class StatusIn(BaseModel):
    status: str = Field(..., pattern="^(confirmed|arranging|delivering|delivered|failed_delivery)$")
    note: str | None = None


@router.post("/orders/{code}/payment", summary="Ghi nhận khách đã thanh toán (mô phỏng)")
def record_payment(code: str, body: PaymentIn, conn=Depends(get_db)):
    current = now()
    with conn:
        order = repo.get_order(conn, code)
        if not order:
            raise ApiError(404, "ORDER_NOT_FOUND", "Không có đơn này.")
        paid = min(order["paid_amount"] + body.amount, order["total"])
        conn.execute("UPDATE orders SET paid_amount = ?, updated_at = ? WHERE code = ?", (paid, iso(current), code))
        if order["status"] == "pending":
            conn.execute("UPDATE orders SET status = 'confirmed' WHERE code = ?", (order["code"],))
            repo.log_order_event(conn, order["code"], "status_changed", current, from_status="pending",
                                 to_status="confirmed", detail=f"Nhận thanh toán {vnd(body.amount)}", actor="staff")
        _recompute_payment_status(conn, order["code"])
        updated = repo.get_order(conn, order["code"])
    return {"order": services.order_view(conn, updated, current, get_policy(), detail=False)}


@router.post("/orders/{code}/status", summary="Chuyển trạng thái đơn (mô phỏng vận hành)")
def set_status(code: str, body: StatusIn, conn=Depends(get_db)):
    current = now()
    with conn:
        order = repo.get_order(conn, code)
        if not order:
            raise ApiError(404, "ORDER_NOT_FOUND", "Không có đơn này.")
        delivered_at = iso(current) if body.status == "delivered" else order["delivered_at"]
        paid = order["total"] if body.status == "delivered" and order["payment_method"] == "cod" else order["paid_amount"]
        conn.execute("UPDATE orders SET status = ?, delivered_at = ?, paid_amount = ?, updated_at = ? WHERE code = ?",
                     (body.status, delivered_at, paid, iso(current), code))
        repo.log_order_event(conn, order["code"], "status_changed", current, from_status=order["status"],
                             to_status=body.status, detail=body.note, actor="staff")
        _recompute_payment_status(conn, order["code"])
        updated = repo.get_order(conn, order["code"])
    return {"order": services.order_view(conn, updated, current, get_policy(), detail=False)}


@router.post("/subscriptions/{code}/payment", summary="Ghi nhận thanh toán gói định kỳ → kích hoạt")
def subscription_payment(code: str, body: PaymentIn, conn=Depends(get_db)):
    current = now()
    with conn:
        sub = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (code.upper(),))
        if not sub:
            raise ApiError(404, "SUBSCRIPTION_NOT_FOUND", "Không có gói này.")
        paid = min(sub["paid_amount"] + body.amount, sub["price_total"])
        status = "active" if paid >= sub["price_total"] and sub["status"] == "pending_payment" else sub["status"]
        conn.execute("UPDATE subscriptions SET paid_amount = ?, status = ?, updated_at = ? WHERE code = ?",
                     (paid, status, iso(current), sub["code"]))
        updated = repo.one(conn, "SELECT * FROM subscriptions WHERE code = ?", (sub["code"],))
    return {"subscription": services.subscription_view(conn, updated, current, get_policy())}
