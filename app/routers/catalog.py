"""Danh mục: chi nhánh, sản phẩm, tồn kho, khu vực & khung giờ giao, mã khuyến mãi, policy."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from .. import labels, repo, services
from ..db import get_db, many, one
from ..errors import ApiError
from ..policy import get_policy
from ..utils import date_vi, is_peak_day, normalize_phone, now, vnd

router = APIRouter(tags=["Danh mục & tồn kho"])


def _stock_status(product: dict, qty: int) -> str:
    if qty <= 0:
        return "out_of_stock"
    low = 20 if product["category"] == "hoa_le" else 3
    return "low_stock" if qty <= low else "in_stock"


STOCK_LABEL = {"in_stock": "Còn hàng", "low_stock": "Sắp hết", "out_of_stock": "Hết hàng"}


def _product_view(conn, p: dict) -> dict:
    stocks = repo.stock_by_branch(conn, p["sku"])
    return {
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "category_label": labels.CATEGORY[p["category"]],
        "price": p["price"],
        "price_label": vnd(p["price"]) + f"/{p['unit']}",
        "unit": p["unit"],
        "main_flowers": p["main_flowers"],
        "color_tone": p["color_tone"],
        "size": p["size"],
        "description": p["description"],
        "lead_time_hours": p["lead_time_hours"],
        "freshness_days": p["freshness_days"],
        "is_seasonal": bool(p["is_seasonal"]),
        "season_note": p["season_note"],
        "stock": {b: {"quantity": q, "status": _stock_status(p, q), "status_label": STOCK_LABEL[_stock_status(p, q)]}
                  for b, q in stocks.items()},
    }


@router.get("/branches", summary="Danh sách chi nhánh, giờ mở cửa")
def list_branches(conn=Depends(get_db)):
    return {"branches": repo.list_branches(conn)}


@router.get("/products", summary="Tìm sản phẩm theo danh mục, từ khoá, khoảng giá")
def list_products(
    category: str | None = Query(None, description="bo_hoa, gio_hop_hoa, binh_hoa, ke_khai_truong, hoa_chia_buon, "
                                                   "hoa_cuoi, lan_chau, hoa_le, hoa_say_kho, phu_kien"),
    q: str | None = Query(None, description="Từ khoá trong tên / loại hoa / màu"),
    min_price: int | None = None,
    max_price: int | None = None,
    conn=Depends(get_db),
):
    sql, params = "SELECT * FROM products WHERE is_active = 1", []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if min_price is not None:
        sql += " AND price >= ?"
        params.append(min_price)
    if max_price is not None:
        sql += " AND price <= ?"
        params.append(max_price)
    rows = many(conn, sql + " ORDER BY category, price", params)
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in " ".join(str(r[k] or "") for k in
                                                     ("name", "main_flowers", "color_tone", "description")).lower()]
    return {"count": len(rows), "categories": labels.CATEGORY, "products": [_product_view(conn, r) for r in rows]}


@router.get("/products/{sku}", summary="Chi tiết 1 sản phẩm kèm tồn kho từng chi nhánh")
def get_product(sku: str, conn=Depends(get_db)):
    p = repo.get_product(conn, sku)
    if not p:
        raise ApiError(404, "PRODUCT_NOT_FOUND", f"Không có sản phẩm mã {sku}.")
    return _product_view(conn, p)


@router.get("/inventory", summary="Tra tồn kho theo SKU / từ khoá / chi nhánh")
def inventory(
    sku: str | None = None,
    q: str | None = Query(None, description="Từ khoá tên hoa, vd 'tulip', 'hồng'"),
    branch_id: str | None = None,
    only_available: bool = False,
    conn=Depends(get_db),
):
    sql = ("SELECT i.sku, i.branch_id, i.quantity, i.updated_at, p.* FROM inventory i "
           "JOIN products p ON p.sku = i.sku WHERE p.is_active = 1")
    params: list = []
    if sku:
        sql += " AND i.sku = ?"
        params.append(sku.upper())
    if branch_id:
        sql += " AND i.branch_id = ?"
        params.append(branch_id.upper())
    rows = many(conn, sql + " ORDER BY i.sku, i.branch_id", params)
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in f"{r['name']} {r['main_flowers'] or ''}".lower()]
    if only_available:
        rows = [r for r in rows if r["quantity"] > 0]
    if sku and not rows:
        raise ApiError(404, "PRODUCT_NOT_FOUND", f"Không có sản phẩm mã {sku}.")
    return {
        "note": "Với sản phẩm cắm sẵn (bó, giỏ, kệ...), số lượng là số suất còn nhận trong ngày; "
                "hoa lẻ/phụ kiện là số lượng thực tế.",
        "items": [{
            "sku": r["sku"], "name": r["name"], "branch_id": r["branch_id"], "quantity": r["quantity"],
            "unit": r["unit"], "status": _stock_status(r, r["quantity"]),
            "status_label": STOCK_LABEL[_stock_status(r, r["quantity"])], "price": r["price"],
            "lead_time_hours": r["lead_time_hours"], "season_note": r["season_note"], "updated_at": r["updated_at"],
        } for r in rows],
    }


@router.get("/delivery/zones", summary="Khu vực giao, phí ship, ngưỡng miễn phí")
def zones(conn=Depends(get_db)):
    policy = get_policy()
    express = policy["ordering"]["express"]
    return {
        "zones": [{**z, "fee_label": vnd(z["fee"]),
                   "free_ship_label": vnd(z["free_ship_min_order"]) if z["free_ship_min_order"] else "Không áp dụng"}
                  for z in repo.list_zones(conn)],
        "outside_zones": "Vị Thanh, Ngã Bảy, Sóc Trăng và tỉnh khác: báo giá riêng, cần trưởng ca duyệt (APR-06).",
        "express": {**express, "fee_label": vnd(express["fee"])},
        "vip_free_shipping_zones": policy["loyalty"]["tiers"]["vip"]["free_shipping_zones"],
    }


@router.get("/delivery/slots", summary="Khung giờ còn trống cho 1 ngày")
def delivery_slots(
    date_: date = Query(..., alias="date", description="YYYY-MM-DD"),
    zone_id: str | None = Query(None, description="Bắt buộc nếu giao tận nơi"),
    branch_id: str | None = Query(None, description="Bắt buộc nếu nhận tại cửa hàng"),
    skus: str | None = Query(None, description="Danh sách SKU, phân cách dấu phẩy, để tính thời gian chuẩn bị"),
    conn=Depends(get_db),
):
    policy = get_policy()
    zone = repo.get_zone(conn, zone_id) if zone_id else None
    if zone_id and not zone:
        raise ApiError(404, "ZONE_NOT_FOUND", "Khu vực không thuộc Z1–Z4; giao ngoài vùng cần trưởng ca duyệt (APR-06).")
    if not zone and not branch_id:
        raise ApiError(422, "ZONE_OR_BRANCH_REQUIRED", "Cần zone_id (giao tận nơi) hoặc branch_id (nhận tại cửa hàng).")
    products = []
    for sku in (skus or "").split(","):
        if sku.strip():
            p = repo.get_product(conn, sku.strip())
            if not p:
                raise ApiError(404, "PRODUCT_NOT_FOUND", f"Không có sản phẩm mã {sku}.")
            products.append(p)
    fulfillment = "delivery" if zone else "pickup"
    table, lead = services.slot_availability(conn, zone=zone, fulfillment=fulfillment, branch_id=branch_id, d=date_,
                                             products=products, now=now(), policy=policy)
    return {"date": date_.isoformat(), "date_label": date_vi(date_), "peak_day": is_peak_day(date_, policy),
            "fulfillment": fulfillment, "required_lead_time_hours": lead, "now": now().isoformat(), "slots": table}


@router.get("/promotions", summary="Chương trình khuyến mãi đang/ sắp diễn ra")
def promotions(conn=Depends(get_db)):
    today = now().date().isoformat()
    rows = many(conn, "SELECT * FROM discount_codes WHERE kind != 'goodwill' AND is_active = 1 AND valid_to >= ? "
                      "ORDER BY valid_from", (today,))
    return {"today": today, "promotions": [{
        "code": r["code"], "description": r["description"], "valid_from": r["valid_from"], "valid_to": r["valid_to"],
        "min_order": r["min_order"], "applicable_categories": r["applicable_categories"],
        "status": "active" if r["valid_from"] <= today else "upcoming",
    } for r in rows], "stacking_allowed": get_policy()["discount"]["stacking_allowed"]}


@router.get("/discounts/{code}", summary="Kiểm tra trạng thái 1 mã giảm giá")
def discount_status(code: str, phone: str | None = Query(None, description="Bắt buộc với mã xin lỗi (XL...)"),
                    conn=Depends(get_db)):
    row = one(conn, "SELECT * FROM discount_codes WHERE code = ?", (code.strip().upper(),))
    if not row:
        raise ApiError(404, "CODE_NOT_FOUND", "Mã giảm giá không tồn tại trong hệ thống (DSC-05: không tự tạo mã).")
    if row["customer_id"]:
        customer = repo.get_customer_by_phone(conn, normalize_phone(phone) or "")
        if not customer or customer["id"] != row["customer_id"]:
            raise ApiError(404, "CODE_NOT_FOUND", "Mã giảm giá không tồn tại hoặc không thuộc số điện thoại này.")
    today = now().date().isoformat()
    if not row["is_active"]:
        status = "inactive"
    elif today < row["valid_from"]:
        status = "upcoming"
    elif today > row["valid_to"]:
        status = "expired"
    elif row["usage_limit"] is not None and row["used_count"] >= row["usage_limit"]:
        status = "used_up"
    else:
        status = "active"
    return {"code": row["code"], "description": row["description"], "status": status,
            "discount_type": row["discount_type"], "value": row["value"], "max_discount": row["max_discount"],
            "min_order": row["min_order"], "applicable_categories": row["applicable_categories"],
            "valid_from": row["valid_from"], "valid_to": row["valid_to"], "kind": row["kind"]}


@router.get("/policy", summary="Toàn bộ policy.yaml dạng JSON (cho guardrail / reviewer)")
def policy():
    return get_policy()
