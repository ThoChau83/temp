# API nghiệp vụ giả lập – Mộc Miên Florist

FastAPI + `sqlite3` (thư viện chuẩn, không ORM). Dữ liệu tổng hợp; mọi ngưỡng chính sách đọc trực tiếp từ [`../policy.yaml`](../policy.yaml), nên API, guardrail và reviewer luôn dùng cùng một bộ số.

## 1. Chạy nhanh

```bash
# từ thư mục moc-mien-florist/api
python -m venv .venv && .venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py                              # tạo data/moc_mien.db từ sql/schema.sql + sql/seed.sql
uvicorn app.main:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs · OpenAPI JSON: http://localhost:8000/openapi.json
- Chạy test: `pytest -q` (36 test theo kịch bản, mỗi test dùng DB mới).
- Tạo DB bằng `sqlite3` CLI cũng được: `sqlite3 data/moc_mien.db < sql/schema.sql && sqlite3 data/moc_mien.db < sql/seed.sql`.

### Cấu hình (`.env`, xem `.env.example`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DB_PATH` | `data/moc_mien.db` | File SQLite |
| `POLICY_PATH` | `../policy.yaml` | Chính sách máy đọc được |
| `MOCK_NOW` | `2026-10-16T08:00:00+07:00` | **Đồng hồ giả lập.** Seed được sinh quanh mốc này để các kịch bản (đơn sắp giao, đơn trễ, hợp đồng còn 12 ngày...) luôn tái lập. Đặt `off` để dùng giờ thật. |
| `API_KEY` | (trống) | Nếu đặt, mọi request phải có header `X-API-Key` |
| `STAFF_KEY` | `mocmien-staff-2026` | Header `X-Staff-Key` cho `/staff/*` |

## 2. Dữ liệu

| Bảng | Số dòng | Ghi chú |
|---|---|---|
| `customers` | 60 | 8 khách kịch bản (KH0001–KH0008) + 52 khách sinh ngẫu nhiên, 3 hạng thành viên, 5 khách doanh nghiệp |
| `orders` / `order_items` / `order_events` | 140 / ~200 / ~540 | 8 trạng thái: pending, confirmed, arranging, delivering, delivered, failed_delivery, cancelled, refunded |
| `consultations` | 30 | scheduled, completed, contracted, cancelled, no_show |
| `subscriptions` | 20 | active, paused, cancelled, expired (4 gói, có gói theo âm lịch) |
| `service_requests` | ~45 | hoàn tiền, đổi trả, mã giảm giá, huỷ, đổi lịch, chuyển nhân viên – đủ trạng thái chờ duyệt/đã duyệt/từ chối/hoàn tất |
| `products` / `inventory` | 50 / 100 | 10 danh mục, tồn kho theo 2 chi nhánh |
| `discount_codes` | 14 | mã công khai (còn hạn, hết hạn, sắp diễn ra) + mã xin lỗi cá nhân `XL...` |

`sql/seed.sql` được sinh bởi `../tools/generate_seed.py` (random seed cố định → chạy lại ra đúng file cũ). Muốn đổi giá/sản phẩm: sửa `../tools/master_data.py` rồi chạy lại script.

## 3. Endpoint

Mọi endpoint có dữ liệu cá nhân đều yêu cầu **mã + SĐT người đặt** (IDV-01). Sai mã hoặc sai SĐT trả cùng một lỗi 404 để không lộ đơn có tồn tại hay không.

### Danh mục & tồn kho
| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | Trạng thái, giờ hiện tại của API |
| GET | `/branches` | Chi nhánh, giờ mở cửa, sức chứa khung giờ |
| GET | `/products?category=&q=&min_price=&max_price=` | Tìm sản phẩm |
| GET | `/products/{sku}` | Chi tiết + tồn kho từng chi nhánh |
| GET | `/inventory?sku=&q=&branch_id=&only_available=` | **Tra tồn kho** |
| GET | `/delivery/zones` | Khu vực, phí ship, ngưỡng miễn phí, hỏa tốc |
| GET | `/delivery/slots?date=&zone_id=` (hoặc `branch_id=`) `&skus=` | Khung giờ còn trống, lý do không khả dụng |
| GET | `/promotions` | Mã khuyến mãi đang/ sắp áp dụng |
| GET | `/discounts/{code}?phone=` | Trạng thái 1 mã (mã `XL...` cần SĐT chủ mã) |
| GET | `/policy` | Toàn bộ `policy.yaml` dạng JSON |

