"""Mộc Miên Florist — API nghiệp vụ giả lập (FastAPI + sqlite3).

Chạy:  uvicorn app.main:app --reload --port 8000   (trong thư mục api/)
Tài liệu tương tác: http://localhost:8000/docs
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from .config import settings
from .errors import ApiError, install_handlers
from .policy import get_policy
from .routers import catalog, consultations, orders, requests, staff, subscriptions
from .utils import now


def require_api_key(x_api_key: str | None = Header(None, description="Chỉ cần khi đặt biến môi trường API_KEY")) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise ApiError(401, "UNAUTHORIZED", "Thiếu hoặc sai X-API-Key.")


app = FastAPI(
    title="Mộc Miên Florist — API nghiệp vụ giả lập",
    version="1.0.0",
    description=(
        "API cho agent CSKH của tiệm hoa Mộc Miên (Ninh Kiều & Cái Răng, Cần Thơ). "
        "Dữ liệu tổng hợp; mọi ngưỡng chính sách đọc từ policy.yaml. "
        "Mặc định đồng hồ cố định MOCK_NOW=2026-10-16T08:00+07:00 để kịch bản test tái lập được."
    ),
)
install_handlers(app)


@app.get("/health", tags=["Hệ thống"])
def health():
    policy = get_policy()
    return {"status": "ok", "workspace": policy["meta"]["workspace"], "policy_version": policy["meta"]["version"],
            "now": now().isoformat(), "mock_clock": settings.mock_now is not None}


for r in (catalog.router, orders.router, consultations.router, subscriptions.router, requests.router):
    app.include_router(r, dependencies=[Depends(require_api_key)])
app.include_router(staff.router)
