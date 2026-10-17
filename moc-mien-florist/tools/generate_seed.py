"""Sinh api/sql/seed.sql — dữ liệu tổng hợp tái lập được (random seed cố định).

    python tools/generate_seed.py

- Dùng chung hàm tính giá (app/pricing.py) và lịch giao (app/schedule.py) với API nên số liệu luôn khớp.
- Mốc thời gian "hiện tại" = master_data.ANCHOR_NOW (2026-10-16 08:00 +07:00) = MOCK_NOW mặc định của API.
- Các bản ghi "kịch bản" (MM10001–MM10014, TV2001–TV2005, GD3001–GD3004, YC10001–YC10003) cố định
  để viết test case cho agent; phần còn lại sinh ngẫu nhiên.
"""
from __future__ import annotations

import json
import random
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(TOOLS))

import master_data as M  # noqa: E402
from app.pricing import choose_discount, evaluate_code, round_down, shipping_fee, tier_discount  # noqa: E402
from app.schedule import delivery_schedule  # noqa: E402

POLICY = yaml.safe_load((ROOT / "policy.yaml").read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(M.ANCHOR_NOW)
TZ = NOW.tzinfo
TODAY = NOW.date()
rng = random.Random(20261016)

PRODUCTS = {p["sku"]: p for p in M.PRODUCTS}
ZONES = {z["id"]: z for z in M.ZONES}
SLOTS = {s["code"]: s for s in M.SLOTS}
BRANCHES = {b["id"]: b for b in M.BRANCHES}
CODES = {c["code"]: dict(c, used_count=0, is_active=1) for c in M.DISCOUNT_CODES}
PLANS = {p["id"]: p for p in M.SUBSCRIPTION_PLANS}
THRESHOLD = POLICY["refund"]["auto_approve_max_vnd"]
MANAGER = "Trần Diễm Trang (Quản lý cửa hàng)"
SHIFT_LEAD = "Võ Minh Luân (Trưởng ca)"
STUDIO_MANAGER = "Châu Ngọc Hân (Quản lý studio)"
CONSULTANTS = ["Tư vấn viên Ngọc Hân", "Tư vấn viên Gia Huy"]
PREPAID = ("bank_transfer", "momo", "vnpay")


# =============================================================== tiện ích
def at(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


def iso(x: datetime) -> str:
    return x.isoformat(timespec="seconds")


def P(s: str) -> datetime:
    return datetime.fromisoformat(s)


def minutes(n: float) -> timedelta:
    return timedelta(minutes=round(n))


def slug(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower().replace(" ", "")


def weighted(pairs):
    items, weights = zip(*pairs)
    return rng.choices(items, weights=weights, k=1)[0]


# =============================================================== khách hàng
SURNAMES = [("Nguyễn", 25), ("Trần", 12), ("Lê", 10), ("Phạm", 6), ("Huỳnh", 7), ("Võ", 6), ("Phan", 4), ("Đặng", 3),
            ("Bùi", 3), ("Đỗ", 3), ("Hồ", 3), ("Ngô", 3), ("Dương", 3), ("Lý", 3), ("Trương", 3), ("Lâm", 3),
            ("Châu", 2), ("Thạch", 2), ("Quách", 2), ("Mai", 2), ("Danh", 1), ("Tạ", 1)]
F_MIDDLE = ["Thị", "Ngọc", "Thanh", "Kim", "Mỹ", "Bích", "Thu", "Hồng", "Yến", "Thị Mỹ", "Thị Kim", "Ngọc Bảo"]
F_FIRST = ["Hà", "Hương", "Lan", "Trang", "Vy", "Ngân", "Thảo", "Nhi", "Diễm", "Tuyết", "Hạnh", "My", "Như", "Trinh",
           "Quyên", "Phương", "Uyên", "Hằng", "Loan", "Xuân", "Mai", "Châu", "Thư", "Linh", "Anh", "Duyên", "Tiên"]
M_MIDDLE = ["Văn", "Minh", "Hoàng", "Quốc", "Thanh", "Hữu", "Gia", "Tấn", "Phước", "Trọng", "Công", "Đức"]
M_FIRST = ["Khang", "Tài", "Phúc", "Lộc", "Huy", "Khoa", "Tuấn", "Nam", "Bảo", "Trí", "Hiếu", "Thịnh", "Nhân", "Duy",
           "Đạt", "Vinh", "Long", "Phong", "Toàn", "Kiệt", "Sơn", "Quân", "Tâm", "Nghĩa"]

STREETS = {
    "Z1": (["Trần Văn Hoài", "Nguyễn Văn Cừ", "30 Tháng 4", "Mậu Thân", "3 Tháng 2", "Hòa Bình", "Trần Hưng Đạo",
            "Nguyễn Trãi", "Lý Tự Trọng", "Đề Thám", "Nguyễn Việt Hồng", "Hùng Vương", "Trần Phú", "Võ Văn Tần"],
           ["phường Ninh Kiều", "phường Cái Khế", "phường Tân An", "phường An Bình"]),
    "Z2": (["Lê Hồng Phong", "Bùi Hữu Nghĩa", "Cách Mạng Tháng 8", "Trần Quang Diệu", "Võ Nguyên Giáp", "Trần Chiên",
            "Phạm Hùng", "Nguyễn Văn Linh", "Lê Bình"],
           ["phường Bình Thủy", "phường Long Tuyền", "phường Cái Răng", "phường Hưng Phú"]),
    "Z3": (["Quốc lộ 91", "Lộ Vòng Cung", "Trần Hưng Đạo", "Đường 26 Tháng 3"],
           ["phường Ô Môn", "phường Phước Thới", "xã Phong Điền", "xã Nhơn Ái"]),
    "Z4": (["Quốc lộ 91", "Quốc lộ 80", "Tỉnh lộ 919", "Tỉnh lộ 922"],
           ["phường Thốt Nốt", "xã Thới Lai", "xã Cờ Đỏ", "xã Vĩnh Thạnh"]),
}
PHONE_PREFIXES = ["090", "091", "093", "094", "096", "097", "098", "070", "076", "077", "078", "079", "081", "083",
                  "084", "085", "032", "033", "034", "035", "036", "037", "038", "039", "088", "089"]
used_phones: set[str] = set()


def gen_phone() -> str:
    while True:
        p = rng.choice(PHONE_PREFIXES) + "".join(str(rng.randint(0, 9)) for _ in range(7))
        if p not in used_phones:
            used_phones.add(p)
            return p


def gen_name(gender: str) -> tuple[str, str]:
    sur = weighted(SURNAMES)
    if gender == "nu":
        first = rng.choice(F_FIRST)
        return f"{sur} {rng.choice(F_MIDDLE)} {first}", first
    first = rng.choice(M_FIRST)
    return f"{sur} {rng.choice(M_MIDDLE)} {first}", first


def gen_address(zone: str) -> str:
    streets, wards = STREETS[zone]
    number = rng.randint(1, 320)
    if rng.random() < 0.3:
        return f"{number}/{rng.randint(2, 60)} {rng.choice(streets)}, {rng.choice(wards)}, TP. Cần Thơ"
    return f"{number} {rng.choice(streets)}, {rng.choice(wards)}, TP. Cần Thơ"


customers: dict[str, dict] = {}


def add_customer(cid, name, phone, gender, zone, address, *, tier=None, total=None, birthday=None, email=None,
                 created="2025-01-01T09:00:00+07:00", ctype="individual", company=None, note=None):
    used_phones.add(phone)
    customers[cid] = dict(id=cid, full_name=name, phone=phone, email=email, gender=gender, birthday=birthday,
                          address=address, zone=zone, customer_type=ctype, company_name=company, tier=tier,
                          points=0, total_spent_12m=total, created_at=created, note=note, fixed=tier is not None)


# --- khách kịch bản (cố định)
add_customer("KH0001", "Nguyễn Thị Thu Hà", "0901234567", "nu", "Z1", "12 Hòa Bình, phường Ninh Kiều, TP. Cần Thơ",
             tier="vip", total=14560000, birthday="1988-10-22", email="thuha.nguyen@example.com",
             created="2023-02-14T10:20:00+07:00", note="Khách VIP, hay đặt hoa tặng đối tác.")
add_customer("KH0002", "Trần Minh Khang", "0912345678", "nam", "Z1", "88 Nguyễn Văn Cừ, phường An Bình, TP. Cần Thơ",
             tier="member", total=1825000, birthday="1999-05-09", created="2025-12-20T19:05:00+07:00")
add_customer("KH0003", "Lê Ngọc Bích", "0933456789", "nu", "Z2", "23 Lê Hồng Phong, phường Bình Thủy, TP. Cần Thơ",
             tier="loyal", total=4250000, birthday="1992-03-03", email="ngocbich.le@example.com",
             created="2024-06-01T08:40:00+07:00")
add_customer("KH0004", "Phạm Quốc Bảo", "0939111222", "nam", "Z2", "Lô 18 KCN Trà Nóc 1, phường Bình Thủy, TP. Cần Thơ",
             tier="loyal", total=7410000, email="hanhchinh@gaosachtaydo.example.com", created="2026-09-01T09:00:00+07:00",
             ctype="business", company="Công ty TNHH Gạo Sạch Tây Đô", note="Đầu mối: phòng hành chính. Cần xuất hoá đơn VAT.")
add_customer("KH0005", "Huỳnh Văn Tài", "0987654321", "nam", "Z1", "56 Trần Hưng Đạo, phường Ninh Kiều, TP. Cần Thơ",
             tier="member", total=1250000, birthday="1995-11-30", created="2025-08-15T14:00:00+07:00",
             note="Sắp cưới (TV2001).")
add_customer("KH0006", "Phạm Gia Huy", "0978123456", "nam", "Z1", "141 Đường 30 Tháng 4, phường Tân An, TP. Cần Thơ",
             tier="member", total=1653000, birthday="1996-07-21", created="2026-09-25T21:10:00+07:00")
add_customer("KH0007", "Đặng Thị Kim Ngân", "0905678123", "nu", "Z2", "9 Trần Chiên, phường Cái Răng, TP. Cần Thơ",
             tier="member", total=650000, birthday="1997-12-12", created="2026-06-10T11:30:00+07:00")
add_customer("KH0008", "Lâm Thanh Tú", "0918222333", "nam", "Z3", "77 Quốc lộ 91, phường Ô Môn, TP. Cần Thơ",
             tier="member", total=0, birthday="1990-01-25", created="2026-10-10T20:45:00+07:00")
SCENARIO_CUSTOMERS = set(customers)

# --- khách ngẫu nhiên KH0009..KH0060 (4 khách doanh nghiệp)
BUSINESSES = ["Công ty CP Thủy Sản Mê Kông Xanh", "Nha khoa Nụ Cười Tây Đô", "Trường Mầm non Hoa Sen Nhỏ",
              "Nhà hàng Cá Lóc Miệt Vườn"]
for n in range(9, 61):
    cid = f"KH{n:04d}"
    gender = rng.choice(["nu", "nu", "nu", "nam", "nam"])
    name, _ = gen_name(gender)
    zone = weighted([("Z1", 50), ("Z2", 30), ("Z3", 13), ("Z4", 7)])
    created = datetime(2023, 1, 1, tzinfo=TZ) + timedelta(days=rng.randint(0, 1370), hours=rng.randint(8, 21))
    biz = BUSINESSES[n - 9] if n - 9 < len(BUSINESSES) else None
    email = None
    if biz:
        email = f"lienhe@{slug(biz.split(' ', 2)[-1])[:14]}.example.com"
    elif rng.random() < 0.55:
        email = f"{slug(name.split()[-1])}.{slug(name.split()[0])}{rng.randint(1, 99)}@example.com"
    add_customer(cid, name, gen_phone(), gender, "Z1" if biz else zone, gen_address("Z1" if biz else zone),
                 birthday=None if biz else f"{rng.randint(1965, 2004)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                 email=email, created=iso(created), ctype="business" if biz else "individual", company=biz)
    customers[cid]["tier_target"] = "loyal" if biz else weighted([("member", 60), ("loyal", 28), ("vip", 12)])
RANDOM_CUSTOMERS = [c for c in customers if c not in SCENARIO_CUSTOMERS]
BUSINESS_RANDOM = [c for c in RANDOM_CUSTOMERS if customers[c]["customer_type"] == "business"]
for c in RANDOM_CUSTOMERS:  # hạng tạm để tính ưu đãi; chốt lại theo tổng chi tiêu ở cuối
    customers[c]["tier"] = customers[c]["tier_target"]


# =============================================================== đơn hàng
CARD_MESSAGES = {
    "sinh_nhat": ["Chúc mừng sinh nhật! Mong mọi điều tốt đẹp nhất sẽ đến với bạn.",
                  "Happy birthday! Tuổi mới thật nhiều niềm vui nhé.", "Mừng sinh nhật mẹ, con thương mẹ nhiều!"],
    "ky_niem": ["Cảm ơn em đã đồng hành cùng anh. Kỷ niệm vui vẻ nhé!", "Happy anniversary – thương em nhiều."],
    "phu_nu_20_10": ["Chúc mừng ngày Phụ nữ Việt Nam 20/10! Luôn xinh đẹp và hạnh phúc nhé.",
                     "20/10 vui vẻ, cảm ơn chị đã luôn tận tâm.", "Gửi mẹ yêu nhân ngày 20/10."],
    "vu_lan": ["Mùa Vu Lan, con kính chúc ba mẹ luôn mạnh khỏe.", "Con cảm ơn mẹ vì tất cả."],
    "trung_thu": ["Trung thu đoàn viên, chúc gia đình mình an vui.", "Chúc Trung thu ấm áp!"],
    "khai_truong": ["Chúc mừng khai trương – Hồng phát, đại cát!", "Khai trương hồng phát, vạn sự như ý."],
    "chia_buon": ["Thành kính phân ưu cùng gia đình.", "Vô cùng thương tiếc, xin chia buồn cùng tang quyến."],
    "tot_nghiep": ["Chúc mừng tân cử nhân! Tự hào về bạn.", "Congrats! Hành trình mới thật rực rỡ nhé."],
    "tham_benh": ["Chúc bác mau khỏe để về nhà.", "Mong chị sớm bình phục!"],
    "tri_an_doi_tac": ["Trân trọng cảm ơn quý đối tác đã đồng hành.", "Kính chúc quý khách hàng an khang thịnh vượng."],
}
OCCASION_POOLS = {
    "sinh_nhat": (["BH01", "BH04", "BH07", "GH01", "BH05", "GH03", "BH11", "LC03"], ["PK01", "PK02", "PK03", "PK06"]),
    "ky_niem": (["BH02", "BH03", "GH03", "BH06", "BH04"], ["PK01", "PK03", "PK05"]),
    "phu_nu_20_10": (["BH02", "BH04", "GH01", "GH03", "BH06", "BH11", "GH02", "BH07"], ["PK01", "PK03"]),
    "vu_lan": (["BH04", "GH02", "BH05", "LC03", "GH04"], ["PK01"]),
    "trung_thu": (["GH02", "GH04", "GH01"], ["PK01"]),
    "khai_truong": (["KT01", "KT02", "KT03", "LC02", "LC01"], []),
    "chia_buon": (["CB01", "CB02", "CB03"], []),
    "tot_nghiep": (["BH08", "BH01", "BH07"], ["PK02", "PK06"]),
    "tham_benh": (["GH04", "BH01", "LC03", "BN01"], []),
    "tri_an_doi_tac": (["GH02", "LC01", "BN02", "LC02"], ["PK01"]),
    "cung_ram": (["BN03"], []),
    "trang_tri": (["BN01", "HS02", "HS01", "BN02"], ["PK04", "PK05"]),
    "hoa_le": (["HL01", "HL03", "HL05", "HL06", "HL08", "HL09", "HL10", "HL11", "HL07"], []),
}
FAIL_NOTES = ["Người nhận không nghe máy sau 3 cuộc gọi; hoa lưu tại cửa hàng 24 giờ.",
              "Địa chỉ người nhận không chính xác, không liên lạc được người đặt.",
              "Người nhận từ chối nhận hoa (không quen người gửi)."]
CANCEL_REASONS = ["Khách đổi ý, không cần hoa nữa.", "Người nhận đi công tác đột xuất.", "Khách đặt trùng đơn.",
                  "Sự kiện bị hoãn.", "Khách muốn đặt mẫu khác, sẽ đặt lại sau."]

orders: list[dict] = []


def scenario(code, cid, *, created, d, slot, items, pm, final, zone=None, recipient=None, channel="website",
             occasion=None, code_try=None, card=None, surprise=False, pickup_branch=None, paid_at=None,
             delivered_at=None, failed_at=None, cancelled_at=None, cancel_reason=None, note=None, expect_total=None):
    orders.append(dict(code=code, customer_id=cid, created=P(created), d=date.fromisoformat(d), slot=slot,
                       items=items, pm=pm, final=final, zone=zone, recipient=recipient, channel=channel,
                       occasion=occasion, code_try=code_try, card=card, surprise=surprise, pickup_branch=pickup_branch,
                       paid_at=P(paid_at) if paid_at else None, delivered_at=P(delivered_at) if delivered_at else None,
                       failed_at=P(failed_at) if failed_at else None,
                       cancelled_at=P(cancelled_at) if cancelled_at else None, cancel_reason=cancel_reason,
                       note=note, express=False, expect_total=expect_total, scenario=True))


scenario("MM10001", "KH0002", created="2026-10-14T20:15:00+07:00", d="2026-10-20", slot="K2", zone="Z1",
         recipient=("Lê Thị Mỹ Duyên", "0976543210", "45 Hẻm 51 Đường 3 Tháng 2, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH02", 1), ("PK01", 1)], pm="momo", final="confirmed", occasion="phu_nu_20_10", code_try="PNVN2010",
         card="Chúc em 20/10 luôn rạng rỡ như hoa. Yêu em! – Khang", surprise=True,
         paid_at="2026-10-14T20:18:00+07:00", expect_total=418000)
scenario("MM10002", "KH0001", created="2026-10-15T10:30:00+07:00", d="2026-10-16", slot="K5", zone="Z2",
         recipient=("BS. Trương Minh Đức", "0939456789", "Phòng khám Nha khoa An Tâm, 102 Trần Chiên, phường Cái Răng, TP. Cần Thơ"),
         items=[("LC01", 1)], pm="bank_transfer", final="confirmed", channel="hotline", occasion="khai_truong",
         card="Chúc mừng khai trương phòng khám – Hồng phát! Thu Hà", paid_at="2026-10-15T11:02:00+07:00",
         expect_total=1242000)
scenario("MM10003", "KH0003", created="2026-10-15T19:40:00+07:00", d="2026-10-16", slot="K2", zone="Z1",
         recipient=("Nguyễn Thị Sáu", "0939876543", "17 Lý Tự Trọng, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH04", 1), ("PK03", 1)], pm="momo", final="arranging", channel="zalo", occasion="sinh_nhat",
         card="Mừng sinh nhật mẹ, con thương mẹ nhiều! – Bích", paid_at="2026-10-15T19:43:00+07:00",
         expect_total=675000)
scenario("MM10004", "KH0002", created="2026-10-14T09:00:00+07:00", d="2026-10-15", slot="K4", zone="Z2",
         recipient=("Võ Thị Thanh Tâm", "0945112233", "60 Bùi Hữu Nghĩa, phường Bình Thủy, TP. Cần Thơ"),
         items=[("BH11", 1)], pm="bank_transfer", final="delivered", occasion="sinh_nhat",
         card="Chúc mừng sinh nhật chị Tâm! – Team Marketing", paid_at="2026-10-14T09:20:00+07:00",
         delivered_at="2026-10-15T16:20:00+07:00", expect_total=515000)
scenario("MM10005", "KH0003", created="2026-10-09T18:00:00+07:00", d="2026-10-10", slot="K3", zone="Z1",
         recipient=("Phan Thị Hồng Nhung", "0907333444", "210 Đường 30 Tháng 4, phường Tân An, TP. Cần Thơ"),
         items=[("BH04", 1)], pm="bank_transfer", final="delivered", occasion="sinh_nhat",
         card="Happy birthday Nhung!", paid_at="2026-10-09T18:15:00+07:00", delivered_at="2026-10-10T13:45:00+07:00",
         expect_total=523000)
scenario("MM10006", "KH0001", created="2026-10-13T21:00:00+07:00", d="2026-10-14", slot="K4", zone="Z3",
         recipient=("Nguyễn Văn Bảy", "0918765432", "Ấp Nhơn Lộc, xã Phong Điền, TP. Cần Thơ"),
         items=[("GH04", 1), ("PK01", 1)], pm="vnpay", final="delivered", occasion="tham_benh",
         card="Con chúc ông ngoại mau khỏe. – Thu Hà", paid_at="2026-10-13T21:04:00+07:00",
         delivered_at="2026-10-14T19:25:00+07:00", note="Xe giao gặp sự cố trên Lộ Vòng Cung, giao trễ.",
         expect_total=985000)
scenario("MM10007", "KH0002", created="2026-10-08T12:00:00+07:00", d="2026-10-12", slot="K3", zone="Z1",
         recipient=("Lê Thị Mỹ Duyên", "0976543210", "45 Hẻm 51 Đường 3 Tháng 2, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH06", 1)], pm="bank_transfer", final="cancelled", occasion="ky_niem",
         paid_at="2026-10-08T12:30:00+07:00", cancelled_at="2026-10-10T09:00:00+07:00",
         cancel_reason="Khách đổi kế hoạch, sẽ đặt lại dịp 20/10.", expect_total=890000)
scenario("MM10008", "KH0004", created="2026-10-15T15:00:00+07:00", d="2026-10-22", slot="K1", zone="Z2",
         recipient=("Phạm Quốc Bảo", "0939111222", "Lô 7 Khu đô thị Nam Cần Thơ, phường Hưng Phú, TP. Cần Thơ"),
         items=[("KT03", 1), ("KT02", 1)], pm="bank_transfer", final="pending", channel="hotline",
         occasion="khai_truong", card="Mừng khai trương văn phòng Hưng Phú – Gạo Sạch Tây Đô",
         note="Cần xuất hoá đơn VAT cho Công ty TNHH Gạo Sạch Tây Đô.", expect_total=3895000)
scenario("MM10009", "KH0005", created="2026-10-15T20:00:00+07:00", d="2026-10-17", slot="K3", pickup_branch="CN02",
         items=[("HL01", 20), ("HL07", 1)], pm="cash", final="confirmed", channel="zalo", occasion="hoa_le",
         note="Khách tự gói, chỉ lấy hoa lẻ.", expect_total=480000)
scenario("MM10010", "KH0005", created="2026-10-11T10:00:00+07:00", d="2026-10-12", slot="K2", zone="Z1",
         recipient=("Trần Ngọc Như Ý", "0961234098", "33 Nguyễn Trãi, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH01", 1), ("PK02", 1)], pm="momo", final="delivered", occasion="sinh_nhat",
         card="Sinh nhật vui vẻ nha Ý!", paid_at="2026-10-11T10:05:00+07:00",
         delivered_at="2026-10-12T11:05:00+07:00", expect_total=500000)
