"""Đơn hoa giao theo khung giờ: báo giá, tạo đơn, tra cứu (mã + SĐT), đổi lịch / giao lại, huỷ."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response

from .. import repo, rules, services
from ..db import get_db, one
from ..errors import ApiError
from ..policy import get_policy
from ..pricing import choose_discount, evaluate_code, shipping_fee, tier_discount
from ..schemas import CancelIn, OrderIn, OrderRescheduleIn
from ..utils import date_vi, iso, is_peak_day, mask_phone, normalize_phone, now, vnd

router = APIRouter(prefix="/orders", tags=["Đơn hàng"])


def _code_usage(conn, customer: dict | None, code: str) -> dict:
    if not customer:
        return {"customer_used": 0, "customer_prior_orders": 0}
    used = one(conn, "SELECT COUNT(*) AS n FROM orders WHERE customer_id = ? AND discount_code = ? "
                     "AND discount_source = 'code' AND status != 'cancelled'", (customer["id"], code))["n"]
    return {"customer_used": used, "customer_prior_orders": repo.customer_order_count(conn, customer["id"])}


def _bulk_lead(lines: list[dict], policy: dict) -> int:
    """ORD-07: từ 10 sản phẩm cùng mẫu (trừ hoa lẻ, phụ kiện) cần đặt trước 48 giờ."""
    cfg = policy["ordering"]["bulk_order"]
    bulky = any(l["quantity"] >= cfg["min_same_item_quantity"] and l["category"] not in cfg["excluded_categories"]
                for l in lines)
    return cfg["lead_time_hours"] if bulky else 0


def build_order_plan(conn, body: OrderIn, current, policy: dict) -> dict:
    phone = repo.require_phone(body.customer.phone)
    customer = repo.get_customer_by_phone(conn, phone)
    tier = customer["tier"] if customer else "member"
    warnings: list[str] = []

    # --- sản phẩm
    merged: dict[str, int] = {}
    for it in body.items:
        sku = it.sku.strip().upper()
        merged[sku] = merged.get(sku, 0) + it.quantity
    products, lines = [], []
    for sku, qty in merged.items():
        p = repo.get_product(conn, sku)
        if not p or not p["is_active"]:
            raise ApiError(404, "PRODUCT_NOT_FOUND", f"Không có sản phẩm mã {sku}.")
        products.append(p)
        lines.append({"sku": sku, "product_name": p["name"], "category": p["category"], "quantity": qty,
                      "unit_price": p["price"], "line_total": p["price"] * qty, "lead_time_hours": p["lead_time_hours"]})
    subtotal = sum(l["line_total"] for l in lines)
    max_lead = max(p["lead_time_hours"] for p in products)
    is_custom = max_lead >= policy["order_changes"]["cancellation"]["custom_order_lead_time_hours"]
    bulk_lead = _bulk_lead(lines, policy)
    if bulk_lead:
        warnings.append(f"Đơn từ {policy['ordering']['bulk_order']['min_same_item_quantity']} sản phẩm cùng mẫu "
                        f"cần đặt trước {bulk_lead} giờ (ORD-07).")

    # --- hình thức nhận
    zone = None
    recipient_phone = None
    if body.fulfillment == "delivery":
        if body.recipient is None:
            raise ApiError(422, "RECIPIENT_REQUIRED", "Giao tận nơi cần thông tin người nhận (tên, SĐT, địa chỉ, khu vực).")
        recipient_phone = normalize_phone(body.recipient.phone)
        if not recipient_phone:
            raise ApiError(422, "INVALID_RECIPIENT_PHONE", "Số điện thoại người nhận không hợp lệ.")
        zone = repo.get_zone(conn, body.recipient.zone_id)
        if zone is None:
            raise ApiError(409, "OUTSIDE_DELIVERY_ZONE",
                           "Địa chỉ ngoài vùng giao Z1–Z4: cần trưởng ca báo giá ship riêng (APR-06).",
                           {"approval_rule": "APR-06", "next_step": "POST /requests/escalate với topic=outside_zone"})
        if "PK06" in merged and zone["id"] not in ("Z1", "Z2"):
            raise ApiError(422, "PRODUCT_ZONE_RESTRICTED", "Bóng bay chữ (PK06) chỉ giao vùng Z1–Z2.")
    else:
        if not body.branch_id or not repo.get_branch(conn, body.branch_id):
            raise ApiError(422, "BRANCH_REQUIRED", "Nhận tại cửa hàng cần chọn chi nhánh CN01 hoặc CN02.")
        if body.express:
            raise ApiError(422, "EXPRESS_DELIVERY_ONLY", "Giao hỏa tốc chỉ áp dụng cho giao tận nơi.")

    # --- thời gian
    express_fee = 0
    express_deadline = None
    if body.express:
        cfg = policy["ordering"]["express"]
        reasons = []
        if zone["id"] not in cfg["zones"]:
            reasons.append(f"chỉ áp dụng khu vực {', '.join(cfg['zones'])}")
        if cfg["disabled_on_peak_days"] and is_peak_day(current.date(), policy):
            reasons.append("không áp dụng ngày cao điểm")
        if not (cfg["start"] <= current.strftime("%H:%M") <= cfg["end"]):
            reasons.append(f"chỉ nhận từ {cfg['start']} đến {cfg['end']}")
        slow = [p["sku"] for p in products if p["lead_time_hours"] > cfg["only_ready_products_max_lead_time_hours"]]
        if slow:
            reasons.append(f"sản phẩm {', '.join(slow)} cần thời gian chuẩn bị dài")
        bulky = [p["sku"] for p in products if p["category"] in cfg["excluded_categories"]]
        if bulky:
            reasons.append(f"kệ/vòng hoa ({', '.join(bulky)}) không giao hỏa tốc")
        if bulk_lead:
            reasons.append("đơn số lượng lớn cần đặt trước 48 giờ")
        if reasons:
            raise ApiError(409, "EXPRESS_UNAVAILABLE", "Không giao hỏa tốc được: " + "; ".join(reasons) + " (ORD-03).")
        branch = repo.get_branch(conn, body.branch_id or zone["default_branch_id"])
        delivery_date, slot = current.date(), None
        express_fee = cfg["fee"]
        express_deadline = current + timedelta(hours=cfg["max_hours"])
    else:
        if not body.delivery_date or not body.slot_code:
            raise ApiError(422, "DATE_AND_SLOT_REQUIRED", "Cần ngày giao (delivery_date) và khung giờ (slot_code).")
        branch, slot = services.validate_slot(conn, zone=zone, fulfillment=body.fulfillment, branch_id=body.branch_id,
                                              d=body.delivery_date, slot_code=body.slot_code, products=products,
                                              now=current, policy=policy, min_lead_hours=bulk_lead)
        delivery_date = body.delivery_date

    # --- tồn kho
    shortages = []
    for line in lines:
        available = repo.stock(conn, line["sku"], branch["id"])
        if available < line["quantity"]:
            p = next(x for x in products if x["sku"] == line["sku"])
            shortages.append({"sku": line["sku"], "name": line["product_name"], "requested": line["quantity"],
                              "available_at_branch": available, "available_by_branch": repo.stock_by_branch(conn, line["sku"]),
                              "season_note": p["season_note"]})
    if shortages:
        raise ApiError(409, "OUT_OF_STOCK", f"Chi nhánh {branch['id']} không đủ hàng cho một số sản phẩm.",
                       {"branch_id": branch["id"], "shortages": shortages})

    # --- giá
    ship = shipping_fee(zone, subtotal, tier, policy) if body.fulfillment == "delivery" else 0
    tier_amount = tier_discount(subtotal, tier, policy)
    code_amount, code_error, code = 0, None, None
    if body.discount_code:
        code = body.discount_code.strip().upper()
        row = one(conn, "SELECT * FROM discount_codes WHERE code = ?", (code,))
        if not row:
            code_error = {"code": "CODE_NOT_FOUND", "message": "Mã giảm giá không tồn tại (DSC-05)."}
        else:
            amount, err, msg = evaluate_code(row, lines, subtotal, current.date(), customer, _code_usage(conn, customer, code))
            if err:
                code_error = {"code": err, "message": msg}
            else:
                code_amount = amount
    source, discount = choose_discount(code_amount, tier_amount)
    if code_amount and source == "tier":
        warnings.append(f"Ưu đãi hạng thành viên ({vnd(tier_amount)}) có lợi hơn mã {code} ({vnd(code_amount)}); "
                        "mỗi đơn chỉ áp dụng 1 ưu đãi nên hệ thống dùng ưu đãi hạng (DSC-03).")
    if code_error:
        warnings.append(f"Mã {code} không áp dụng được: {code_error['message']}")
    total = subtotal + ship + express_fee - discount

    if total >= 10_000_000:
        raise ApiError(409, "REQUIRES_APPROVAL", "Đơn từ 10.000.000đ cần quản lý cửa hàng duyệt (APR-07).",
                       {"approval_rule": "APR-07", "total": total,
                        "next_step": "POST /requests/escalate với topic=large_order"})

    # --- thanh toán
    pm = body.payment_method
    cod_cfg, pre_cfg = policy["ordering"]["cod"], policy["ordering"]["prepayment"]
    prepay_required = total >= pre_cfg["required_from_vnd"] or is_custom
    if pm == "cod":
        if body.fulfillment != "delivery" or zone["id"] not in cod_cfg["allowed_zones"]:
            raise ApiError(422, "COD_NOT_ALLOWED", f"COD chỉ áp dụng giao tận nơi vùng {', '.join(cod_cfg['allowed_zones'])} (ORD-05).")
        if total >= cod_cfg["below_vnd"] or is_custom:
            raise ApiError(422, "COD_NOT_ALLOWED",
                           f"COD chỉ áp dụng cho đơn dưới {vnd(cod_cfg['below_vnd'])} và không phải đơn đặt riêng (ORD-05, ORD-06).")
    if pm in ("cash", "card") and body.fulfillment != "pickup":
        raise ApiError(422, "PAY_AT_STORE_PICKUP_ONLY", "Tiền mặt/quẹt thẻ tại quầy chỉ dùng khi nhận tại cửa hàng; giao tận nơi chọn COD hoặc chuyển khoản.")
    if prepay_required and pm in ("cash", "card"):
        raise ApiError(422, "PREPAYMENT_REQUIRED",
                       f"Đơn từ {vnd(pre_cfg['required_from_vnd'])} hoặc đơn đặt riêng cần thanh toán trước tối thiểu "
                       f"{pre_cfg['min_percent']}% qua chuyển khoản/MoMo/VNPay (ORD-06).")

    d_label = date_vi(delivery_date)
    if is_peak_day(delivery_date, policy):
        warnings.append("Ngày cao điểm: khung giờ giao có thể lệch ±30 phút và không nhận giao hỏa tốc (ORD-04).")
    if is_custom:
        warnings.append("Đơn đặt riêng (thời gian chuẩn bị ≥ 24 giờ): áp dụng mốc huỷ 72h/24h (CHG-02).")
    warnings.append(policy["ordering"]["natural_variation_note"])

    return {
        "customer": {"exists": customer is not None, "id": customer["id"] if customer else None,
                     "full_name": customer["full_name"] if customer else body.customer.full_name.strip(),
                     "phone": phone, "phone_masked": mask_phone(phone), "tier": tier,
                     "tier_label": policy["loyalty"]["tiers"][tier]["label"]},
        "fulfillment": body.fulfillment,
        "branch": {"id": branch["id"], "name": branch["name"], "address": branch["address"]},
        "zone": {"id": zone["id"], "name": zone["name"]} if zone else None,
        "delivery": {"date": delivery_date.isoformat(), "date_label": d_label,
                     "slot_code": slot["code"] if slot else None,
                     "window": f"{slot['start_time']}–{slot['end_time']}" if slot else
                     f"Hỏa tốc trước {express_deadline:%H:%M}",
                     "is_express": body.express, "express_deadline": iso(express_deadline) if express_deadline else None,
                     "recipient_phone": recipient_phone},
        "items": lines,
        "pricing": {"subtotal": subtotal, "shipping_fee": ship, "express_fee": express_fee,
                    "discount": {"applied_source": source, "code": code if source == "code" else None,
                                 "amount": discount, "tier_discount_available": tier_amount,
                                 "code_discount_available": code_amount, "code_error": code_error},
                    "total": total, "total_label": vnd(total)},
        "payment": {"method": pm, "prepayment_required": prepay_required,
                    "min_prepay_percent": pre_cfg["min_percent"] if prepay_required else None,
                    "initial_status": "confirmed" if pm in ("cod", "cash", "card") else "pending"},
        "is_custom_order": is_custom,
        "warnings": warnings,
    }


@router.post("/quote", summary="Báo giá đơn (không tạo đơn, không giữ khung giờ)")
def quote(body: OrderIn, conn=Depends(get_db)):
    plan = build_order_plan(conn, body, now(), get_policy())
    plan["note"] = "Đây là báo giá, chưa giữ khung giờ và hàng. Gọi POST /orders sau khi khách xác nhận."
    return plan


@router.post("", status_code=201, summary="Tạo đơn hàng (sau khi khách đã xác nhận báo giá)")
def create_order(body: OrderIn, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        plan = build_order_plan(conn, body, current, policy)
        customer = repo.upsert_customer(conn, body.customer.full_name, plan["customer"]["phone"], body.customer.email, current)
        code = repo.next_code(conn, "orders", "MM", 10001)
        pricing, delivery = plan["pricing"], plan["delivery"]
        status = plan["payment"]["initial_status"]
        recipient = body.recipient
        conn.execute(
            "INSERT INTO orders (code, customer_id, branch_id, channel, occasion, status, fulfillment, delivery_date, "
            "slot_code, is_express, express_deadline, zone_id, recipient_name, recipient_phone, delivery_address, "
            "card_message, is_surprise, subtotal, shipping_fee, express_fee, discount_code, discount_source, "
            "discount_amount, total, payment_method, payment_status, paid_amount, refunded_amount, reschedule_count, "
            "note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, 'unpaid', 0, 0, 0, ?, ?, ?)",
            (code, customer["id"], plan["branch"]["id"], body.channel, body.occasion, status, body.fulfillment,
             delivery["date"], delivery["slot_code"], 1 if body.express else 0, delivery["express_deadline"],
             plan["zone"]["id"] if plan["zone"] else None,
             recipient.name if recipient else customer["full_name"],
             delivery["recipient_phone"] or customer["phone"],
             recipient.address if recipient else None, body.card_message, 1 if body.is_surprise else 0,
             pricing["subtotal"], pricing["shipping_fee"], pricing["express_fee"], pricing["discount"]["code"],
             pricing["discount"]["applied_source"], pricing["discount"]["amount"], pricing["total"],
             body.payment_method, body.note, iso(current), iso(current)),
        )
        for line in plan["items"]:
            conn.execute(
                "INSERT INTO order_items (order_code, sku, product_name, quantity, unit_price, line_total) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (code, line["sku"], line["product_name"], line["quantity"], line["unit_price"], line["line_total"]),
            )
            repo.adjust_stock(conn, line["sku"], plan["branch"]["id"], -line["quantity"], current)
        if pricing["discount"]["applied_source"] == "code":
            conn.execute("UPDATE discount_codes SET used_count = used_count + 1 WHERE code = ?", (pricing["discount"]["code"],))
        repo.log_order_event(conn, code, "created", current, to_status=status, actor=body.channel if body.channel == "agent" else "customer",
                             detail=f"Tạo đơn qua kênh {body.channel}.")
        order = repo.get_order(conn, code)
    return {
        "order": services.order_view(conn, order, current, policy, detail=False),
        "payment_instructions": services.payment_instructions(order, customer["phone"], plan["payment"]["min_prepay_percent"]),
        "warnings": plan["warnings"],
        "message": f"Đã tạo đơn {code}: {delivery['date_label']}, {delivery['window']}, tổng {pricing['total_label']}."
                   + (" Đơn sẽ được xác nhận khi nhận thanh toán." if status == "pending" else ""),
    }


@router.get("/{code}", summary="Tra đơn theo mã + SĐT người đặt")
def lookup(code: str, phone: str = Query(..., description="SĐT người đặt"), conn=Depends(get_db)):
    order = repo.find_order_for_phone(conn, code, phone)
    return {"order": services.order_view(conn, order, now(), get_policy())}


@router.post("/{code}/reschedule", summary="Đổi ngày/khung giờ giao, hoặc hẹn giao lại đơn giao thất bại")
def reschedule(code: str, body: OrderRescheduleIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        order = repo.find_order_for_phone(conn, code, body.phone)
        slots = repo.slots_by_code(conn)
        check = rules.reschedule_check(order, slots, current, policy)
        if not check["allowed"]:
            raise ApiError(409, "RESCHEDULE_NOT_ALLOWED", check["reason"], check)
        items = repo.order_items(conn, order["code"])
        products = [repo.get_product(conn, i["sku"]) for i in items]
        zone = repo.get_zone(conn, order["zone_id"])
        branch_hint = order["branch_id"] if order["fulfillment"] == "pickup" else None
        if (body.new_date.isoformat(), body.new_slot_code.upper()) == (order["delivery_date"], order["slot_code"]) \
                and check["mode"] != "redelivery":
            raise ApiError(422, "SAME_SLOT", "Ngày và khung giờ mới trùng với lịch hiện tại.")
        branch, slot = services.validate_slot(conn, zone=zone, fulfillment=order["fulfillment"], branch_id=branch_hint,
                                              d=body.new_date, slot_code=body.new_slot_code, products=products,
                                              now=current, policy=policy, exclude_code=order["code"],
                                              min_lead_hours=_bulk_lead(items, policy))
        new_window = f"{date_vi(body.new_date)}, {slot['start_time']}–{slot['end_time']}"
        if check["requires_approval"]:
            req = repo.insert_request(
                conn, type="reschedule", customer_id=order["customer_id"], ref_type="order", ref_code=order["code"],
                reason_code="reschedule_outside_policy", description=body.reason,
                amount=None, payload={"new_date": body.new_date.isoformat(), "new_slot_code": slot["code"],
                                      "branch_id": branch["id"], "mode": check["mode"], "check": check["reason"]},
                status="pending_approval", approval_rules=check["approval_rules"], created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "policy_check": check, "requested_window": new_window,
                    "request": services.request_view(req), "message": services.pending_message(req)}
        services.apply_reschedule(conn, order, new_date=body.new_date, slot_code=slot["code"], branch_id=branch["id"],
                                  mode=check["mode"], actor=body.actor, now=current, policy=policy, reason=body.reason)
        updated = repo.get_order(conn, order["code"])
    msg = f"Đã chuyển đơn {order['code']} sang {new_window}."
    if check["mode"] == "redelivery":
        msg = (f"Đã hẹn giao lại đơn {order['code']} vào {new_window}; phí giao lại "
               f"{vnd(updated['shipping_fee'] - order['shipping_fee'])}, tổng mới {vnd(updated['total'])}.")
    return {"result": "rescheduled" if check["mode"] != "redelivery" else "redelivery_scheduled",
            "policy_check": check, "order": services.order_view(conn, updated, current, policy, detail=False),
            "message": msg}


@router.post("/{code}/cancel", summary="Huỷ đơn (dry_run=true để xem trước mức hoàn tiền)")
def cancel(code: str, body: CancelIn, response: Response, conn=Depends(get_db)):
    current, policy = now(), get_policy()
    with conn:
        order = repo.find_order_for_phone(conn, code, body.phone)
        items = repo.order_items(conn, order["code"])
        preview = rules.cancellation_preview(order, items, repo.slots_by_code(conn), current, policy)
        if not preview["allowed"]:
            raise ApiError(409, "NOT_CANCELLABLE", preview["reason"], preview)
        if body.dry_run:
            return {"result": "preview", "dry_run": True, "preview": preview}
        if preview["requires_approval"]:
            req = repo.insert_request(
                conn, type="cancellation", customer_id=order["customer_id"], ref_type="order", ref_code=order["code"],
                reason_code="cancel_outside_policy", description=body.reason, amount=preview["refund_amount"],
                payload={"preview": preview}, status="pending_approval", approval_rules=preview["approval_rules"],
                created_by=body.actor, now=current)
            response.status_code = 202
            return {"result": "pending_approval", "preview": preview, "request": services.request_view(req),
                    "message": services.pending_message(req)}
        refund_req = services.perform_cancel(conn, order, refund_amount=preview["refund_amount"], reason=body.reason,
                                             actor=body.actor, now=current, policy=policy)
        updated = repo.get_order(conn, order["code"])
    msg = f"Đã huỷ đơn {order['code']}."
    if refund_req:
        msg += f" Hoàn {vnd(refund_req['amount'])} ({preview['refund_percent']}%), yêu cầu {refund_req['code']}"
        msg += " đang chờ quản lý duyệt (APR-01)." if refund_req["status"] == "pending_approval" else " đã được duyệt."
    return {"result": "cancelled", "preview": preview,
            "refund_request": services.request_view(refund_req) if refund_req else None,
            "order": services.order_view(conn, updated, current, policy, detail=False), "message": msg}