### Đơn hàng (giao hoa theo khung giờ)
| Method | Path | Mô tả |
|---|---|---|
| POST | `/orders/quote` | Báo giá: tiền hoa, ship, hỏa tốc, ưu đãi tốt nhất, cảnh báo – **không** tạo đơn |
| POST | `/orders` | **Tạo đơn** (lịch giao) sau khi khách xác nhận |
| GET | `/orders/{code}?phone=` | **Tra đơn theo mã + SĐT**, kèm `allowed_actions` (xem trước huỷ/đổi lịch theo policy) |
| POST | `/orders/{code}/reschedule` | **Đổi lịch giao**; với đơn giao thất bại = hẹn giao lại (CHG-03) |
| POST | `/orders/{code}/cancel` | **Huỷ đơn**; `dry_run: true` để xem trước % hoàn |

### Tư vấn hoa cưới – sự kiện
| Method | Path | Mô tả |
|---|---|---|
| GET | `/consultations/availability?date=&mode=` | Giờ tư vấn trống (nghỉ Thứ Hai) |
| POST | `/consultations` | **Đặt lịch tư vấn** |
| GET | `/consultations/{code}?phone=` | Tra lịch |
| POST | `/consultations/{code}/reschedule` | **Đổi lịch** (miễn phí nếu ≥ 12 giờ) |
| POST | `/consultations/{code}/cancel` | **Huỷ lịch** / huỷ hợp đồng (hoàn cọc luôn chờ duyệt) |
| POST | `/consultations/{code}/change-event-date` | Đổi ngày sự kiện (1 lần miễn phí nếu ≥ 15 ngày) |

### Gói hoa định kỳ
| Method | Path | Mô tả |
|---|---|---|
| GET | `/subscriptions/plans` | 4 gói, giá theo kỳ hạn 1/3/6 tháng |
| POST | `/subscriptions` | Đăng ký gói |
| GET | `/subscriptions/{code}?phone=` | Tra gói, 4 kỳ giao kế tiếp (gói Hoa Cúng có nhãn âm lịch) |
| POST | `/subscriptions/{code}/pause` · `/resume` · `/reschedule` · `/cancel` | Tạm ngưng / tiếp tục / đổi lịch / huỷ |

### Yêu cầu dịch vụ
| Method | Path | Mô tả |
|---|---|---|
| POST | `/requests/refund` | **Ghi nhận hoàn tiền** – tự duyệt nếu ≤ 500.000đ và đúng điều kiện |
| POST | `/requests/exchange` | **Ghi nhận đổi trả** / bảo hành độ tươi |
| POST | `/requests/discount` | **Cấp/đề xuất mã giảm giá** – tự cấp nếu ≤ 10% và ≤ 100.000đ |
| POST | `/requests/escalate` | Chuyển nhân viên (kèm mã quy tắc APR-xx nếu có) |
| GET | `/requests/{code}?phone=` | Tra trạng thái yêu cầu |

### Nội bộ nhân viên (header `X-Staff-Key`)
| Method | Path | Mô tả |
|---|---|---|
| GET | `/staff/requests?status=pending_approval` | Hàng đợi duyệt |
| POST | `/staff/requests/{code}/decision` | `approve` / `reject` / `complete` – approve sẽ **thực thi** thay đổi (huỷ đơn, đổi lịch, cấp mã...) |
| POST | `/staff/orders/{code}/payment` · `/status` | Mô phỏng khách thanh toán, chuyển trạng thái giao |
| POST | `/staff/subscriptions/{code}/payment` | Kích hoạt gói sau thanh toán |

## 4. Quy ước phản hồi

- **200/201**: thực hiện xong. Phản hồi có `message` tiếng Việt để agent diễn đạt lại.
- **202 `pending_approval`**: hành động vượt quyền tự động → API **tự tạo yêu cầu chờ duyệt** và trả `request.code`, `approval_rules` (APR-xx, người duyệt, SLA). Agent phải báo "đang chờ duyệt", không hứa kết quả (NOT-02).
- **4xx**: `{"error": {"code": "...", "message": "...", "details": {...}}}`. Một số mã hay gặp:

