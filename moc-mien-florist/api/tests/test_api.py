"""Test theo kịch bản nghiệp vụ. Đồng hồ cố định 2026-10-16 08:00 (+07:00), DB tạo lại cho mỗi test."""

STAFF = {"X-Staff-Key": "mocmien-staff-2026"}
NEW_CUSTOMER = {"full_name": "Đỗ Thị Kiều Oanh", "phone": "0909 888 777"}
RECIPIENT_Z1 = {"name": "Mai Anh", "phone": "0911222333", "address": "10 Hòa Bình, phường Ninh Kiều", "zone_id": "Z1"}


def order_body(**over):
    body = {"customer": NEW_CUSTOMER, "items": [{"sku": "BH02"}, {"sku": "PK01"}], "delivery_date": "2026-10-20",
            "slot_code": "K2", "recipient": RECIPIENT_Z1, "payment_method": "bank_transfer"}
    body.update(over)
    return body


# ------------------------------------------------------------------ hệ thống & danh mục
def test_health_uses_mock_clock(client):
    r = client.get("/health").json()
    assert r["now"] == "2026-10-16T08:00:00+07:00" and r["mock_clock"] is True


def test_policy_endpoint_exposes_approval_rules(client):
    rules = {r["id"] for r in client.get("/policy").json()["approval_required"]}
    assert {"APR-01", "APR-02", "APR-05", "APR-14"} <= rules


def test_inventory_and_seasonal_out_of_stock(client):
    items = client.get("/inventory", params={"sku": "BH10"}).json()["items"]
    assert all(i["quantity"] == 0 and i["status"] == "out_of_stock" for i in items)
    assert client.get("/inventory", params={"sku": "XX99"}).status_code == 404


def test_delivery_slots_respect_lead_time(client):
    slots = {s["slot_code"]: s for s in client.get("/delivery/slots", params={"date": "2026-10-16", "zone_id": "Z1"}).json()["slots"]}
    assert not slots["K1"]["available"] and not slots["K2"]["available"]
    assert slots["K3"]["available"]
    z4 = {s["slot_code"]: s for s in client.get("/delivery/slots", params={"date": "2026-10-16", "zone_id": "Z4"}).json()["slots"]}
    assert not any(s["available"] for s in z4.values())


# ------------------------------------------------------------------ xác minh danh tính
def test_lookup_requires_orderer_phone(client):
    assert client.get("/orders/MM10001", params={"phone": "0912345678"}).status_code == 200
    assert client.get("/orders/MM10001", params={"phone": "+84 912 345 678"}).status_code == 200
    wrong = client.get("/orders/MM10001", params={"phone": "0999999999"})
    recipient = client.get("/orders/MM10001", params={"phone": "0976543210"})
    missing = client.get("/orders/MM99999", params={"phone": "0912345678"})
    assert wrong.status_code == recipient.status_code == missing.status_code == 404
    assert wrong.json()["error"]["code"] == missing.json()["error"]["code"]


# ------------------------------------------------------------------ báo giá & tạo đơn
def test_quote_applies_code_and_shipping(client):
    r = client.post("/orders/quote", json=order_body(discount_code="PNVN2010")).json()
    p = r["pricing"]
    assert (p["subtotal"], p["shipping_fee"], p["discount"]["amount"], p["total"]) == (435000, 25000, 42000, 418000)


def test_vip_tier_beats_smaller_code(client):
    body = order_body(customer={"full_name": "Nguyễn Thị Thu Hà", "phone": "0901234567"},
                      items=[{"sku": "BH03"}], discount_code="CHAOBAN30")
    p = client.post("/orders/quote", json=body).json()["pricing"]
    assert p["discount"]["applied_source"] == "tier" and p["discount"]["amount"] == 100000 and p["shipping_fee"] == 0


def test_create_order_then_lookup(client):
    before = client.get("/inventory", params={"sku": "BH02", "branch_id": "CN01"}).json()["items"][0]["quantity"]
    r = client.post("/orders", json=order_body(discount_code="CHAOBAN30"))
    assert r.status_code == 201
    data = r.json()
    code = data["order"]["code"]
    assert data["order"]["status"] == "pending" and data["payment_instructions"]["account_number"]
    after = client.get("/inventory", params={"sku": "BH02", "branch_id": "CN01"}).json()["items"][0]["quantity"]
    assert after == before - 1
    looked = client.get(f"/orders/{code}", params={"phone": "0909888777"}).json()["order"]
    assert looked["pricing"]["total"] == 430000
    again = client.post("/orders/quote", json=order_body(discount_code="CHAOBAN30")).json()["pricing"]["discount"]
    assert again["code_error"]["code"] in ("CODE_ALREADY_USED", "CODE_FIRST_ORDER_ONLY")


