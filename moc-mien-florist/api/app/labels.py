"""Nhãn tiếng Việt cho các mã trạng thái — agent dùng để trả lời khách."""

ORDER_STATUS = {
    "pending": "Chờ xác nhận / chờ thanh toán",
    "confirmed": "Đã xác nhận",
    "arranging": "Đang cắm hoa",
    "delivering": "Đang giao",
    "delivered": "Đã giao",
    "failed_delivery": "Giao không thành công",
    "cancelled": "Đã huỷ",
    "refunded": "Đã hoàn tiền",
}

PAYMENT_STATUS = {
    "unpaid": "Chưa thanh toán",
    "partially_paid": "Đã thanh toán một phần",
    "paid": "Đã thanh toán",
    "refund_pending": "Đang xử lý hoàn tiền",
    "partially_refunded": "Đã hoàn một phần",
    "refunded": "Đã hoàn tiền",
}

PAYMENT_METHOD = {
    "cod": "Thanh toán khi nhận hàng (COD)",
    "bank_transfer": "Chuyển khoản ngân hàng",
    "momo": "Ví MoMo",
    "vnpay": "VNPay QR",
    "card": "Quẹt thẻ tại cửa hàng",
    "cash": "Tiền mặt tại cửa hàng",
}

FULFILLMENT = {"delivery": "Giao tận nơi", "pickup": "Nhận tại cửa hàng"}

REQUEST_TYPE = {
    "refund": "Hoàn tiền",
    "exchange": "Đổi trả",
    "discount": "Mã giảm giá",
    "cancellation": "Huỷ",
    "reschedule": "Đổi lịch",
    "escalation": "Chuyển nhân viên",
}

REQUEST_STATUS = {
    "pending_approval": "Chờ duyệt",
    "approved": "Đã duyệt",
    "rejected": "Từ chối",
    "completed": "Hoàn tất",
    "open": "Đang xử lý",
    "closed": "Đã đóng",
}

CONSULT_STATUS = {
    "scheduled": "Đã đặt lịch",
    "completed": "Đã tư vấn",
    "contracted": "Đã ký hợp đồng",
    "cancelled": "Đã huỷ",
    "no_show": "Khách không đến",
}

EVENT_TYPE = {
    "wedding": "Hoa cưới",
    "opening": "Khai trương",
    "conference": "Hội nghị / sự kiện công ty",
    "party": "Tiệc sinh nhật / kỷ niệm",
}

CONSULT_MODE = {
    "studio": "Tại studio Mộc Miên Ninh Kiều (tầng 2)",
    "online": "Gọi video Zalo / Google Meet",
    "onsite": "Khảo sát tận nơi",
}

DEPOSIT_STATUS = {
    "none": "Chưa đặt cọc",
    "paid": "Đã đặt cọc",
    "refund_pending": "Đang xử lý hoàn cọc",
    "refunded": "Đã hoàn cọc",
    "partially_refunded": "Đã hoàn một phần cọc",
    "forfeited": "Không hoàn cọc",
}

SUB_STATUS = {
    "pending_payment": "Chờ thanh toán",
    "active": "Đang hoạt động",
    "paused": "Tạm ngưng",
    "cancelled": "Đã huỷ",
    "expired": "Đã hết hạn",
}

SUB_FREQUENCY = {
    "weekly": "Mỗi tuần",
    "biweekly": "2 tuần/lần",
    "lunar_1_15": "Trước mùng 1 và rằm âm lịch",
}

CATEGORY = {
    "bo_hoa": "Bó hoa",
    "gio_hop_hoa": "Giỏ & hộp hoa",
    "binh_hoa": "Bình hoa",
    "ke_khai_truong": "Kệ hoa khai trương",
    "hoa_chia_buon": "Hoa chia buồn",
    "hoa_cuoi": "Hoa cưới",
    "lan_chau": "Lan hồ điệp chậu",
    "hoa_le": "Hoa lẻ theo cành",
    "hoa_say_kho": "Hoa sáp & hoa khô",
    "phu_kien": "Phụ kiện & quà tặng",
}

BANK_TRANSFER_INFO = {
    "bank": "Ngân hàng TMCP Á Châu (ACB) – CN Cần Thơ",
    "account_number": "2923 868 186",
    "account_name": "CONG TY TNHH MOC MIEN FLORIST",
    "transfer_note_format": "<mã đơn> <4 số cuối SĐT>",
}