scenario("MM10011", "KH0005", created="2026-10-14T08:00:00+07:00", d="2026-10-15", slot="K2", zone="Z1",
         recipient=("Hồ Thị Bé Ba", "0939001122", "8/12 Mậu Thân, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH05", 1)], pm="cod", final="failed_delivery", occasion="tham_benh",
         card="Chúc dì Ba mau khỏe!", failed_at="2026-10-15T11:40:00+07:00",
         note="Người nhận không nghe máy sau 3 cuộc gọi; hoa lưu tại CN01 đến 12:00 ngày 16/10.", expect_total=405000)
scenario("MM10012", "KH0006", created="2026-10-13T14:00:00+07:00", d="2026-10-17", slot="K5", zone="Z1",
         recipient=("Ngô Thị Thanh Vy", "0937555666", "Nhà hàng ven sông, Bến Ninh Kiều, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH09", 1)], pm="bank_transfer", final="confirmed", occasion="cau_hon",
         card="Làm vợ anh nhé! – Gia Huy", surprise=True, paid_at="2026-10-13T14:10:00+07:00", expect_total=2990000)
scenario("MM10013", "KH0003", created="2026-09-01T16:00:00+07:00", d="2026-09-02", slot="K3", zone="Z2",
         recipient=("Lê Văn Hải", "0915678901", "5 Cách Mạng Tháng 8, phường Bình Thủy, TP. Cần Thơ"),
         items=[("GH02", 1)], pm="momo", final="delivered", occasion="tri_an_doi_tac", code_try="QUOCKHANH",
         paid_at="2026-09-01T16:05:00+07:00", delivered_at="2026-09-02T15:50:00+07:00",
         note="Giao trễ 50 phút do kẹt xe dịp lễ.", expect_total=635000)
