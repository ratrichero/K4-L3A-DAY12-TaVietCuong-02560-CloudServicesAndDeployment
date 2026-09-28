"""CP3 — Rate limiting bằng thuật toán sliding window.

Đếm số request trong 60 giây **gần nhất** (cửa sổ trượt), thay vì đếm theo
phút đồng hồ. Đếm theo phút đồng hồ có lỗ hổng: 10 request lúc 10:00:59 và
10 request lúc 10:01:01 = 20 request trong 2 giây mà vẫn "đúng luật".

Cấu trúc dữ liệu: Redis Sorted Set (ZSET), score = timestamp của request.
"""

from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, status

WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, client, limit_per_minute: int) -> None:
        self.client = client
        self.limit = limit_per_minute

    @staticmethod
    def _key(user_id: str) -> str:
        """CHO SẴN — mỗi user một key riêng."""
        return f"ratelimit:{user_id}"

    def hit_count(self, user_id: str, now: float | None = None) -> int:
        """Số request của user trong ``WINDOW_SECONDS`` giây gần nhất."""
        now = now if now is not None else time.time()
        key = self._key(user_id)
        # Vứt các entry đã ra khỏi cửa sổ trượt
        self.client.zremrangebyscore(key, 0, now - WINDOW_SECONDS)
        return self.client.zcard(key)

    def check(self, user_id: str, now: float | None = None) -> None:
        """Cho qua nếu còn quota, ngược lại raise 429.

        Thứ tự bắt buộc: **kiểm tra trước, ghi nhận sau**. Ghi trước rồi
        đếm sẽ chặn nhầm ngay ở request thứ ``limit``.
        """
        now = now if now is not None else time.time()
        key = self._key(user_id)

        if self.hit_count(user_id, now) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        # Ghi nhận SAU khi kiểm tra. Member phải DUY NHẤT (timestamp + uuid):
        # hai request cùng timestamp mà trùng member thì ZSET chỉ giữ một,
        # bạn đếm thiếu. Expire để key tự dọn khi user ngừng gọi.
        member = f"{now}:{uuid.uuid4().hex}"
        self.client.zadd(key, {member: now})
        self.client.expire(key, WINDOW_SECONDS)
