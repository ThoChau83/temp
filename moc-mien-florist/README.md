# Workspace `moc-mien-florist` – Mộc Miên Florist (Cần Thơ)

Doanh nghiệp hư cấu ngành **bán lẻ hoa tươi & dịch vụ hoa sự kiện**, bối cảnh TP. Cần Thơ. Agent CSKH của workspace này xử lý: tư vấn – báo giá – tồn kho, đặt/đổi/huỷ **lịch giao hoa theo khung giờ**, **lịch tư vấn hoa cưới – sự kiện**, **gói hoa định kỳ** (gồm gói hoa cúng theo âm lịch), hoàn tiền, đổi trả, mã giảm giá.

## Thông tin cốt lõi

| Mục | Giá trị |
|---|---|
| Chi nhánh | CN01 Ninh Kiều – 86 Trần Văn Hoài (07:00–21:00, có studio hoa cưới); CN02 Cái Răng – 215 Võ Nguyên Giáp (07:30–20:00) |
| Hotline / Zalo | 0292 3 868 186 / 0939 868 186 (07:00–21:00) |
| Khung giờ giao | K1 08–10, K2 10–12, K3 13–15, K4 15–17, K5 17–19, K6 19–21; đặt trước ≥ 3 giờ |
| Khu vực | Z1 25.000đ (free ≥ 500k) · Z2 35.000đ (free ≥ 800k) · Z3 60.000đ (free ≥ 1,5tr) · Z4 120.000đ |
| Hoàn tiền | ≤ 500.000đ tự duyệt; > 500.000đ quản lý duyệt |
| Huỷ đơn | ≥ 24h hoàn 100%, 4–24h hoàn 70%, < 4h cần duyệt; đơn đặt riêng 72h/24h → 100%/50% |
| Đổi trả | Hoa tươi 24 giờ; cam kết tươi 1–21 ngày theo loại; phụ kiện 7 ngày; hoa sáp/khô 3 ngày |
| Giảm giá agent được tự cấp | ≤ 10% và ≤ 100.000đ, tối đa 2 mã xin lỗi / khách / 90 ngày |

Nguồn sự thật: **`policy.yaml`** (ngưỡng, quyền duyệt) và **`tools/master_data.py`** (giá, sản phẩm, khu vực, gói).

## Cấu trúc

```
moc-mien-florist/
├── policy.yaml          chính sách máy đọc được (rule id: ORD, CHG, REF, EXC, DSC, CON, SUB, APR, NOT...)
├── brand_voice.md       giọng thương hiệu: xưng hô, từ cấm, độ dài, emoji, giọng theo ngữ cảnh
├── knowledge/           29 tài liệu tri thức (MD, HTML, PDF, CSV, XLSX)
├── api/                 FastAPI + sqlite3, 38 endpoint, seed 60 khách / 140 đơn (xem api/README.md)
└── tools/
    ├── master_data.py   dữ liệu gốc dùng chung
    ├── generate_seed.py sinh api/sql/seed.sql (tất định)
    ├── build_docs.py    sinh PDF/CSV/XLSX trong knowledge/
    └── pdf_src/         nguồn văn bản cho PDF điều khoản hợp đồng
```

## Danh mục tài liệu tri thức (29)