scenario("MM10014", "KH0003", created="2026-10-03T17:00:00+07:00", d="2026-10-04", slot="K2", zone="Z1",
         recipient=("Lê Ngọc Bích", "0933456789", "Văn phòng tầng 3, 99 Hòa Bình, phường Ninh Kiều, TP. Cần Thơ"),
         items=[("BH05", 1), ("PK01", 1)], pm="bank_transfer", final="delivered", occasion="trang_tri",
         paid_at="2026-10-03T17:10:00+07:00", delivered_at="2026-10-04T10:40:00+07:00",
         note="Khách báo 2 bông cát tường bị dập khi nhận; đã tặng mã xin lỗi YC10003.", expect_total=401000)

capacity = Counter()
for o in orders:
    if o["final"] != "cancelled":
        branch = o["pickup_branch"] or ZONES[o["zone"]]["default_branch_id"]
        capacity[(branch, o["d"], o["slot"])] += 1


def pick_date() -> date:
    start = date(2026, 8, 1)
    days = [start + timedelta(days=i) for i in range((date(2026, 10, 25) - start).days + 1)]
    weights = []
    for d in days:
        w = 1.0
        if d.weekday() >= 5:
            w *= 1.3
        if date(2026, 8, 24) <= d <= date(2026, 8, 27):
            w *= 3.5
        if date(2026, 9, 20) <= d <= date(2026, 9, 25):
            w *= 2.5
        if date(2026, 10, 17) <= d <= date(2026, 10, 20):
            w *= 5 if d.day != 20 else 8
        if d > date(2026, 10, 20):
            w *= 0.8
        if d == TODAY:
            w *= 4
        weights.append(w)
    return rng.choices(days, weights=weights, k=1)[0]


def pick_occasion(d: date) -> str:
    if date(2026, 10, 17) <= d <= date(2026, 10, 20) and rng.random() < 0.7:
        return "phu_nu_20_10"
    if date(2026, 8, 24) <= d <= date(2026, 8, 27) and rng.random() < 0.55:
        return "vu_lan"
    if date(2026, 9, 20) <= d <= date(2026, 9, 25) and rng.random() < 0.45:
        return "trung_thu"
    return weighted([("sinh_nhat", 30), ("ky_niem", 12), ("khai_truong", 8), ("chia_buon", 6), ("tham_benh", 6),
                     ("tri_an_doi_tac", 7), ("tot_nghiep", 5), ("trang_tri", 6), ("hoa_le", 8), ("cung_ram", 5)])


def pick_items(occasion: str) -> list[tuple[str, int]]:
    mains, extras = OCCASION_POOLS[occasion]
    if occasion == "hoa_le":
        skus = rng.sample(mains, k=rng.choice([1, 1, 2]))
        return [(s, 1 if s == "HL07" else rng.choice([5, 10, 10, 15, 20, 30])) for s in skus]
    if occasion == "cung_ram":
        return [("BN03", 2)]
    items = [(rng.choice(mains), 1)]
    if extras and rng.random() < 0.45:
        items.append((rng.choice(extras), 1))
    return items


