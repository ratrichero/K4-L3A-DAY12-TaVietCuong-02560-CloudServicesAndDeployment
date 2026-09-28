"""CP3 — Xác thực bằng API key.

Public URL = ai cũng gọi được. Không có lớp này, hóa đơn LLM của bạn do
người lạ quyết định.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings

ANONYMOUS_USER = "anonymous"


def verify_api_key(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    """Kiểm tra header ``X-API-Key``; trả về user_id nếu hợp lệ.

    So sánh khóa bằng ``secrets.compare_digest`` chứ không phải ``==``:
    toán tử ``==`` dừng ngay tại ký tự đầu tiên khác nhau, nên thời gian
    phản hồi rò rỉ thông tin về khóa (timing attack). ``compare_digest``
    luôn chạy hết chuỗi, thời gian không phụ thuộc vị trí khác nhau.
    """
    expected = get_settings().agent_api_key
    if (
        x_api_key is None
        or not secrets.compare_digest(x_api_key, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )
    return x_user_id if x_user_id else ANONYMOUS_USER
