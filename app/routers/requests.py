"""Ghi nhận yêu cầu: hoàn tiền, đổi trả, mã giảm giá (mã xin lỗi), chuyển nhân viên."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response

from .. import repo, rules, services
from ..db import get_db
from ..errors import ApiError, not_found_or_mismatch
from ..policy import approval_rule, get_policy
from ..schemas import DiscountRequestIn, EscalateIn, ExchangeIn, ItemIn, RefundIn
from ..utils import iso, normalize_phone, now, vnd

router = APIRouter(prefix="/requests", tags=["Yêu cầu hoàn tiền / đổi trả / giảm giá"])


def _result(req: dict, response: Response, extra: dict | None = None) -> dict:
    pending = req["status"] == "pending_approval"
    if pending:
        response.status_code = 202
    body = {"result": req["status"], "request": services.request_view(req),
            "message": services.pending_message(req) if pending else None}
    body.update(extra or {})
    return body


@router.post("/refund", status_code=201, summary="Ghi nhận yêu cầu hoàn tiền (tự duyệt nếu ≤ ngưỡng và đúng điều kiện)")
def refund(body: RefundIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        order = repo.find_order_for_phone(conn, body.order_code, body.phone)
        items = repo.order_items(conn, order["code"])
        refundable = order["paid_amount"] - order["refunded_amount"] - repo.open_refund_total(conn, order["code"])
        assessment = rules.refund_assessment(order, items, repo.slots_by_code(conn), current, policy,
                                             reason_code=body.reason_code, amount=body.amount, refundable=refundable,
                                             has_evidence=bool(body.evidence_urls))
        if not assessment["eligible"]:
            raise ApiError(409 if assessment.get("error") != "AMOUNT_EXCEEDS_REFUNDABLE" else 422,
                           assessment.get("error", "REFUND_NOT_ELIGIBLE"), assessment["reason"], assessment)
        req = services.create_refund_request(
            conn, order=order, amount=assessment["amount"], reason_code=body.reason_code,
            refund_method=body.refund_method, description=body.description, evidence_urls=body.evidence_urls,
            approval_rules=assessment["approval_rules"], created_by=body.actor, now=current, policy=policy,
            extra={"assessment_notes": assessment["notes"]})
    extra = {"assessment": assessment}
    if req["status"] == "approved":
        days = services.refund_processing_days(order["payment_method"], body.refund_method, policy)
        extra["message"] = (f"Đã duyệt hoàn {vnd(req['amount'])} cho đơn {order['code']} (mã yêu cầu {req['code']}); "
                            f"tiền về trong khoảng {days} ngày làm việc.")
    return _result(req, response, extra)


@router.post("/exchange", status_code=201, summary="Ghi nhận yêu cầu đổi trả / bảo hành độ tươi")
def exchange(body: ExchangeIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        order = repo.find_order_for_phone(conn, body.order_code, body.phone)
        items = {i["sku"]: i for i in repo.order_items(conn, order["code"])}
        wanted = body.items or [ItemIn(sku=s, quantity=i["quantity"]) for s, i in items.items()]
        lines = []
        for w in wanted:
            sku = w.sku.strip().upper()
            if sku not in items:
                raise ApiError(422, "ITEM_NOT_IN_ORDER", f"Sản phẩm {sku} không có trong đơn {order['code']}.")
            if w.quantity > items[sku]["quantity"]:
                raise ApiError(422, "QUANTITY_EXCEEDS_ORDER", f"Đơn chỉ có {items[sku]['quantity']} {sku}.")
            line = dict(items[sku])
            line["quantity"] = w.quantity
            line["line_total"] = items[sku]["unit_price"] * w.quantity
            lines.append(line)
        assessment = rules.exchange_assessment(order, lines, current, policy, reason_code=body.reason_code,
                                               has_evidence=bool(body.evidence_urls))
        value = sum(l["line_total"] for l in lines)
        approval = list(assessment.get("approval_rules", []))
        if assessment["eligible"] and body.resolution == "refund" and value > policy["refund"]["auto_approve_max_vnd"]:
            approval.append("APR-01")
        payload = {"items": [{"sku": l["sku"], "quantity": l["quantity"], "line_total": l["line_total"]} for l in lines],
                   "resolution": body.resolution, "evidence_urls": body.evidence_urls,
                   "assessment": {k: assessment.get(k) for k in ("items", "notes", "hours_since_delivery")}}
        if not assessment["eligible"]:
            status, note = "rejected", assessment["reason"]
        else:
            status, note = ("pending_approval" if approval else "approved"), None
        req = repo.insert_request(conn, type="exchange", customer_id=order["customer_id"], ref_type="order",
                                  ref_code=order["code"], reason_code=body.reason_code, description=body.description,
                                  amount=value, payload=payload, status=status, approval_rules=approval,
                                  created_by=body.actor, now=current, resolution_note=note)
        if status == "rejected":
            conn.execute("UPDATE service_requests SET decided_at = ?, decided_by = 'system' WHERE code = ?",
                         (iso(current), req["code"]))
            req = repo.get_request(conn, req["code"])
    extra = {"assessment": assessment}
    if status == "approved":
        extra["message"] = {
            "redeliver_same": "Đã duyệt giao lại sản phẩm tương đương miễn phí trong vòng 3 giờ (REF-05); nhân viên sẽ gọi xác nhận khung giờ.",
            "replace_other": "Đã duyệt đổi sang mẫu khác cùng giá trị; nhân viên sẽ gọi để chọn mẫu.",
            "refund": f"Đã duyệt hoàn {vnd(value)} theo yêu cầu đổi trả.",
            "store_credit": f"Đã duyệt cộng {vnd(value + value // 10)} vào ví Mộc Miên (giá trị + 10%, REF-05).",
        }[body.resolution]
    elif status == "rejected":
        extra["message"] = f"Yêu cầu không đủ điều kiện đổi trả: {assessment['reason']}"
    return _result(req, response, extra)


@router.post("/discount", status_code=201, summary="Đề xuất / cấp mã giảm giá xin lỗi (≤10% và ≤100.000đ tự cấp)")
def discount(body: DiscountRequestIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    cfg = policy["discount"]
    with conn:
        phone = repo.require_phone(body.phone)
        if body.order_code:
            order = repo.find_order_for_phone(conn, body.order_code, phone)
            customer = repo.get_customer(conn, order["customer_id"])
        else:
            customer = repo.get_customer_by_phone(conn, phone)
            if not customer:
                raise ApiError(404, "CUSTOMER_NOT_FOUND", "Chưa có khách hàng với số điện thoại này.")
        approval, notes = [], []
        if body.percent and body.percent > cfg["agent_max_percent"]:
            approval.append("APR-02")
            notes.append(f"Mức {body.percent}% vượt giới hạn agent {cfg['agent_max_percent']}% (DSC-02).")
        if body.amount and body.amount > cfg["agent_max_amount_vnd"]:
            approval.append("APR-02")
            notes.append(f"Mức {vnd(body.amount)} vượt giới hạn agent {vnd(cfg['agent_max_amount_vnd'])} (DSC-02).")
        if body.reason_code not in cfg["allowed_reasons"]:
            approval.append("APR-02")
            notes.append("Lý do không thuộc danh sách được tự cấp mã.")
        since = iso(current - timedelta(days=90))
        issued_90d = repo.goodwill_codes_since(conn, customer["id"], since)
        if issued_90d >= cfg["max_goodwill_codes_per_customer_90_days"]:
            approval.append("APR-02")
            notes.append(f"Khách đã nhận {issued_90d} mã xin lỗi trong 90 ngày (tối đa {cfg['max_goodwill_codes_per_customer_90_days']}).")
        payload = {"percent": body.percent, "amount": body.amount, "order_code": body.order_code, "notes": notes,
                   "goodwill_codes_last_90_days": issued_90d}
        issued = None
        if not approval:
            issued = services.issue_goodwill_code(conn, customer_id=customer["id"], percent=body.percent,
                                                  amount=body.amount, now=current, policy=policy, created_by=body.actor)
        req = repo.insert_request(conn, type="discount", customer_id=customer["id"],
                                  ref_type="order" if body.order_code else None,
                                  ref_code=body.order_code.upper() if body.order_code else None,
                                  reason_code=body.reason_code, description=body.description,
                                  amount=body.amount or body.percent, payload=payload,
                                  status="pending_approval" if approval else "completed",
                                  approval_rules=list(dict.fromkeys(approval)), created_by=body.actor, now=current,
                                  issued_code=issued["code"] if issued else None)
    extra = {"notes": notes}
    if issued:
        extra["issued_code"] = issued
        extra["message"] = f"Đã cấp mã {issued['code']}: {issued['description']}, dùng đến hết ngày {issued['valid_to']}."
    return _result(req, response, extra)


@router.post("/escalate", status_code=201, summary="Chuyển nhân viên / quản lý xử lý")
def escalate(body: EscalateIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        phone = repo.require_phone(body.phone)
        customer = repo.get_customer_by_phone(conn, phone)
        if body.ref_type and body.ref_code:
            finder = {"order": repo.find_order_for_phone, "consultation": repo.find_consultation_for_phone,
                      "subscription": repo.find_subscription_for_phone}[body.ref_type]
            finder(conn, body.ref_code, phone)
        rule_ids = []
        if body.approval_rule:
            try:
                approval_rule(body.approval_rule)
            except KeyError:
                raise ApiError(422, "UNKNOWN_RULE", f"Không có quy tắc {body.approval_rule} trong policy.yaml.")
            rule_ids = [body.approval_rule]
        req = repo.insert_request(conn, type="escalation", customer_id=customer["id"] if customer else None,
                                  ref_type=body.ref_type, ref_code=body.ref_code.upper() if body.ref_code else None,
                                  reason_code=body.topic, description=body.summary, amount=None,
                                  payload={"contact_phone": phone}, status="open", approval_rules=rule_ids,
                                  created_by=body.actor, now=current)
    sla = approval_rule(rule_ids[0])["sla_hours"] if rule_ids else 4
    return {"result": "open", "request": services.request_view(req),
            "message": f"Đã chuyển yêu cầu {req['code']} cho nhân viên; Mộc Miên sẽ liên hệ lại trong khoảng {sla} giờ "
                       f"làm việc (07:00–21:00). Hotline: {policy['meta']['hotline']}."}


@router.get("/{code}", summary="Tra trạng thái yêu cầu theo mã + SĐT")
def get_request(code: str, phone: str = Query(...), conn=Depends(get_db)):
    req = repo.get_request(conn, code)
    p = normalize_phone(phone)
    if not req or not p:
        raise not_found_or_mismatch("request")
    customer = repo.get_customer(conn, req["customer_id"]) if req["customer_id"] else None
    if not customer or customer["phone"] != p:
        raise not_found_or_mismatch("request")
    return {"request": services.request_view(req)}