for _ in range(126):
    for _attempt in range(30):
        d = pick_date()
        occasion = pick_occasion(d)
        items = pick_items(occasion)
        is_biz_occ = occasion in ("khai_truong", "tri_an_doi_tac", "chia_buon")
        cid = rng.choice(BUSINESS_RANDOM) if is_biz_occ and rng.random() < 0.4 else rng.choice(RANDOM_CUSTOMERS)
        pickup = occasion == "hoa_le" or (occasion in ("sinh_nhat", "trang_tri") and rng.random() < 0.08)
        zone = None if pickup else (customers[cid]["zone"] if rng.random() < 0.6 else
                                    weighted([("Z1", 55), ("Z2", 28), ("Z3", 11), ("Z4", 6)]))
        lead = max([POLICY["ordering"]["min_lead_time_hours"]] + [PRODUCTS[s]["lead"] for s, _ in items])
        express = (not pickup and zone in ("Z1", "Z2") and d < TODAY and lead <= 3
                   and d.strftime("%m-%d") not in POLICY["ordering"]["peak_days"]
                   and not any(PRODUCTS[s]["category"] in POLICY["ordering"]["express"]["excluded_categories"]
                               for s, _ in items)
                   and rng.random() < 0.05)
        if pickup:
            branch = "CN01" if rng.random() < 0.65 else "CN02"
            allowed = [s for s in SLOTS if SLOTS[s]["end_time"] <= BRANCHES[branch]["close_time"]]
        else:
            branch = ZONES[zone]["default_branch_id"]
            allowed = ZONES[zone]["allowed_slots"].split(",")
        slot = None if express else weighted([(s, {"K1": 2, "K2": 4, "K3": 3, "K4": 4, "K5": 3, "K6": 1}[s])
                                              for s in allowed])
        if slot and not pickup and SLOTS[slot]["end_time"] > BRANCHES[branch]["close_time"]:
            branch = "CN01"
        if zone == "Z4" and (d - TODAY).days < 1 and d >= TODAY:
            continue
        if slot and capacity[(branch, d, slot)] >= BRANCHES[branch]["slot_capacity"]:
            continue
        if express:
            created = at(d, f"{rng.randint(8, 15):02d}:{rng.choice(['05', '20', '35', '50'])}")
            start = created
        else:
            start = at(d, SLOTS[slot]["start_time"])
            hours_before = weighted([(rng.uniform(0, 9), 30), (rng.uniform(9, 45), 45), (rng.uniform(45, 165), 25)])
            created = start - timedelta(hours=lead + hours_before)
            latest = min(start - timedelta(hours=lead), NOW - timedelta(minutes=20))
            if created > latest:
                created = latest - minutes(rng.uniform(5, 600))
            if start - created < timedelta(hours=lead):
                continue
        if created < datetime(2026, 7, 25, tzinfo=TZ) or created > NOW:
            continue
        created = created.replace(second=0, microsecond=0)
        break
    else:
        raise RuntimeError("Không sinh được đơn hợp lệ")

    # --- trạng thái cuối
    if express:
        end = created + timedelta(hours=2)
    else:
        end = at(d, SLOTS[slot]["end_time"])
    if end + timedelta(minutes=30) <= NOW:
        final = weighted([("delivered", 80), ("cancelled", 8), ("failed_delivery", 4), ("refunded", 8)])
    elif start - timedelta(hours=2) <= NOW:
        final = "delivering" if NOW >= start - timedelta(minutes=20) else "arranging"
    else:
        final = weighted([("cancelled", 10), ("pending", 15), ("confirmed", 75)])
    if pickup and final == "failed_delivery":
        final = "delivered"
    if pickup and final == "delivering":
        final = "arranging"

    # --- thanh toán
    if pickup:
        pm = weighted([("cash", 45), ("momo", 25), ("bank_transfer", 20), ("card", 10)])
    else:
        pm = weighted([("cod", 25), ("bank_transfer", 40), ("momo", 25), ("vnpay", 10)])
    if final == "pending" and pm not in PREPAID:
        final = "confirmed"

    recipient = None
    if not pickup:
        if rng.random() < 0.25:
            c = customers[cid]
            recipient = (c["full_name"], c["phone"], gen_address(zone))
        else:
            rname, _ = gen_name(rng.choice(["nu", "nu", "nam"]))
            recipient = (rname, gen_phone(), gen_address(zone))
    orders.append(dict(code=None, customer_id=cid, created=created, d=d, slot=slot, items=items, pm=pm, final=final,
                       zone=zone, recipient=recipient,
                       channel=weighted([("website", 40), ("zalo", 25), ("hotline", 15), ("facebook", 12), ("store", 8)]),
                       occasion=occasion, code_try=None, card=rng.choice(CARD_MESSAGES[occasion]) if occasion in CARD_MESSAGES and not pickup else None,
                       surprise=rng.random() < 0.12 and not pickup, pickup_branch=branch if pickup else None,
                       paid_at=None, delivered_at=None, failed_at=None, cancelled_at=None, cancel_reason=None,
                       note=None, express=express, expect_total=None, scenario=False, branch_hint=branch))
    if final != "cancelled" and slot:
        capacity[(branch, d, slot)] += 1

# --- đánh mã đơn ngẫu nhiên theo thứ tự thời gian tạo
orders.sort(key=lambda o: o["created"])
next_no = 10015
for o in orders:
    if o["code"] is None:
        o["code"] = f"MM{next_no}"
        next_no += 1

# =============================================================== tính giá + trạng thái + yêu cầu
order_rows, item_rows, event_rows, request_rows, goodwill_codes = [], [], [], [], []
prior_orders = Counter()
code_used = Counter()
req_no = [10004]  # YC10001..YC10003 dành cho kịch bản


def new_request(code: str | None = None, **fields) -> dict:
    if code is None:
        code = f"YC{req_no[0]}"
        req_no[0] += 1
    row = dict(code=code, type=None, customer_id=None, ref_type=None, ref_code=None, reason_code=None, description=None,
               amount=None, payload=None, status=None, requires_approval=0, approval_rules=None, resolution_note=None,
               issued_code=None, created_by="agent", created_at=None, decided_at=None, decided_by=None)
    row.update(fields)
    request_rows.append(row)
    return row


def new_goodwill(customer_id: str, created: datetime, percent: int = 10, fixed: str | None = None) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = fixed or "XL" + "".join(rng.choice(alphabet) for _ in range(6))
    goodwill_codes.append(dict(code=code, description=f"Mã xin lỗi: giảm {percent}% (tối đa 100.000đ) cho 1 đơn",
                               discount_type="percent", value=percent, max_discount=100000, min_order=0,
                               applicable_categories=None, valid_from=created.date().isoformat(),
                               valid_to=(created.date() + timedelta(days=30)).isoformat(), usage_limit=1, used_count=0,
                               per_customer_limit=1, customer_id=customer_id, kind="goodwill", is_active=1,
                               created_by="agent", created_at=iso(created)))
    return code


def ev(code, etype, when, frm=None, to=None, detail=None, actor="system"):
    if when <= NOW:
        event_rows.append(dict(order_code=code, event_type=etype, from_status=frm, to_status=to, detail=detail,
                               actor=actor, created_at=iso(when)))