def test_slot_lead_time_and_custom_product(client):
    r = client.post("/orders", json=order_body(delivery_date="2026-10-16", slot_code="K2"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert "K3 13:00–15:00" in r.json()["error"]["details"]["alternatives_same_day"]
    r = client.post("/orders", json=order_body(items=[{"sku": "BH09"}], delivery_date="2026-10-16", slot_code="K6"))
    assert r.status_code == 409 and r.json()["error"]["details"]["required_lead_time_hours"] == 24


def test_out_of_stock(client):
    r = client.post("/orders", json=order_body(items=[{"sku": "BH10"}], delivery_date="2026-10-25"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "OUT_OF_STOCK"


def test_payment_rules(client):
    big = order_body(items=[{"sku": "BH09"}], delivery_date="2026-10-25", payment_method="cod")
    assert client.post("/orders", json=big).json()["error"]["code"] == "COD_NOT_ALLOWED"
    z3 = order_body(recipient={**RECIPIENT_Z1, "zone_id": "Z3"}, payment_method="cod")
    assert client.post("/orders", json=z3).json()["error"]["code"] == "COD_NOT_ALLOWED"
    cash_delivery = order_body(payment_method="cash")
    assert client.post("/orders", json=cash_delivery).json()["error"]["code"] == "PAY_AT_STORE_PICKUP_ONLY"
    ok = client.post("/orders", json=order_body(payment_method="cod"))
    assert ok.status_code == 201 and ok.json()["order"]["status"] == "confirmed"


def test_express_rules(client):
    ok = client.post("/orders/quote", json=order_body(express=True, delivery_date=None, slot_code=None))
    assert ok.status_code == 200 and ok.json()["pricing"]["express_fee"] == 40000
    z3 = order_body(express=True, delivery_date=None, slot_code=None, recipient={**RECIPIENT_Z1, "zone_id": "Z3"})
    assert client.post("/orders/quote", json=z3).json()["error"]["code"] == "EXPRESS_UNAVAILABLE"
    wreath = order_body(express=True, delivery_date=None, slot_code=None, items=[{"sku": "CB01"}])
    assert client.post("/orders/quote", json=wreath).json()["error"]["code"] == "EXPRESS_UNAVAILABLE"


def test_bulk_order_needs_48_hours(client):
    bulk = order_body(items=[{"sku": "BH08", "quantity": 10}], delivery_date="2026-10-17", slot_code="K3")
    r = client.post("/orders/quote", json=bulk)
    assert r.status_code == 409 and r.json()["error"]["details"]["required_lead_time_hours"] == 48
    stems = order_body(items=[{"sku": "HL01", "quantity": 30}], delivery_date="2026-10-17", slot_code="K3")
    assert client.post("/orders/quote", json=stems).status_code == 200


def test_outside_zone_and_large_order_need_approval(client):
    r = client.post("/orders", json=order_body(recipient={**RECIPIENT_Z1, "zone_id": "Z9"}))
    assert r.status_code == 409 and r.json()["error"]["details"]["approval_rule"] == "APR-06"
    big = order_body(items=[{"sku": "BH09", "quantity": 2}, {"sku": "LC02", "quantity": 2}], delivery_date="2026-10-25",
                     slot_code="K3")
    r = client.post("/orders", json=big)
    assert r.status_code == 409 and r.json()["error"]["details"]["approval_rule"] == "APR-07"


# ------------------------------------------------------------------ huỷ đơn
def test_cancel_full_refund_auto_approved(client):
    preview = client.post("/orders/MM10001/cancel", json={"phone": "0912345678", "dry_run": True}).json()["preview"]
    assert preview["refund_percent"] == 100 and preview["refund_amount"] == 418000
    r = client.post("/orders/MM10001/cancel", json={"phone": "0912345678", "reason": "Đổi ý"}).json()
    assert r["result"] == "cancelled" and r["refund_request"]["status"] == "approved"
    assert r["order"]["payment"]["status"] == "refund_pending"


def test_cancel_70_percent_refund_needs_manager(client):
    r = client.post("/orders/MM10002/cancel", json={"phone": "0901234567"}).json()
    assert r["preview"]["refund_percent"] == 70 and r["preview"]["refund_amount"] == 869000
    assert r["refund_request"]["status"] == "pending_approval"
    assert r["refund_request"]["approval_rules"][0]["id"] == "APR-01"


def test_cancel_in_progress_creates_approval_request(client):
    r = client.post("/orders/MM10003/cancel", json={"phone": "0933456789"})
    assert r.status_code == 202 and r.json()["request"]["approval_rules"][0]["id"] == "APR-03"
    assert client.get("/orders/MM10003", params={"phone": "0933456789"}).json()["order"]["status"] == "arranging"


def test_cancel_custom_order_tiers(client):
    preview = client.post("/orders/MM10012/cancel", json={"phone": "0978123456", "dry_run": True}).json()["preview"]
    assert preview["is_custom_order"] and preview["refund_percent"] == 50 and preview["refund_amount"] == 1495000


def test_cancel_delivered_not_allowed(client):
    r = client.post("/orders/MM10004/cancel", json={"phone": "0912345678"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_CANCELLABLE"


# ------------------------------------------------------------------ đổi lịch / giao lại
def test_reschedule_free(client):
    r = client.post("/orders/MM10001/reschedule", json={"phone": "0912345678", "new_date": "2026-10-19", "new_slot_code": "K4"})
    assert r.status_code == 200 and r.json()["order"]["reschedule_count"] == 1


def test_reschedule_in_progress_needs_approval_then_staff_applies(client):
    r = client.post("/orders/MM10003/reschedule", json={"phone": "0933456789", "new_date": "2026-10-16", "new_slot_code": "K4"})
    assert r.status_code == 202
    code = r.json()["request"]["code"]
    d = client.post(f"/staff/requests/{code}/decision", headers=STAFF, json={"decision": "approve", "staff_name": "Luân"})
    assert d.json()["request"]["status"] == "completed"
    order = client.get("/orders/MM10003", params={"phone": "0933456789"}).json()["order"]
    assert order["delivery"]["slot_code"] == "K4"


def test_redelivery_after_failed_delivery(client):
    r = client.post("/orders/MM10011/reschedule", json={"phone": "0987654321", "new_date": "2026-10-16", "new_slot_code": "K4"})
    data = r.json()
    assert data["result"] == "redelivery_scheduled"
    assert data["order"]["status"] == "confirmed" and data["order"]["pricing"]["total"] == 430000


# ------------------------------------------------------------------ hoàn tiền & đổi trả
def test_refund_late_delivery_policy(client):
    r = client.post("/requests/refund", json={"phone": "0901234567", "order_code": "MM10006", "reason_code": "late_delivery"})
    assert r.status_code == 201 and r.json()["request"]["amount"] == 60000 and r.json()["request"]["status"] == "approved"
    full = client.post("/requests/refund", json={"phone": "0901234567", "order_code": "MM10006",
                                                 "reason_code": "late_delivery", "amount": 925000})
    rules = {x["id"] for x in full.json()["request"]["approval_rules"]}
    assert full.status_code == 202 and {"APR-09", "APR-01"} <= rules


def test_refund_on_undelivered_order_redirects_to_cancel(client):
    r = client.post("/requests/refund", json={"phone": "0912345678", "order_code": "MM10001", "reason_code": "other"})
    assert r.status_code == 409 and "huỷ" in r.json()["error"]["message"]


def test_exchange_within_guarantee(client):
    ok = client.post("/requests/exchange", json={"phone": "0912345678", "order_code": "MM10004", "reason_code": "wilted_early",
                                                 "evidence_urls": ["https://example.com/a.jpg"]})
    assert ok.status_code == 201 and ok.json()["request"]["status"] == "approved"
    no_proof = client.post("/requests/exchange", json={"phone": "0912345678", "order_code": "MM10004", "reason_code": "wilted_early"})
    assert no_proof.status_code == 202


def test_exchange_outside_guarantee_needs_approval(client):
    r = client.post("/requests/exchange", json={"phone": "0933456789", "order_code": "MM10005", "reason_code": "wilted_early",
                                                "evidence_urls": ["https://example.com/b.jpg"]})
    assert r.status_code == 202 and r.json()["request"]["approval_rules"][0]["id"] == "APR-08"


def test_exchange_change_of_mind(client):
    fresh = client.post("/requests/exchange", json={"phone": "0987654321", "order_code": "MM10010",
                                                    "reason_code": "change_of_mind", "items": [{"sku": "BH01"}]})
    assert fresh.json()["request"]["status"] == "rejected"
    bear = client.post("/requests/exchange", json={"phone": "0987654321", "order_code": "MM10010",
                                                   "reason_code": "change_of_mind", "items": [{"sku": "PK02"}],
                                                   "resolution": "refund"})
    assert bear.json()["request"]["status"] == "approved"


# ------------------------------------------------------------------ mã giảm giá
def test_discount_limits(client):
    ok = client.post("/requests/discount", json={"phone": "0912345678", "reason_code": "late_delivery", "percent": 10})
    assert ok.status_code == 201 and ok.json()["issued_code"]["code"].startswith("XL")
    over = client.post("/requests/discount", json={"phone": "0912345678", "reason_code": "late_delivery", "percent": 15})
    assert over.status_code == 202
    third = client.post("/requests/discount", json={"phone": "0933456789", "reason_code": "quality_issue", "percent": 5})
    assert third.status_code == 202 and "APR-02" in [x["id"] for x in third.json()["request"]["approval_rules"]]


def test_goodwill_code_status_requires_owner_phone(client):
    assert client.get("/discounts/XL7K2M9Q").status_code == 404
    assert client.get("/discounts/XL7K2M9Q", params={"phone": "0933456789"}).json()["status"] == "expired"
    assert client.get("/discounts/XLQ8D3TR", params={"phone": "0933456789"}).json()["status"] == "active"
    assert client.get("/discounts/GIAM50").status_code == 404


# ------------------------------------------------------------------ tư vấn sự kiện
def test_consultation_booking(client):
    monday = client.get("/consultations/availability", params={"date": "2026-10-19"}).json()
    assert not any(s["available"] for s in monday["slots"])
    body = {"customer": NEW_CUSTOMER, "event_type": "wedding", "appointment_date": "2026-10-20",
            "appointment_time": "10:30", "event_date": "2026-12-20"}
    assert client.post("/consultations", json=body).status_code == 201
    too_soon = client.post("/consultations", json={**body, "appointment_time": "14:00", "event_date": "2026-10-24"})
    assert too_soon.json()["error"]["code"] == "EVENT_TOO_SOON"


def test_consultation_reschedule_close_to_appointment(client):
    r = client.post("/consultations/TV2004/reschedule", json={"phone": "0918222333", "new_date": "2026-10-20", "new_time": "15:30"})
    assert r.status_code == 202 and r.json()["request"]["approval_rules"][0]["id"] == "APR-10"


def test_contract_deposit_refund_tiers(client):
    def preview(code, phone):
        return client.post(f"/consultations/{code}/cancel", json={"phone": phone, "dry_run": True}).json()["preview"]
    assert preview("TV2001", "0987654321")["refund_amount"] == 4770000
    assert preview("TV2005", "0901234567")["refund_amount"] == 1125000
    assert preview("TV2002", "0905678123")["refund_amount"] == 0
    r = client.post("/consultations/TV2001/cancel", json={"phone": "0987654321"})
    assert r.status_code == 202 and r.json()["request"]["approval_rules"][0]["id"] == "APR-05"


# ------------------------------------------------------------------ gói định kỳ
def test_altar_subscription_follows_lunar_calendar(client):
    body = {"customer": NEW_CUSTOMER, "plan_id": "SUB-ALTAR", "term_months": 3, "start_date": "2026-10-20",
            "slot_code": "K1", "zone_id": "Z1", "delivery_address": "10 Hòa Bình, phường Ninh Kiều"}
    r = client.post("/subscriptions", json=body).json()
    sub = r["subscription"]
    assert sub["next_delivery"]["date"] == "2026-10-23" and sub["deliveries"]["total"] == 6
    assert sub["price_total"] == 1254000


def test_subscription_pause_rules(client):
    ok = client.post("/subscriptions/GD3004/pause", json={"phone": "0978123456", "resume_date": "2026-11-01"})
    assert ok.status_code == 200 and ok.json()["subscription"]["next_delivery"]["date"] == "2026-11-07"
    too_long = client.post("/subscriptions/GD3001/pause", json={"phone": "0939111222", "resume_date": "2026-12-31"})
    assert too_long.status_code == 202


def test_subscription_cancel_refund_needs_approval(client):
    p = client.post("/subscriptions/GD3001/cancel", json={"phone": "0939111222", "dry_run": True}).json()["preview"]
    assert p["remaining_deliveries"] == 6 and p["refund_amount"] == 3335000 and p["requires_approval"]


# ------------------------------------------------------------------ duyệt của nhân viên
def test_staff_refund_flow(client):
    r = client.post("/orders/MM10002/cancel", json={"phone": "0901234567"}).json()
    code = r["refund_request"]["code"]
    assert client.post(f"/staff/requests/{code}/decision", headers={"X-Staff-Key": "sai"},
                       json={"decision": "approve", "staff_name": "x"}).status_code == 401
    client.post(f"/staff/requests/{code}/decision", headers=STAFF, json={"decision": "approve", "staff_name": "Diễm Trang"})
    done = client.post(f"/staff/requests/{code}/decision", headers=STAFF, json={"decision": "complete", "staff_name": "Diễm Trang"})
    assert done.json()["request"]["status"] == "completed"
    order = client.get("/orders/MM10002", params={"phone": "0901234567"}).json()["order"]
    assert order["payment"]["status"] == "partially_refunded" and order["payment"]["refunded_amount"] == 869000