| Code | Khi nào |
|---|---|
| `ORDER_NOT_FOUND_OR_PHONE_MISMATCH` (404) | Sai mã hoặc sai SĐT người đặt |
| `SLOT_UNAVAILABLE` (409) | Khung giờ không đủ thời gian chuẩn bị / đã kín / khu vực không giao – kèm `alternatives_same_day`, `alternatives_next_day` |
| `OUT_OF_STOCK` (409) | Chi nhánh không đủ hàng – kèm tồn kho chi nhánh khác, ghi chú mùa |
| `OUTSIDE_DELIVERY_ZONE`, `REQUIRES_APPROVAL` (409) | Cần chuyển nhân viên (APR-06, APR-07) |
| `COD_NOT_ALLOWED`, `PREPAYMENT_REQUIRED`, `EXPRESS_UNAVAILABLE` | Vi phạm ORD-03/05/06 |
| `NOT_CANCELLABLE`, `RESCHEDULE_NOT_ALLOWED`, `REFUND_NOT_ELIGIBLE` (409) | Không thể thực hiện theo chính sách – `message` nêu lý do |
| `VALIDATION_ERROR` (422) | Thiếu/sai trường dữ liệu |

## 5. Dữ liệu kịch bản để test agent

Mốc thời gian: **Thứ Sáu 16/10/2026, 08:00**. Mã và SĐT dưới đây cố định qua mọi lần sinh seed.

| Mã | Khách – SĐT người đặt | Tình huống | Kết quả mong đợi |
|---|---|---|---|
| MM10001 | Trần Minh Khang – 0912345678 | Bó Thương Thương giao 20/10 K2, đã trả 418.000đ (mã PNVN2010) | Đổi lịch miễn phí; huỷ → hoàn 100% = 418.000đ, tự duyệt |
| MM10002 | Nguyễn Thị Thu Hà (VIP) – 0901234567 | Lan 3 cành giao hôm nay K5, còn 9 giờ | Huỷ → hoàn 70% = 869.000đ, khoản hoàn chờ duyệt (APR-01) |
| MM10003 | Lê Ngọc Bích (Thân thiết) – 0933456789 | Đang cắm hoa, giao K2 hôm nay | Huỷ / đổi lịch → 202, trưởng ca duyệt (APR-03/04) |
| MM10004 | Trần Minh Khang – 0912345678 | Cẩm tú cầu giao 15/10 16:20 | Báo héo + ảnh → đổi trả được duyệt; không ảnh → APR-08 |
| MM10005 | Lê Ngọc Bích – 0933456789 | Bó hồng giao 10/10 | Báo héo ngày 16/10 → quá cam kết 3 ngày → APR-08 |
| MM10006 | Nguyễn Thị Thu Hà – 0901234567 | Giao trễ 145 phút, phí ship Z3 60.000đ | Hoàn 60.000đ tự duyệt + gợi ý mã 10%; đòi hoàn nhiều hơn → APR-09 (+APR-01) |
| MM10007 | Trần Minh Khang – 0912345678 | Đã huỷ, đã hoàn 890.000đ (YC10001) | Tra lịch sử hoàn tiền |
| MM10008 | Phạm Quốc Bảo (DN) – 0939111222 | 2 kệ khai trương 3.895.000đ, chờ chuyển khoản | Không cho COD, cần trả trước ≥ 50% |
| MM10009 | Huỳnh Văn Tài – 0987654321 | Hoa lẻ nhận tại CN02 ngày 17/10 K3, trả tiền mặt | Tra cứu, đổi giờ nhận |
| MM10010 | Huỳnh Văn Tài – 0987654321 | Bó hoa + gấu bông giao 12/10 | Trả gấu bông (phụ kiện, 7 ngày) được; đổi bó hoa vì không thích → từ chối (EXC-03) |
| MM10011 | Huỳnh Văn Tài – 0987654321 | Giao thất bại 15/10, COD | Hẹn giao lại trong 24 giờ, phí 25.000đ → tổng 430.000đ |
| MM10012 | Phạm Gia Huy – 0978123456 | Bó 99 hồng cầu hôn 17/10 K5, đã trả 2.990.000đ | Đơn đặt riêng: huỷ → hoàn 50% = 1.495.000đ, chờ duyệt |
| MM10013, MM10014 | Lê Ngọc Bích – 0933456789 | Lịch sử giao trễ, hoa dập → đã nhận 2 mã xin lỗi (XL7K2M9Q hết hạn, XLQ8D3TR còn hạn) | Xin mã thứ 3 → APR-02; không áp mã hết hạn |
| TV2001 | Huỳnh Văn Tài – 0987654321 | HĐ Gói Miên, cọc 4.770.000đ, cưới 12/12 | Huỷ → đề xuất hoàn 100% cọc, luôn chờ duyệt (APR-05) |
| TV2002 | Đặng Thị Kim Ngân – 0905678123 | HĐ Gói Mộc, cưới 28/10 (còn 12 ngày) | Huỷ → không hoàn cọc |
| TV2003 | Phạm Quốc Bảo – 0939111222 | Tư vấn khai trương 18/10 09:00 | Đổi lịch miễn phí |
| TV2004 | Lâm Thanh Tú – 0918222333 | Tư vấn online 16/10 14:00 (còn 6 giờ) | Đổi lịch → APR-10 |
| TV2005 | Nguyễn Thị Thu Hà – 0901234567 | HĐ hội nghị, sự kiện 05/11 (còn 20 ngày) | Huỷ → hoàn 50% cọc = 1.125.000đ, chờ duyệt |
| GD3001 | Phạm Quốc Bảo – 0939111222 | Văn Phòng Tươi 3 tháng, đã giao 6/12 lần | Huỷ → hoàn 3.335.000đ, chờ duyệt (APR-13) |
| GD3002 | Nguyễn Thị Thu Hà – 0901234567 | Hoa Cúng Rằm – Mùng Một, kỳ tới 23/10 (trước rằm tháng 9) | Tra lịch theo âm lịch |
| GD3003 | Lê Ngọc Bích – 0933456789 | Đang tạm ngưng đến 30/10 | Tiếp tục gói |
| GD3004 | Phạm Gia Huy – 0978123456 | Hoa Nhà Nửa Tháng, kỳ tới 17/10 K2 (còn 26 giờ) | Tạm ngưng / đổi lịch được (≥ 24 giờ) |