for o in orders:
    cust = customers[o["customer_id"]]
    lines = []
    for sku, qty in o["items"]:
        p = PRODUCTS[sku]
        lines.append(dict(sku=sku, product_name=p["name"], quantity=qty, unit_price=p["price"],
                          line_total=p["price"] * qty, category=p["category"], lead=p["lead"]))
    subtotal = sum(l["line_total"] for l in lines)
    zone = ZONES.get(o["zone"]) if o["zone"] else None
    tier = cust["tier"]
    ship = shipping_fee(zone, subtotal, tier, POLICY) if zone else 0
    express_fee = POLICY["ordering"]["express"]["fee"] if o["express"] else 0
    tier_amt = tier_discount(subtotal, tier, POLICY)
    code_try = o["code_try"]
    if code_try is None and not o["scenario"]:
        cdate = o["created"].date()
        candidates = [c for c in ("PNVN2010", "TRUNGTHU26", "QUOCKHANH") if CODES[c]["valid_from"] <= cdate.isoformat() <= CODES[c]["valid_to"]]
        if prior_orders[o["customer_id"]] == 0 and cust["created_at"] >= "2026-07-01" and rng.random() < 0.5:
            code_try = "CHAOBAN30"
        elif candidates and rng.random() < 0.45:
            code_try = candidates[0]
        elif cust["birthday"] and int(cust["birthday"][5:7]) == cdate.month and rng.random() < 0.5:
            code_try = "SINHNHAT10"
    code_amt = 0
    if code_try:
        usage = {"customer_used": code_used[(code_try, o["customer_id"])],
                 "customer_prior_orders": prior_orders[o["customer_id"]]}
        code_amt, err, _ = evaluate_code(CODES[code_try], lines, subtotal, o["created"].date(), cust, usage)
        if err and o["scenario"]:
            raise RuntimeError(f"{o['code']}: mã {code_try} lỗi {err}")
    source, discount = choose_discount(code_amt, tier_amt)
    total = subtotal + ship + express_fee - discount
    custom = max(l["lead"] for l in lines) >= POLICY["order_changes"]["cancellation"]["custom_order_lead_time_hours"]

    pm = o["pm"]
    if not o["scenario"]:
        if pm == "cod" and (zone is None or zone["id"] not in ("Z1", "Z2") or total >= 2000000 or custom):
            pm = "bank_transfer"
        if pm in ("cash", "card") and (total >= 2000000 or custom):
            pm = "bank_transfer"
    if o["expect_total"] is not None and total != o["expect_total"]:
        raise RuntimeError(f"{o['code']}: tổng {total} khác kỳ vọng {o['expect_total']}")

    if source == "code":
        CODES[code_try]["used_count"] += 1
        code_used[(code_try, o["customer_id"])] += 1

    # ---- mốc thời gian
    branch = o.get("pickup_branch") or (o.get("branch_hint") if not o["scenario"] else None) or ZONES[o["zone"]]["default_branch_id"]
    if o["slot"] and o["zone"] and SLOTS[o["slot"]]["end_time"] > BRANCHES[branch]["close_time"]:
        branch = "CN01"
    if o["express"]:
        start = o["created"]
        end = o["created"] + timedelta(hours=2)
    else:
        start, end = at(o["d"], SLOTS[o["slot"]]["start_time"]), at(o["d"], SLOTS[o["slot"]]["end_time"])
    final = o["final"]
    created = o["created"]
    paid_at = o["paid_at"]
    if not o["scenario"] and pm in PREPAID and final != "pending":
        paid_at = min(created + minutes(rng.uniform(3, 80)), NOW - timedelta(minutes=1))
    delivered_at = o["delivered_at"]
    if final in ("delivered", "refunded") and delivered_at is None:
        if o["express"]:
            delivered_at = created + minutes(rng.uniform(55, 112))
        else:
            r = rng.random()
            if r < 0.85:
                delivered_at = start + minutes(rng.uniform(10, 115))
            elif r < 0.95:
                delivered_at = end + minutes(rng.uniform(10, 50))
            else:
                delivered_at = end + minutes(rng.uniform(61, 115))
    failed_at = o["failed_at"]
    if final == "failed_delivery" and failed_at is None:
        failed_at = start + minutes(rng.uniform(30, 110))
    cancelled_at = o["cancelled_at"]
    cancel_reason = o["cancel_reason"]
    if final == "cancelled" and cancelled_at is None:
        latest = min(start - timedelta(hours=4), NOW - timedelta(minutes=30))
        earliest = created + timedelta(minutes=15)
        cancelled_at = earliest + (latest - earliest) * rng.random() if latest > earliest else earliest
        cancelled_at = cancelled_at.replace(second=0, microsecond=0)
        cancel_reason = rng.choice(CANCEL_REASONS)
    if paid_at and cancelled_at and paid_at > cancelled_at:
        paid_at = None
    if final in ("delivered", "refunded") and pm not in PREPAID:
        paid_at = delivered_at

    paid_amount = total if paid_at and paid_at <= NOW else 0
    refunded_amount = 0
    payment_status = "paid" if paid_amount else "unpaid"
    note = o["note"]
    if final == "failed_delivery" and not note:
        note = rng.choice(FAIL_NOTES)

    # ---- dòng thời gian
    initial = "pending" if pm in PREPAID else "confirmed"
    actor_created = "customer" if o["channel"] in ("website", "facebook") else "staff"
    ev(o["code"], "created", created, to=initial, detail=f"Tạo đơn qua kênh {o['channel']}.", actor=actor_created)
    if initial == "pending" and paid_at:
        ev(o["code"], "status_changed", paid_at, "pending", "confirmed", "Đã nhận thanh toán.")
    state = "confirmed" if (initial == "confirmed" or paid_at) else "pending"
    if final == "cancelled":
        ev(o["code"], "cancelled", cancelled_at, state, "cancelled", cancel_reason, actor="agent")
    elif final != "pending":
        arr_at = max(start - timedelta(hours=2), created + timedelta(minutes=10))
        if final in ("arranging", "delivering", "delivered", "refunded", "failed_delivery"):
            ev(o["code"], "status_changed", arr_at, "confirmed", "arranging", None, actor="staff")
        if final in ("delivering", "delivered", "refunded", "failed_delivery") and not (o["pickup_branch"]):
            ev(o["code"], "status_changed", max(start - timedelta(minutes=20), arr_at + timedelta(minutes=30)),
               "arranging", "delivering", None, actor="staff")
        if final in ("delivered", "refunded"):
            ev(o["code"], "status_changed", delivered_at, "delivering" if not o["pickup_branch"] else "arranging",
               "delivered", "Khách đã nhận tại cửa hàng." if o["pickup_branch"] else "Giao thành công.", actor="staff")
        if final == "failed_delivery":
            ev(o["code"], "status_changed", failed_at, "delivering", "failed_delivery", note, actor="staff")

    # ---- yêu cầu phát sinh
    if final == "cancelled":
        hours = (start - cancelled_at).total_seconds() / 3600
        tiers = POLICY["order_changes"]["cancellation"]["custom_order_tiers" if custom else "standard_tiers"]
        last = min(t["min_hours_before_slot"] for t in tiers)
        pct = next((t["refund_percent"] for t in sorted(tiers, key=lambda t: -t["min_hours_before_slot"])
                    if hours >= t["min_hours_before_slot"]), 0)
        amount = round_down(paid_amount * pct / 100)
        if hours < last or (not paid_amount and hours < POLICY["order_changes"]["cancellation"]["unpaid_free_min_hours"]):
            new_request(type="cancellation", customer_id=o["customer_id"], ref_type="order", ref_code=o["code"],
                        reason_code="cancel_outside_policy", description=cancel_reason, amount=0,
                        payload=json.dumps({"hours_before_slot": round(hours, 1)}), status="completed",
                        requires_approval=1, approval_rules=json.dumps(["APR-03"]),
                        resolution_note="Trưởng ca duyệt huỷ; hoa đã chuẩn bị nên không hoàn tiền.", created_by="agent",
                        created_at=iso(cancelled_at - timedelta(minutes=20)), decided_at=iso(cancelled_at),
                        decided_by=SHIFT_LEAD)
            amount = 0
        if amount and paid_amount:
            needs = amount > THRESHOLD
            decided = cancelled_at + (timedelta(hours=3) if needs else timedelta(0))
            done = cancelled_at + timedelta(days=2)
            completed = done <= NOW
            new_request(code="YC10001" if o["code"] == "MM10007" else None, type="refund", customer_id=o["customer_id"],
                        ref_type="order", ref_code=o["code"], reason_code="cancelled_order",
                        description=f"Hoàn tiền do huỷ đơn: {cancel_reason}", amount=amount,
                        payload=json.dumps({"refund_method": "original_payment", "refund_percent": pct,
                                            "hours_before_slot": round(hours, 1)}, ensure_ascii=False),
                        status="completed" if completed else "approved", requires_approval=1 if needs else 0,
                        approval_rules=json.dumps(["APR-01"]) if needs else None,
                        resolution_note="Đã chuyển hoàn tiền." if completed else None, created_by="agent",
                        created_at=iso(cancelled_at), decided_at=iso(decided), decided_by=MANAGER if needs else "system")
            if completed:
                refunded_amount = amount
                payment_status = "refunded" if amount >= paid_amount else "partially_refunded"
            else:
                payment_status = "refund_pending"

    if final == "refunded":
        reason = rng.choice(["damaged", "wrong_item", "wilted_early"])
        req_at = min(delivered_at + timedelta(hours=rng.uniform(1, 20)), NOW - timedelta(hours=3))
        needs = total > THRESHOLD
        new_request(type="refund", customer_id=o["customer_id"], ref_type="order", ref_code=o["code"],
                    reason_code=reason, description={"damaged": "Hoa bị dập nhiều khi nhận.",
                                                     "wrong_item": "Giao sai mẫu so với đơn.",
                                                     "wilted_early": "Hoa héo sau 1 ngày dù đã thay nước."}[reason],
                    amount=total, payload=json.dumps({"refund_method": "original_payment",
                                                      "evidence_urls": [f"https://zalo.example/img/{o['code'].lower()}-1.jpg"]}),
                    status="completed", requires_approval=1 if needs else 0,
                    approval_rules=json.dumps(["APR-01"]) if needs else None, resolution_note="Đã hoàn 100% sau khi xác minh ảnh.",
                    created_by="agent", created_at=iso(req_at), decided_at=iso(req_at + timedelta(hours=2)),
                    decided_by=MANAGER if needs else "system")
        refunded_amount = total
        payment_status = "refunded"
        ev(o["code"], "status_changed", req_at + timedelta(hours=2), "delivered", "refunded", "Hoàn tiền 100%.", actor="staff")

    if final == "delivered" and delivered_at and not o["express"] and not o["scenario"]:
        late = (delivered_at - end).total_seconds() / 60
        if late > 60 and rng.random() < 0.7:
            req_at = delivered_at + timedelta(minutes=40)
            if ship + express_fee > 0:
                new_request(type="refund", customer_id=o["customer_id"], ref_type="order", ref_code=o["code"],
                            reason_code="late_delivery", description=f"Giao trễ {late:.0f} phút.", amount=ship + express_fee,
                            payload=json.dumps({"refund_method": "original_payment"}), status="completed",
                            resolution_note="Hoàn phí ship theo REF-04.", created_by="agent", created_at=iso(req_at),
                            decided_at=iso(req_at), decided_by="system")
                refunded_amount = ship + express_fee
                payment_status = "partially_refunded"
            gw = new_goodwill(o["customer_id"], req_at)
            new_request(type="discount", customer_id=o["customer_id"], ref_type="order", ref_code=o["code"],
                        reason_code="late_delivery", description=f"Xin lỗi vì giao trễ {late:.0f} phút.", amount=10,
                        payload=json.dumps({"percent": 10}), status="completed", issued_code=gw, created_by="agent",
                        created_at=iso(req_at), decided_at=iso(req_at), decided_by="system")
        elif 30 < late <= 60 and rng.random() < 0.5:
            req_at = delivered_at + timedelta(minutes=30)
            gw = new_goodwill(o["customer_id"], req_at)
            new_request(type="discount", customer_id=o["customer_id"], ref_type="order", ref_code=o["code"],
                        reason_code="late_delivery", description=f"Xin lỗi vì giao trễ {late:.0f} phút.", amount=10,
                        payload=json.dumps({"percent": 10}), status="completed", issued_code=gw, created_by="agent",
                        created_at=iso(req_at), decided_at=iso(req_at), decided_by="system")

    if final != "cancelled":
        prior_orders[o["customer_id"]] += 1

    order_rows.append(dict(
        code=o["code"], customer_id=o["customer_id"], branch_id=branch, channel=o["channel"], occasion=o["occasion"],
        status=final, fulfillment="pickup" if o["pickup_branch"] else "delivery",
        delivery_date=(o["created"].date() if o["express"] else o["d"]).isoformat(), slot_code=o["slot"],
        is_express=1 if o["express"] else 0, express_deadline=iso(end) if o["express"] else None,
        zone_id=o["zone"], recipient_name=o["recipient"][0] if o["recipient"] else cust["full_name"],
        recipient_phone=o["recipient"][1] if o["recipient"] else cust["phone"],
        delivery_address=o["recipient"][2] if o["recipient"] else None, card_message=o["card"],
        is_surprise=1 if o["surprise"] else 0, subtotal=subtotal, shipping_fee=ship, express_fee=express_fee,
        discount_code=code_try if source == "code" else None, discount_source=source, discount_amount=discount,
        total=total, payment_method=pm, payment_status=payment_status, paid_amount=paid_amount,
        refunded_amount=refunded_amount, reschedule_count=0,
        delivered_at=iso(delivered_at) if delivered_at and final in ("delivered", "refunded") else None,
        cancel_reason=cancel_reason if final == "cancelled" else None, note=note, created_at=iso(created),
        updated_at=iso(max([t for t in (created, paid_at, delivered_at, failed_at, cancelled_at) if t and t <= NOW])),
    ))
    for l in lines:
        item_rows.append(dict(order_code=o["code"], sku=l["sku"], product_name=l["product_name"], quantity=l["quantity"],
                              unit_price=l["unit_price"], line_total=l["line_total"]))

