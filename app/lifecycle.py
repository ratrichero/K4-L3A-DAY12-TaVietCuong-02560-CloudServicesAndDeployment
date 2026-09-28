"""CP4 — Graceful shutdown.

Khi bạn deploy phiên bản mới, orchestrator (Docker, Railway, Cloud Run, K8s)
gửi **SIGTERM** rồi đợi vài chục giây trước khi SIGKILL. Nếu app bỏ qua tín
hiệu đó, mọi request đang xử lý dở bị cắt giữa chừng — user thấy lỗi 502 mỗi
lần bạn deploy.

Ứng xử đúng: nhận SIGTERM → báo "tôi sắp tắt" qua health check để load
balancer ngừng đẩy traffic mới vào → xử lý nốt request đang chạy → thoát.
"""

from __future__ import annotations

import signal


class Lifecycle:
    """Giữ trạng thái vòng đời của process."""

    def __init__(self) -> None:
        self.shutting_down = False
        # Handler đã được đăng ký trước ta (của uvicorn) — xem install()
        self._previous: dict = {}

    def request_shutdown(self, signum=None, frame=None) -> None:
        """Signal handler: đánh dấu process đang tắt dần.

        Chỉ làm việc rất nhẹ (bật cờ) — handler chạy xen giữa bytecode.
        Sau đó gọi lại handler cũ: mỗi tín hiệu chỉ có MỘT handler, đăng ký
        handler của mình là ghi đè handler dừng server của uvicorn. Không
        nhường lại thì app bật cờ "đang tắt" rồi chạy tiếp mãi mãi cho tới
        khi bị SIGKILL — đúng cái graceful shutdown định tránh.
        """
        self.shutting_down = True
        previous = self._previous.get(signum)
        if callable(previous):
            previous(signum, frame)

    def install(self) -> None:
        """Đăng ký handler cho SIGTERM và SIGINT, nhớ lại handler cũ."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._previous[sig] = signal.getsignal(sig)  # nhớ handler cũ
            signal.signal(sig, self.request_shutdown)  # rồi mới ghi đè


# Một instance dùng chung cho cả app
lifecycle = Lifecycle()
