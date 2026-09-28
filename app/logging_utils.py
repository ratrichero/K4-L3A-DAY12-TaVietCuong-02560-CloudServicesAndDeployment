"""CP1 — Structured logging.

`print("user abc hỏi gì đó")` là log cho người đọc. Cloud (Railway, Render,
Cloud Run, Datadog...) đọc log bằng máy: một dòng = một JSON object thì mới
lọc/đếm/cảnh báo được. Đây là khác biệt lớn giữa localhost và production.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """CHO SẴN — thời điểm hiện tại theo ISO-8601, múi giờ UTC."""
    return datetime.now(timezone.utc).isoformat()


def log_event(event: str, level: str = "info", **fields) -> str:
    """Ghi một dòng log JSON ra stdout.

    Tạo dict gồm tối thiểu 3 khóa (event, level viết thường, timestamp),
    gộp thêm mọi cặp key/value trong ``**fields``, rồi in ra stdout trên
    MỘT dòng duy nhất — cloud gom log theo dòng, JSON xuống dòng là log vỡ.

    Ví dụ:
        >>> log_event("ask_completed", user_id="sv01", cost_usd=0.0001)
        '{"event": "ask_completed", "level": "info", "timestamp": "...", ...}'
    """
    entry = {
        "event": event,
        "level": level.lower(),
        "timestamp": utc_now_iso(),
        **fields,
    }
    # ensure_ascii=False để tiếng Việt trong log giữ nguyên dấu, không thành \u1ea1
    line = json.dumps(entry, ensure_ascii=False)
    print(line, file=sys.stdout, flush=True)
    return line