ORDER_BY_CODE = {r["code"]: r for r in order_rows}

# --- yêu cầu kịch bản cố định (mã xin lỗi của KH0003)
gw1 = new_goodwill("KH0003", P("2026-09-02T19:30:00+07:00"), fixed="XL7K2M9Q")
new_request(code="YC10002", type="discount", customer_id="KH0003", ref_type="order", ref_code="MM10013",
            reason_code="late_delivery", description="Xin lỗi vì giao trễ 50 phút dịp lễ 2/9.", amount=10,
            payload=json.dumps({"percent": 10}), status="completed", issued_code=gw1, created_by="agent",
            created_at="2026-09-02T19:30:00+07:00", decided_at="2026-09-02T19:30:00+07:00", decided_by="system")
gw2 = new_goodwill("KH0003", P("2026-10-04T16:10:00+07:00"), fixed="XLQ8D3TR")
new_request(code="YC10003", type="discount", customer_id="KH0003", ref_type="order", ref_code="MM10014",
            reason_code="quality_issue", description="2 bông cát tường bị dập khi nhận.", amount=10,
            payload=json.dumps({"percent": 10}), status="completed", issued_code=gw2, created_by="agent",
            created_at="2026-10-04T16:10:00+07:00", decided_at="2026-10-04T16:10:00+07:00", decided_by="system")

# --- đổi trả, khiếu nại, chờ duyệt (ngẫu nhiên, gắn với đơn đã giao)
delivered_random = [r for r in order_rows if r["status"] == "delivered" and r["code"] >= "MM10015"]
fresh_delivered = [r for r in delivered_random
                   if P(r["delivered_at"]) <= NOW - timedelta(days=2)
                   and all(PRODUCTS[i["sku"]]["category"] not in ("phu_kien", "hoa_say_kho")
                           for i in item_rows if i["order_code"] == r["code"])]
for r in rng.sample(fresh_delivered, 5):
    t = P(r["delivered_at"]) + timedelta(hours=rng.uniform(26, 44))
    new_request(type="exchange", customer_id=r["customer_id"], ref_type="order", ref_code=r["code"],
                reason_code="wilted_early", description="Hoa héo rũ sau gần 2 ngày dù đã thay nước, cắt gốc.",
                amount=r["subtotal"], payload=json.dumps({"resolution": "redeliver_same",
                                                          "evidence_urls": [f"https://zalo.example/img/{r['code'].lower()}.jpg"]}),
                status="completed", resolution_note="Đã giao bó mới tương đương (EXC-04).", created_by="agent",
                created_at=iso(t), decided_at=iso(t), decided_by="system")
for r in rng.sample([x for x in fresh_delivered if x["code"] not in {q["ref_code"] for q in request_rows}], 2):
    t = P(r["delivered_at"]) + timedelta(hours=rng.uniform(3, 30))
    new_request(type="exchange", customer_id=r["customer_id"], ref_type="order", ref_code=r["code"],
                reason_code="change_of_mind", description="Người nhận không thích màu hoa, muốn đổi màu khác.",
                amount=r["subtotal"], payload=json.dumps({"resolution": "replace_other"}), status="rejected",
                resolution_note="Hoa tươi đã nhận đúng mẫu không đổi vì không thích (EXC-03).", created_by="agent",
                created_at=iso(t), decided_at=iso(t), decided_by="system")
recent = sorted([r for r in delivered_random if r["total"] > THRESHOLD
                 and r["code"] not in {q["ref_code"] for q in request_rows}],
                key=lambda r: r["delivered_at"], reverse=True)
if recent:
    r = recent[0]
    t = P(r["delivered_at"]) + timedelta(hours=3)
    new_request(type="refund", customer_id=r["customer_id"], ref_type="order", ref_code=r["code"], reason_code="damaged",
                description="Giỏ hoa bị đổ khi giao, nhiều bông gãy cành.", amount=r["total"],
                payload=json.dumps({"refund_method": "original_payment",
                                    "evidence_urls": [f"https://zalo.example/img/{r['code'].lower()}-a.jpg"]}),
                status="pending_approval", requires_approval=1, approval_rules=json.dumps(["APR-01"]),
                created_by="agent", created_at=iso(t))
    ORDER_BY_CODE[r["code"]]["payment_status"] = "refund_pending"
late_customers = [q for q in request_rows if q["type"] == "discount" and q["customer_id"] not in SCENARIO_CUSTOMERS]
if late_customers:
    q = late_customers[0]
    new_request(type="discount", customer_id=q["customer_id"], ref_type="order", ref_code=q["ref_code"],
                reason_code="service_recovery", description="Khách phàn nàn lần 2, đề xuất giảm 15% cho đơn kế tiếp.",
                amount=15, payload=json.dumps({"percent": 15}), status="pending_approval", requires_approval=1,
                approval_rules=json.dumps(["APR-02"]), created_by="agent", created_at=iso(NOW - timedelta(hours=14)))
some = rng.sample(delivered_random, 3)
new_request(type="escalation", customer_id=some[0]["customer_id"], ref_type="order", ref_code=some[0]["code"],
            reason_code="complaint", description="Khách phản ánh thiệp in sai tên người nhận, muốn quản lý gọi lại.",
            status="open", requires_approval=1, approval_rules=json.dumps(["APR-11"]), created_by="agent",
            created_at=iso(NOW - timedelta(hours=16)))
new_request(type="escalation", customer_id=some[1]["customer_id"], ref_type=None, ref_code=None,
            reason_code="outside_zone", description="Khách hỏi giao 2 kệ khai trương về Vị Thanh ngày 25/10.",
            status="closed", requires_approval=1, approval_rules=json.dumps(["APR-06"]),
            resolution_note="Đã báo giá ship 350.000đ/kệ, khách đồng ý đặt qua hotline.", created_by="agent",
            created_at="2026-10-12T09:15:00+07:00", decided_at="2026-10-12T10:40:00+07:00", decided_by=SHIFT_LEAD)
new_request(type="escalation", customer_id=some[2]["customer_id"], ref_type=None, ref_code=None,
            reason_code="data_privacy", description="Khách yêu cầu xoá số điện thoại khỏi danh sách nhận tin khuyến mãi.",
            status="open", requires_approval=1, approval_rules=json.dumps(["APR-12"]), created_by="agent",
            created_at=iso(NOW - timedelta(days=1, hours=3)))

# =============================================================== tư vấn sự kiện
PACKAGES = defaultdict(list)
for pkg in M.EVENT_PACKAGES:
    PACKAGES[pkg["event_type"]].append((pkg["name"], pkg["price"]))