Khách mới (chưa có trong DB) dùng được mã `CHAOBAN30`; KH0001 có sinh nhật tháng 10 (thử `SINHNHAT10` – hệ thống vẫn chọn ưu đãi VIP 8% nếu lợi hơn).

## 6. Ví dụ gọi API

```bash
# Tra đơn
curl "http://localhost:8000/orders/MM10002?phone=0901234567"

# Xem trước mức hoàn khi huỷ
curl -X POST http://localhost:8000/orders/MM10002/cancel -H "Content-Type: application/json" \
     -d '{"phone":"0901234567","dry_run":true}'

# Báo giá đơn mới
curl -X POST http://localhost:8000/orders/quote -H "Content-Type: application/json" -d '{
  "customer": {"full_name": "Đỗ Thị Kiều Oanh", "phone": "0909888777"},
  "items": [{"sku": "BH02"}, {"sku": "PK01"}],
  "delivery_date": "2026-10-20", "slot_code": "K2",
  "recipient": {"name": "Mai Anh", "phone": "0911222333", "address": "10 Hòa Bình, phường Ninh Kiều", "zone_id": "Z1"},
  "discount_code": "PNVN2010", "payment_method": "momo"}'

# Quản lý duyệt yêu cầu
curl -X POST http://localhost:8000/staff/requests/YC10046/decision -H "X-Staff-Key: mocmien-staff-2026" \
     -H "Content-Type: application/json" -d '{"decision":"approve","staff_name":"Diễm Trang"}'
```

## 7. Cấu trúc mã

```
app/
  main.py            khởi tạo FastAPI, gắn router, API key
  config.py          biến môi trường, MOCK_NOW
  policy.py          nạp policy.yaml
  rules.py           đánh giá hành động theo policy (hàm thuần): huỷ, đổi lịch, hoàn tiền, đổi trả, cọc, gói
  pricing.py         tính phí ship, ưu đãi hạng, mã giảm giá (dùng chung với generate_seed)
  schedule.py, lunar.py   lịch giao gói định kỳ, chuyển đổi âm lịch (thuật toán Hồ Ngọc Đức)
  services.py        thao tác ghi dùng chung (huỷ, đổi lịch, cấp mã...) cho router khách và router nhân viên
  repo.py, db.py     truy vấn sqlite3
  routers/           catalog, orders, consultations, subscriptions, requests, staff
sql/schema.sql, sql/seed.sql
scripts/init_db.py
tests/test_api.py
```