| # | Tệp | Định dạng | Nội dung |
|---|---|---|---|
| 01 | 01-gioi-thieu-moc-mien.md | Markdown | Câu chuyện, giá trị, sản phẩm, kênh liên hệ |
| 02 | 02-chi-nhanh-gio-mo-cua.md | Markdown | Chi nhánh, giờ mở cửa, ngày cao điểm, lịch Tết Đinh Mùi 2027 |
| 03 | 03-faq-tong-hop.md | Markdown | 26 câu hỏi thường gặp |
| 04 | 04-huong-dan-dat-hoa.md | Markdown | Kênh đặt, thông tin cần, quy trình, trạng thái đơn |
| 05 | 05-giao-hang-khung-gio-phi-ship.md | Markdown | Khung giờ, thời gian chuẩn bị, khu vực, hỏa tốc, giao lại |
| 06 | 06-chinh-sach-doi-lich-huy-don.md | Markdown | Đổi lịch, huỷ, mức hoàn, ví dụ tính |
| 07 | 07-chinh-sach-doi-tra.md | Markdown | Thời hạn đổi trả theo nhóm, bằng chứng, phương án |
| 08 | 08-cam-ket-do-tuoi.md | Markdown | Bảo hành độ tươi theo loại hoa |
| 09 | 09-chinh-sach-hoan-tien.md | Markdown | Trường hợp hoàn, ngưỡng duyệt, bồi hoàn giao trễ, thời gian tiền về |
| 10 | 10-thanh-toan-hoa-don.md | Markdown | Hình thức thanh toán, COD, trả trước, VAT |
| 11 | 11-chuong-trinh-thanh-vien.md | Markdown | Hạng thành viên, tích điểm, không cộng dồn |
| 12 | 12-khuyen-mai-thang-10-11-2026.md | Markdown | Khuyến mãi 20/10, 20/11, Black Friday, mã hết hạn |
| 13 | 13-goi-hoa-dinh-ky.md | Markdown | 4 gói, giá theo kỳ hạn, lịch âm, tạm ngưng/huỷ |
| 14 | 14-dat-lich-tu-van-hoa-cuoi-su-kien.md | Markdown | Đặt lịch tư vấn, hợp đồng, hoàn cọc |
| 15 | 15-hoa-chia-buon.md | Markdown | Sản phẩm, nghi thức, băng đen, giọng giao tiếp |
| 16 | 16-hoa-doanh-nghiep.md | Markdown | Đơn số lượng lớn, công nợ, hoá đơn |
| 17 | 17-quy-trinh-xu-ly-khieu-nai.md | Markdown | Các bước, khung xử lý, chuyển cấp |
| 18 | 18-chinh-sach-bao-mat.md | Markdown | Dữ liệu thu thập, xác minh, quyền khách hàng |
| 19 | 19-huong-dan-cham-soc-hoa.html | HTML | Chăm sóc theo từng loại hoa, an toàn thú cưng |
| 20 | 20-y-nghia-hoa-goi-y-dip-tang.html | HTML | Ý nghĩa hoa, gợi ý mẫu theo dịp |
| 21 | 21-goi-y-loi-chuc-tren-thiep.html | HTML | Mẫu lời chúc, băng rôn, băng đen |
| 22 | 22-bang-gia-hoa-cuoi-su-kien-2026.pdf | PDF | 9 gói sự kiện, hạng mục thêm, phụ phí |
| 23 | 23-dieu-khoan-hop-dong-hoa-su-kien.pdf | PDF | Điều khoản hợp đồng (cọc, đổi ngày, huỷ, bất khả kháng) |
| 24 | 24-catalogue-hoa-20-10-2026.pdf | PDF | Catalogue 20/10, mã PNVN2010, lưu ý ngày cao điểm |
| 25 | 25-bang-gia-san-pham.csv | CSV | 50 sản phẩm: giá, thời gian chuẩn bị, cam kết tươi |
| 26 | 26-ma-khuyen-mai-2026.csv | CSV | 7 mã công khai và trạng thái |
| 27 | 27-phi-giao-hang-khu-vuc.csv | CSV | Phí ship, khung giờ, hỏa tốc theo khu vực |
| 28 | 28-lich-mua-hoa.csv | CSV | Lịch mùa 15 loại hoa theo tháng |
| 29 | 29-bang-gia-goi-dinh-ky-va-su-kien.xlsx | XLSX | 4 sheet: gói định kỳ, gói sự kiện, hạng mục thêm, phụ phí & cọc |

Tài liệu Markdown có front-matter (`doc_id`, `category`, `updated`, `related_policy`) để pipeline RAG gắn metadata và trích dẫn quy tắc.

## Tạo lại dữ liệu

```bash
pip install -r tools/requirements.txt
python tools/generate_seed.py      # → api/sql/seed.sql
python tools/build_docs.py         # → knowledge/22–29 (PDF dùng font Arial/DejaVu để in tiếng Việt)
cd api && python scripts/init_db.py
```

Các tài liệu Markdown/HTML (01–21), `policy.yaml`, `brand_voice.md` viết tay; khi đổi số trong `master_data.py`/`policy.yaml`, cần rà lại các tài liệu này cho khớp.
