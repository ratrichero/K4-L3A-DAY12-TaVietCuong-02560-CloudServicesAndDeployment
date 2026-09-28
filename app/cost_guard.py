"""CP3 — Cost guard: chặn chi phí trước khi hóa đơn chặn bạn.

Rate limit giới hạn *số lượng* request. Cost guard giới hạn *số tiền*: một
user gửi 10 request/phút nhưng mỗi request 50k token vẫn đốt sạch ngân sách.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

# Giữ dữ liệu chi tiêu thêm ~40 ngày để còn đối soát sang tháng sau
KEY_TTL_SECONDS = 40 * 24 * 3600


class CostGuard:
    def __init__(self, client, monthly_budget_usd: float) -> None:
        self.client = client
        self.budget = monthly_budget_usd

    @staticmethod
    def current_month() -> str:
        """CHO SẴN — nhãn tháng hiện tại dạng '2026-08' (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y-%m")

    @classmethod
    def _key(cls, user_id: str, month: str | None = None) -> str:
        """CHO SẴN — khóa Redis theo từng user, từng tháng."""
        return f"cost:{user_id}:{month or cls.current_month()}"

    def spent(self, user_id: str, month: str | None = None) -> float:
        """Số tiền user đã tiêu trong tháng.

        TODO (CP3): đọc ``self.client.get(self._key(user_id, month))``.
        Key chưa tồn tại → Redis trả None → hàm này phải trả ``0.0``.
        Nhớ ép kiểu ``float(...)`` vì Redis trả về chuỗi.
        """
        value = self.client.get(self._key(user_id, month))
        return float(value) if value is not None else 0.0

    def check(
        self,
        user_id: str,
        estimated_cost: float = 0.0,
        month: str | None = None,
    ) -> None:
        """Cho qua nếu còn ngân sách, ngược lại raise 402.

        TODO (CP3): nếu ``spent(user_id) + estimated_cost > self.budget``
        → raise ``HTTPException(status_code=402, detail="monthly budget exceeded")``.
        402 = Payment Required, đúng ngữ nghĩa cho tình huống hết ngân sách.
        """
        if self.spent(user_id, month) + estimated_cost > self.budget:
            raise HTTPException(status_code=402, detail="monthly budget exceeded")

    def record(self, user_id: str, cost: float, month: str | None = None) -> float:
        """Cộng dồn chi phí vừa phát sinh, trả về tổng mới.

        TODO (CP3):
          1. ``total = self.client.incrbyfloat(key, cost)``
          2. ``self.client.expire(key, KEY_TTL_SECONDS)``
          3. ``return float(total)``
        """
        key = self._key(user_id, month)
        total = self.client.incrbyfloat(key, cost)
        self.client.expire(key, KEY_TTL_SECONDS)
        return float(total)

    def reserve(self, user_id: str, amount: float, global_budget: float | None = None) -> tuple[str, str]:
        """Real mode: atomically check + reserve the entire turn before any I/O.

        Keep the original month's key in the returned receipt. Existing lab
        keys remain USD strings; Decimal + WATCH avoids rounding accumulation
        without changing the checkpoint's storage contract.
        """
        import json
        from decimal import Decimal
        from uuid import uuid4
        from redis.exceptions import WatchError

        value = Decimal(str(amount))
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid reservation")
        month = self.current_month()
        key = self._key(user_id, month)
        global_key = f"global-cost:{month}" if global_budget is not None else None
        receipt = f"cost-reservation:{uuid4().hex}"
        for _ in range(8):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(*([key, global_key] if global_key else [key]))
                    current = Decimal(pipe.get(key) or "0")
                    if current + value > Decimal(str(self.budget)):
                        raise HTTPException(status_code=402, detail="monthly budget exceeded")
                    global_current = Decimal(pipe.get(global_key) or "0") if global_key else Decimal("0")
                    if global_key and global_current + value > Decimal(str(global_budget)):
                        raise HTTPException(status_code=402, detail="global monthly budget exceeded")
                    pipe.multi()
                    if global_key:
                        pipe.set(global_key, str(global_current + value), ex=KEY_TTL_SECONDS)
                    pipe.set(key, str(current + value), ex=KEY_TTL_SECONDS)
                    pipe.set(receipt, json.dumps({"reserved": str(value), "global_key": global_key}), ex=KEY_TTL_SECONDS)
                    pipe.execute()
                    return key, receipt
                except WatchError:
                    continue
        raise HTTPException(status_code=503, detail="budget busy; retry later")

    def settle(self, reservation: tuple[str, str], incurred: float) -> None:
        """Refund unused reservation exactly once, including across month rollover.

        Failure leaves the reservation charged (fail closed); never retry a paid
        request simply because settlement failed. Unknown/crashed turns keep
        their full reservation. Caller must not also call record in real mode.
        """
        import json
        from decimal import Decimal
        from redis.exceptions import WatchError

        value = Decimal(str(incurred))
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid cost")
        key, receipt = reservation
        for _ in range(8):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(key, receipt)
                    reserved = pipe.get(receipt)
                    if reserved is None:
                        return
                    data = json.loads(reserved)
                    global_key = data["global_key"]
                    if global_key:
                        pipe.watch(global_key)
                        global_current = Decimal(pipe.get(global_key) or "0")
                    current = Decimal(pipe.get(key) or "0")
                    refund = Decimal(data["reserved"]) - value
                    total = max(Decimal("0"), current - refund)
                    pipe.multi()
                    pipe.set(key, str(total), ex=KEY_TTL_SECONDS)
                    if global_key:
                        pipe.set(global_key, str(max(Decimal("0"), global_current - refund)), ex=KEY_TTL_SECONDS)
                    pipe.delete(receipt)
                    pipe.execute()
                    return
                except WatchError:
                    continue
        raise HTTPException(status_code=503, detail="budget settlement busy")
