"""Model dữ liệu đầu vào (Pydantic v2). Mô tả field bằng tiếng Việt để hiện trên /docs."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Actor = Literal["agent", "staff", "customer"]


class CustomerIn(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=80, description="Họ tên người đặt")
    phone: str = Field(..., description="SĐT người đặt, dùng để xác minh khi tra cứu")
    email: str | None = Field(None, max_length=120)


class ItemIn(BaseModel):
    sku: str = Field(..., description="Mã sản phẩm, vd BH02")
    quantity: int = Field(1, ge=1, le=200)


class RecipientIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    phone: str
    address: str = Field(..., min_length=5, max_length=255)
    zone_id: str = Field(..., description="Z1–Z4 (xem GET /delivery/zones). Ngoài vùng: chuyển nhân viên (APR-06)")


class OrderIn(BaseModel):
    customer: CustomerIn
    items: list[ItemIn] = Field(..., min_length=1, max_length=10)
    fulfillment: Literal["delivery", "pickup"] = "delivery"
    branch_id: str | None = Field(None, description="Bắt buộc khi nhận tại cửa hàng (CN01/CN02)")
    delivery_date: date | None = Field(None, description="Ngày giao/nhận (YYYY-MM-DD); bỏ trống nếu giao hỏa tốc")
    slot_code: str | None = Field(None, description="K1..K6; bỏ trống nếu giao hỏa tốc")
    express: bool = Field(False, description="Giao hỏa tốc 2 giờ (ORD-03)")
    recipient: RecipientIn | None = None
    card_message: str | None = Field(None, max_length=300)
    is_surprise: bool = Field(False, description="Giao bất ngờ: không gọi báo trước cho người nhận")
    occasion: str | None = Field(None, max_length=40, description="sinh_nhat, ky_niem, phu_nu_20_10, khai_truong, chia_buon...")
    discount_code: str | None = None
    payment_method: Literal["cod", "bank_transfer", "momo", "vnpay", "card", "cash"] = "bank_transfer"
    note: str | None = Field(None, max_length=300)
    channel: Literal["website", "zalo", "hotline", "facebook", "store", "agent"] = "agent"


class PhoneIn(BaseModel):
    phone: str = Field(..., description="SĐT người đặt để xác minh")
    actor: Actor = "agent"


class OrderRescheduleIn(PhoneIn):
    new_date: date
    new_slot_code: str
    reason: str | None = Field(None, max_length=300)


class CancelIn(PhoneIn):
    reason: str | None = Field(None, max_length=300)
    dry_run: bool = Field(False, description="true = chỉ xem trước mức hoàn tiền, không huỷ")


RefundReason = Literal["late_delivery", "damaged", "wrong_item", "missing_item", "wilted_early",
                       "failed_delivery_shop_fault", "other"]


class RefundIn(PhoneIn):
    order_code: str
    reason_code: RefundReason
    amount: int | None = Field(None, gt=0, description="Bỏ trống để hệ thống đề xuất theo chính sách")
    refund_method: Literal["original_payment", "bank_transfer", "store_credit"] = "original_payment"
    description: str | None = Field(None, max_length=1000)
    evidence_urls: list[str] = Field(default_factory=list, description="Link ảnh/video khách gửi")


class ExchangeIn(PhoneIn):
    order_code: str
    reason_code: Literal["wilted_early", "damaged", "wrong_item", "missing_item", "accessory_defect", "change_of_mind"]
    items: list[ItemIn] | None = Field(None, description="Bỏ trống = toàn bộ đơn")
    resolution: Literal["redeliver_same", "replace_other", "refund", "store_credit"] = "redeliver_same"
    description: str | None = Field(None, max_length=1000)
    evidence_urls: list[str] = Field(default_factory=list)


class DiscountRequestIn(PhoneIn):
    order_code: str | None = None
    reason_code: Literal["late_delivery", "quality_issue", "service_recovery", "loyal_customer", "other"]
    percent: int | None = Field(None, ge=1, le=100)
    amount: int | None = Field(None, gt=0)
    description: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def _one_of(self):
        if (self.percent is None) == (self.amount is None):
            raise ValueError("Cần đúng một trong hai: percent hoặc amount")
        return self


class EscalateIn(PhoneIn):
    topic: Literal["complaint", "urgent_change", "outside_zone", "large_order", "data_privacy",
                   "verification_failed", "other"]
    summary: str = Field(..., min_length=5, max_length=2000)
    ref_type: Literal["order", "consultation", "subscription"] | None = None
    ref_code: str | None = None
    approval_rule: str | None = Field(None, description="Mã APR-xx trong policy.yaml nếu agent xác định được")


class ConsultationIn(BaseModel):
    customer: CustomerIn
    event_type: Literal["wedding", "opening", "conference", "party"]
    mode: Literal["studio", "online", "onsite"] = "studio"
    appointment_date: date
    appointment_time: str = Field(..., description="09:00 | 10:30 | 14:00 | 15:30 (khảo sát tận nơi: 09:00 | 14:00)")
    event_date: date
    venue: str | None = Field(None, max_length=255)
    zone_id: str | None = Field(None, description="Bắt buộc với khảo sát tận nơi (Z1–Z3)")
    guest_count: int | None = Field(None, ge=1, le=2000)
    budget_range: str | None = Field(None, max_length=60)
    note: str | None = Field(None, max_length=500)


class ConsultRescheduleIn(PhoneIn):
    new_date: date
    new_time: str
    reason: str | None = None


class EventDateChangeIn(PhoneIn):
    new_event_date: date
    reason: str | None = None


class SubscriptionIn(BaseModel):
    customer: CustomerIn
    plan_id: str
    term_months: Literal[1, 3, 6] = 1
    start_date: date
    delivery_weekday: int | None = Field(None, ge=0, le=6, description="0 = Thứ Hai ... 6 = Chủ Nhật; bỏ trống với gói Hoa Cúng")
    slot_code: str
    zone_id: str
    delivery_address: str = Field(..., min_length=5, max_length=255)
    recipient_name: str | None = None
    recipient_phone: str | None = None
    payment_method: Literal["bank_transfer", "momo", "vnpay"] = "bank_transfer"
    note: str | None = Field(None, max_length=300)


class SubPauseIn(PhoneIn):
    resume_date: date = Field(..., description="Ngày giao lại sớm nhất (tối đa 30 ngày)")


class SubRescheduleIn(PhoneIn):
    delivery_weekday: int | None = Field(None, ge=0, le=6)
    slot_code: str | None = None


class StaffDecisionIn(BaseModel):
    decision: Literal["approve", "reject", "complete"]
    staff_name: str = Field(..., min_length=2)
    note: str | None = None
    approved_amount: int | None = Field(None, ge=0, description="Ghi đè số tiền hoàn / giá trị mã khi duyệt")
