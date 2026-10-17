# SE373 – Workspace doanh nghiệp hư cấu: Tiệm hoa

Nhóm **Thuận + Thọ** dựng workspace **Mộc Miên Florist** (tiệm hoa tươi & hoa sự kiện, TP. Cần Thơ) cho agent CSKH. Workspace thứ hai (phòng gym) do nhóm Hưng + Hoàng thực hiện riêng.

| Workspace | Ngành | Nghiệp vụ chính cho agent |
|---|---|---|
| [`moc-mien-florist`](moc-mien-florist/README.md) — Mộc Miên Florist, Ninh Kiều & Cái Răng, Cần Thơ | Bán lẻ hoa tươi, hoa cưới – sự kiện | Bảng giá & tồn kho hoa, đặt/đổi/huỷ lịch giao theo khung giờ, lịch tư vấn hoa cưới, gói hoa định kỳ (có gói hoa cúng theo âm lịch), hoàn tiền, đổi trả, bảo hành độ tươi, mã giảm giá |

## Đối chiếu yêu cầu đề bài

| Yêu cầu | Đáp ứng |
|---|---|
| ≥ 20 tài liệu tri thức, ≥ 3 định dạng | **29 tài liệu**: 18 Markdown, 3 HTML, 3 PDF, 4 CSV, 1 XLSX – [`knowledge/`](moc-mien-florist/knowledge) |
| FAQ, bảng giá, đổi trả/hoàn tiền/bảo hành, hướng dẫn đặt lịch, giờ mở cửa, chi nhánh, giọng thương hiệu | Tài liệu 01–29 + [`brand_voice.md`](moc-mien-florist/brand_voice.md) |
| API giả lập FastAPI/Express | **FastAPI + sqlite3**, 38 endpoint – [`api/`](moc-mien-florist/api/README.md) |
| ≥ 50 khách, ≥ 100 đơn/lịch hẹn, nhiều trạng thái | 60 khách, 140 đơn (8 trạng thái), 30 lịch tư vấn, 20 gói định kỳ, ~45 yêu cầu dịch vụ |
| Lệnh SQL seed | [`api/sql/schema.sql`](moc-mien-florist/api/sql/schema.sql) + [`api/sql/seed.sql`](moc-mien-florist/api/sql/seed.sql) |
| Tra đơn/lịch theo mã + SĐT | `GET /orders/{code}?phone=`, `/consultations/{code}`, `/subscriptions/{code}`, `/requests/{code}` |
| Tạo/đổi/huỷ lịch | Đơn giao hoa (`/orders`), lịch tư vấn (`/consultations`), gói định kỳ (`/subscriptions`) |
| Tra tồn kho | `GET /inventory`, `GET /products/{sku}` |
| Ghi nhận hoàn tiền / đổi trả / mã giảm giá | `POST /requests/refund`, `/requests/exchange`, `/requests/discount` |
| `policy.yaml`: ngưỡng hoàn tiền, số ngày đổi trả, mức giảm tối đa, danh mục phải duyệt | [`policy.yaml`](moc-mien-florist/policy.yaml) – có rule id (APR-01…14, NOT-01…10) để guardrail/reviewer trích dẫn; API đọc chính file này |
| `brand_voice.md`: xưng hô, từ cấm, độ dài | [`brand_voice.md`](moc-mien-florist/brand_voice.md) – kèm checklist cho reviewer |

## Chạy thử nhanh

```bash
python -m venv .venv
.venv\Scripts\activate                     # macOS/Linux: source .venv/bin/activate
pip install -r moc-mien-florist/api/requirements.txt
cd moc-mien-florist/api
python scripts/init_db.py
uvicorn app.main:app --reload --port 8000   # mở http://localhost:8000/docs
pytest -q                                   # 36 test kịch bản
```

API dùng **đồng hồ giả lập** `MOCK_NOW=2026-10-16T08:00+07:00` để các kịch bản test (đơn sắp giao, đơn trễ, hợp đồng còn 12 ngày...) luôn ra cùng kết quả. Danh sách mã đơn/lịch/gói kịch bản kèm SĐT và kết quả mong đợi: [api/README.md – mục 5](moc-mien-florist/api/README.md#5-dữ-liệu-kịch-bản-để-test-agent).