VENUES = {
    "wedding": ["Trung tâm hội nghị tiệc cưới ven sông Hậu, phường Cái Khế", "Nhà hàng tiệc cưới tại phường Cái Răng",
                "Tư gia tại xã Phong Điền", "Tư gia tại phường Bình Thủy", "Khách sạn tại phường Ninh Kiều"],
    "opening": ["Cửa hàng mới trên đường 3 Tháng 2", "Showroom tại phường Hưng Phú", "Quán cà phê tại phường Tân An"],
    "conference": ["Hội trường khách sạn tại phường Ninh Kiều", "Trung tâm hội nghị tại phường Cái Khế"],
    "party": ["Nhà hàng tại phường An Bình", "Tư gia tại phường Ninh Kiều", "Sân vườn tại xã Mỹ Khánh"],
}
consult_rows = []
consult_load = Counter()


def consult(code, cid, etype, mode, appt_date, appt_time, event_date, status, *, venue, guests, budget,
            package=None, created, note=None, cancel_reason=None, consultant=None, zone=None):
    key = (appt_date, appt_time)
    consultant = consultant or CONSULTANTS[consult_load[key] % 2]
    consult_load[key] += 1
    contract = deposit = None
    deposit_status = "none"
    if package:
        contract = dict(sum(PACKAGES.values(), []))[package]
        deposit = round_down(contract * POLICY["consultation"]["contract"]["deposit_percent"] / 100)
        deposit_status = "paid"
    consult_rows.append(dict(code=code, customer_id=cid, event_type=etype, mode=mode, appointment_date=appt_date,
                             appointment_time=appt_time, event_date=event_date, venue=venue,
                             zone_id=zone, guest_count=guests, budget_range=budget, status=status,
                             consultant=consultant, onsite_fee=POLICY["consultation"]["onsite_fee_vnd"] if mode == "onsite" else 0,
                             package_name=package, contract_value=contract, deposit_amount=deposit or 0,
                             deposit_status=deposit_status, reschedule_count=0, event_date_change_count=0, note=note,
                             cancel_reason=cancel_reason, created_at=created, updated_at=created))


consult("TV2001", "KH0005", "wedding", "studio", "2026-09-20", "09:00", "2026-12-12", "contracted",
        venue="Trung tâm hội nghị tiệc cưới ven sông Hậu, phường Cái Khế", guests=400, budget="15–20 triệu",
        package="Gói Miên", created="2026-09-15T20:10:00+07:00", note="Tông trắng – xanh lá, cổng hoa tươi 70%.")
consult("TV2002", "KH0007", "wedding", "online", "2026-09-27", "14:00", "2026-10-28", "contracted",
        venue="Nhà hàng tiệc cưới tại phường Cái Răng", guests=250, budget="dưới 10 triệu", package="Gói Mộc",
        created="2026-09-24T09:30:00+07:00", note="Tông hồng pastel.")
consult("TV2003", "KH0004", "opening", "studio", "2026-10-18", "09:00", "2026-11-01", "scheduled",
        venue="Lô 7 Khu đô thị Nam Cần Thơ, phường Hưng Phú", guests=120, budget="5–10 triệu",
        created="2026-10-12T15:20:00+07:00", note="Khai trương văn phòng mới, cần cổng hoa + kệ hoa.")
consult("TV2004", "KH0008", "party", "online", "2026-10-16", "14:00", "2026-10-31", "scheduled",
        venue="Tư gia tại phường Ô Môn", guests=30, budget="3–5 triệu", created="2026-10-12T21:05:00+07:00",
        note="Kỷ niệm 10 năm ngày cưới, muốn bất ngờ cho vợ.")
consult("TV2005", "KH0001", "conference", "studio", "2026-10-03", "10:30", "2026-11-05", "contracted",
        venue="Hội trường khách sạn tại phường Ninh Kiều", guests=150, budget="5–10 triệu",
        package="Gói Hội Nghị Tiêu Chuẩn", created="2026-09-28T11:00:00+07:00", note="Hội nghị khách hàng thường niên.")

open_days = [date(2026, 7, 1) + timedelta(days=i) for i in range(0, 138)]
open_days = [d for d in open_days if d.weekday() != 0]
day_weights = [3.0 if d > TODAY else 1.0 for d in open_days]
for n in range(2006, 2031):
    for _ in range(50):
        etype = weighted([("wedding", 50), ("opening", 20), ("conference", 15), ("party", 15)])
        mode = weighted([("studio", 60), ("online", 30), ("onsite", 10)])
        d = rng.choices(open_days, weights=day_weights, k=1)[0]
        t = rng.choice(POLICY["consultation"]["onsite_slots" if mode == "onsite" else "slots"])
        if consult_load[(d.isoformat(), t)] >= 2:
            continue
        start = at(d, t)
        created = start - timedelta(hours=rng.uniform(26, 240))
        if created > NOW:
            continue
        break
    else:
        raise RuntimeError("Không sinh được lịch tư vấn hợp lệ")
    cid = rng.choice(BUSINESS_RANDOM if etype in ("opening", "conference") and rng.random() < 0.5 else RANDOM_CUSTOMERS)
    gap = rng.randint(20, 150) if etype == "wedding" else rng.randint(8, 45)
    event = d + timedelta(days=gap)
    if start < NOW:
        status = weighted([("contracted", 35), ("completed", 35), ("no_show", 10), ("cancelled", 20)])
    else:
        status = weighted([("scheduled", 85), ("cancelled", 15)])
    package = rng.choice(PACKAGES[etype])[0] if status == "contracted" else None
    zone = rng.choice(["Z1", "Z2", "Z3"]) if mode == "onsite" else None
    consult(f"TV{n}", cid, etype, mode, d.isoformat(), t, event.isoformat(), status,
            venue=rng.choice(VENUES[etype]), guests=rng.choice([30, 50, 80, 120, 200, 300, 450]),
            budget=rng.choice(["dưới 10 triệu", "10–15 triệu", "15–20 triệu", "20–30 triệu", "3–5 triệu", "5–10 triệu"]),
            package=package, created=iso(created), zone=zone,
            cancel_reason=rng.choice(["Khách đã chọn được đơn vị khác.", "Sự kiện bị hoãn.", "Khách bận đột xuất."])
            if status == "cancelled" else None)

# =============================================================== gói định kỳ
sub_rows = []


def delivered_upto(dates: list[date], slot: str) -> int:
    return sum(1 for d in dates if at(d, SLOTS[slot]["end_time"]) <= NOW)


def subscription(code, cid, plan_id, term, start, weekday, slot, zone, address, *, status=None, pause=None,
                 recipient=None, created=None, note=None, cancel_at=None):
    plan = PLANS[plan_id]
    total = plan["deliveries_per_month"] * term
    pct = POLICY["subscription"]["term_discount_percent"][str(term)]
    price = round_down(plan["price_per_delivery"] * total * (100 - pct) / 100)
    sched = delivery_schedule(plan["frequency"], start, weekday, total)
    delivered = delivered_upto(sched, slot)
    if cancel_at:
        delivered = sum(1 for d in sched if at(d, SLOTS[slot]["end_time"]) <= cancel_at)
        if delivered >= total:
            status, cancel_at = None, None
            delivered = delivered_upto(sched, slot)
    paused_until, pause_count = None, 0
    if pause:
        pause_from, paused_until = pause
        delivered = sum(1 for d in sched if d < pause_from and at(d, SLOTS[slot]["end_time"]) <= NOW)
        rest = delivery_schedule(plan["frequency"], paused_until, weekday, total - delivered)
        sched = sched[:delivered] + rest
        pause_count = 1
    if status is None:
        status = "expired" if delivered >= total else ("active" if start <= TODAY or rng.random() < 0.7 else "pending_payment")
    if status == "expired":
        delivered = total
    nxt = None
    if status in ("active", "paused", "pending_payment"):
        nxt = sched[delivered].isoformat() if delivered < total else None
    created = created or iso(min(at(start - timedelta(days=rng.randint(2, 6)), "10:00"), NOW - timedelta(hours=2)))
    sub_rows.append(dict(code=code, customer_id=cid, plan_id=plan_id, term_months=term, total_deliveries=total,
                         delivered_count=delivered, price_total=price,
                         paid_amount=0 if status == "pending_payment" else price, start_date=sched[0].isoformat(),
                         end_date=sched[-1].isoformat(), delivery_weekday=weekday, slot_code=slot, zone_id=zone,
                         delivery_address=address, recipient_name=(recipient or customers[cid]["full_name"]),
                         recipient_phone=customers[cid]["phone"], next_delivery_date=nxt, status=status,
                         paused_until=paused_until.isoformat() if paused_until else None, pause_count=pause_count,
                         note=note, created_at=created, updated_at=iso(cancel_at) if cancel_at else created))
    return sub_rows[-1]


subscription("GD3001", "KH0004", "SUB-OFFICE-W", 3, date(2026, 9, 7), 0, "K1", "Z2",
             "Lô 18 KCN Trà Nóc 1, phường Bình Thủy, TP. Cần Thơ", status="active", recipient="Lễ tân Gạo Sạch Tây Đô",
             created="2026-09-03T10:00:00+07:00", note="Đặt bình ở sảnh lễ tân tầng trệt.")
subscription("GD3002", "KH0001", "SUB-ALTAR", 6, date(2026, 8, 12), None, "K1", "Z1",
             "12 Hòa Bình, phường Ninh Kiều, TP. Cần Thơ", status="active", created="2026-08-08T19:00:00+07:00")
