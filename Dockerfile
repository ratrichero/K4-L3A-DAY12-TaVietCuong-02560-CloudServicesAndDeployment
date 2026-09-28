# ═══════════════════════════════════════════════════════════════════
# CP2 — Production-ready image
#
#   - Multi-stage: builder cài dependency (được phép nặng), runtime chỉ
#     nhận KẾT QUẢ → không mang compiler theo, image ~200MB thay vì ~1GB
#   - Base image slim
#   - COPY requirements.txt + pip install TRƯỚC khi copy source code
#     (Docker cache theo layer: sửa code không phải cài lại thư viện)
#   - Chạy bằng user thường, không phải root
#   - HEALTHCHECK để Docker biết container còn phục vụ được không
#   - Đọc cổng từ biến $PORT (Railway/Render/Cloud Run tự gán cổng)
# ═══════════════════════════════════════════════════════════════════

# ── Stage 1: builder — cài dependency, bị vứt đi sau khi build ──
FROM python:3.11-slim AS builder

WORKDIR /build

# Dependency cài vào /install để stage runtime copy nguyên cụm
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime — chỉ chứa những thứ cần để chạy ──
FROM python:3.11-slim AS runtime

WORKDIR /app

# User thường (uid 10001): lỗ hổng trong app cũng không leo lên root trên host
RUN useradd --create-home --uid 10001 appuser

# Dependency đã cài sẵn từ builder — không cài lại, không mang compiler
COPY --from=builder /install /usr/local

# Code copy SAU dependency để tận dụng Docker cache
COPY app ./app
COPY utils ./utils

USER appuser

# PORT do platform gán lúc deploy; 8000 là mặc định khi chạy compose ở máy
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000')).read()" || exit 1

# 0.0.0.0: bind vào 127.0.0.1 thì bên ngoài container không gọi vào được
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