subscription("GD3003", "KH0003", "SUB-HOME-W", 1, date(2026, 10, 1), 3, "K5", "Z2",
             "23 Lê Hồng Phong, phường Bình Thủy, TP. Cần Thơ", status="paused",
             pause=(date(2026, 10, 16), date(2026, 10, 30)), created="2026-09-28T08:30:00+07:00",
             note="Khách đi công tác Hà Nội đến 29/10.")
subscription("GD3004", "KH0006", "SUB-HOME-2W", 3, date(2026, 10, 3), 5, "K2", "Z1",
             "141 Đường 30 Tháng 4, phường Tân An, TP. Cần Thơ", status="active", created="2026-09-29T22:00:00+07:00")

home_customers = [c for c in RANDOM_CUSTOMERS if customers[c]["zone"] in ("Z1", "Z2", "Z3") and c not in BUSINESS_RANDOM]
for n in range(3005, 3021):
    biz = n % 5 == 0
    cid = rng.choice(BUSINESS_RANDOM) if biz else rng.choice(home_customers)
    plan_id = "SUB-OFFICE-W" if biz else weighted([("SUB-HOME-W", 40), ("SUB-HOME-2W", 25), ("SUB-ALTAR", 35)])
    term = weighted([(1, 40), (3, 40), (6, 20)])
    start = date(2026, 6, 1) + timedelta(days=rng.randint(0, 140))
    weekday = None if plan_id == "SUB-ALTAR" else rng.randint(0, 6)
    zone = customers[cid]["zone"]
    slot = rng.choice([s for s in ZONES[zone]["allowed_slots"].split(",") if s != "K6"])
    status, cancel_at = None, None
    if rng.random() < 0.25 and start < TODAY - timedelta(days=10):
        status = "cancelled"
        cancel_at = at(start + timedelta(days=rng.randint(3, (TODAY - start).days - 2)), "15:00")
    row = subscription(f"GD{n}", cid, plan_id, term, start, weekday, slot, zone, customers[cid]["address"],
                       status=status, cancel_at=cancel_at)
    if row["status"] == "cancelled":
        row["next_delivery_date"] = None
        remaining = row["total_deliveries"] - row["delivered_count"]
        if remaining > 0:
            unused = round_down(row["price_total"] / row["total_deliveries"] * remaining)
            refund = unused - round_down(unused * 0.1)
            t = cancel_at
            row["note"] = "Huỷ: khách chuyển nhà."
            new_request(type="refund", customer_id=cid, ref_type="subscription", ref_code=row["code"],
                        reason_code="subscription_cancelled", description="Hoàn tiền các lần giao chưa dùng (SUB-03).",
                        amount=refund, payload=json.dumps({"refund_method": "bank_transfer"}), status="completed",
                        requires_approval=1 if refund > THRESHOLD else 0,
                        approval_rules=json.dumps(["APR-13"]) if refund > THRESHOLD else None,
                        resolution_note="Đã chuyển khoản hoàn tiền.", created_by="agent", created_at=iso(t),
                        decided_at=iso(t + timedelta(hours=5)), decided_by=MANAGER if refund > THRESHOLD else "system")

# =============================================================== chốt khách hàng
spent = Counter()
for r in order_rows:
    if r["status"] in ("delivered",) and r["created_at"] >= "2025-10-16":
        spent[r["customer_id"]] += r["total"] - r["refunded_amount"]
TIER_MIN = {"loyal": 3000000, "vip": 10000000}
first_order: dict[str, str] = {}
for r in order_rows + consult_rows + sub_rows:
    if r["customer_id"] not in first_order or r["created_at"] < first_order[r["customer_id"]]:
        first_order[r["customer_id"]] = r["created_at"]
for cid, c in customers.items():
    if not c["fixed"]:
        base = {"member": rng.randint(0, 18) * 100000, "loyal": rng.randint(30, 85) * 100000,
                "vip": rng.randint(100, 220) * 100000}[c["tier_target"]]
        total = base + spent[cid]
        c["total_spent_12m"] = total
        c["tier"] = "vip" if total >= TIER_MIN["vip"] else ("loyal" if total >= TIER_MIN["loyal"] else "member")
    c["points"] = max(c["total_spent_12m"] // 10000 - rng.randint(0, 3) * 100, 0)
    if cid in first_order and first_order[cid] < c["created_at"]:
        c["created_at"] = iso(P(first_order[cid]) - timedelta(minutes=5))

# =============================================================== ghi SQL
def q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def inserts(table: str, rows: list[dict], cols: list[str]) -> list[str]:
    out = [f"-- {table}: {len(rows)} dòng"]
    for i in range(0, len(rows), 40):
        chunk = rows[i:i + 40]
        values = ",\n".join("  (" + ", ".join(q(r[c]) for c in cols) + ")" for r in chunk)
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values};")
    return out


updated = iso(NOW - timedelta(hours=1))
product_rows = [dict(sku=p["sku"], name=p["name"], category=p["category"], description=p["desc"] or None,
                     main_flowers=p["flowers"] or None, color_tone=p["tone"] or None, size=p["size"] or None,
                     unit=p["unit"], price=p["price"], lead_time_hours=p["lead"], freshness_days=p["fresh"],
                     is_seasonal=p.get("seasonal", 0), season_note=p.get("season_note"), is_active=1)
                for p in M.PRODUCTS]
inventory_rows = [dict(sku=p["sku"], branch_id=b, quantity=p["stock"][i], updated_at=updated)
                  for p in M.PRODUCTS for i, b in enumerate(("CN01", "CN02"))]
code_rows = [dict(c, customer_id=None, created_by="system", created_at="2026-01-01T00:00:00+07:00")
             for c in CODES.values()] + goodwill_codes
plan_rows = [dict(id=p["id"], name=p["name"], description=p["description"], frequency=p["frequency"],
                  deliveries_per_month=p["deliveries_per_month"], price_per_delivery=p["price_per_delivery"],
                  retail_equivalent=p["retail_equivalent"]) for p in M.SUBSCRIPTION_PLANS]
request_rows.sort(key=lambda r: r["code"])
event_rows.sort(key=lambda e: (e["created_at"], e["order_code"]))

sql = [
    "-- =============================================================================",
    "-- Mộc Miên Florist — dữ liệu tổng hợp (sinh bởi tools/generate_seed.py, KHÔNG sửa tay)",
    f"-- Mốc thời gian dữ liệu: {M.ANCHOR_NOW}",
    "-- =============================================================================",
    "PRAGMA foreign_keys = ON;",
    "BEGIN TRANSACTION;",
]
sql += inserts("branches", M.BRANCHES, ["id", "name", "address", "phone", "open_time", "close_time", "has_studio", "slot_capacity"])
sql += inserts("delivery_slots", M.SLOTS, ["code", "start_time", "end_time"])
sql += inserts("delivery_zones", M.ZONES, ["id", "name", "areas", "fee", "free_ship_min_order", "allowed_slots",
                                           "express_available", "min_days_ahead", "default_branch_id"])
sql += inserts("products", product_rows, list(product_rows[0]))
sql += inserts("inventory", inventory_rows, ["sku", "branch_id", "quantity", "updated_at"])
cust_cols = ["id", "full_name", "phone", "email", "gender", "birthday", "address", "customer_type", "company_name",
             "tier", "points", "total_spent_12m", "created_at", "note"]
sql += inserts("customers", sorted(customers.values(), key=lambda c: c["id"]), cust_cols)
sql += inserts("discount_codes", code_rows, ["code", "description", "discount_type", "value", "max_discount", "min_order",
                                             "applicable_categories", "valid_from", "valid_to", "usage_limit", "used_count",
                                             "per_customer_limit", "customer_id", "kind", "is_active", "created_by",
                                             "created_at"])
order_rows.sort(key=lambda r: r["code"])
sql += inserts("orders", order_rows, list(order_rows[0]))
sql += inserts("order_items", item_rows, list(item_rows[0]))
sql += inserts("order_events", event_rows, list(event_rows[0]))
consult_rows.sort(key=lambda r: r["code"])
sql += inserts("consultations", consult_rows, list(consult_rows[0]))
sql += inserts("subscription_plans", plan_rows, list(plan_rows[0]))
sql += inserts("subscriptions", sub_rows, list(sub_rows[0]))
sql += inserts("service_requests", request_rows, list(request_rows[0]))
sql.append("COMMIT;")

out = ROOT / "api" / "sql" / "seed.sql"
out.write_text("\n".join(sql) + "\n", encoding="utf-8")

print(f"Đã ghi {out.relative_to(ROOT)}")
print(f"  khách hàng: {len(customers)} | đơn: {len(order_rows)} | dòng sản phẩm: {len(item_rows)} | sự kiện đơn: {len(event_rows)}")
print(f"  tư vấn: {len(consult_rows)} | gói định kỳ: {len(sub_rows)} | yêu cầu: {len(request_rows)} | mã giảm giá: {len(code_rows)}")
print("  trạng thái đơn:", dict(Counter(r["status"] for r in order_rows)))
print("  trạng thái tư vấn:", dict(Counter(r["status"] for r in consult_rows)))
print("  trạng thái gói:", dict(Counter(r["status"] for r in sub_rows)))
print("  loại/trạng thái yêu cầu:", dict(Counter((r["type"], r["status"]) for r in request_rows)))
print("  hạng khách:", dict(Counter(c["tier"] for c in customers.values())))
