# Demo NarrativeHealth — không thay cấu trúc bài lab

## Phạm vi

App vẫn ở `app/main.py`: `/health`, `/ready`, `/ask`, API key, sliding-window
rate limiter, Redis history và cost guard. **Mock là mặc định**; giữ nguyên
`utils/mock_llm.py`, bộ test gốc và `grade.py`. Thêm adapter Python độc lập tại
`app/real_agent.py`, không cần Next.js, LangChain, MCP hoặc backend NarrativeHealth.

Đã triển khai các phần CP1–CP4 cần thiết để chạy demo, bổ sung Dockerfile
multi-stage/non-root và Compose. CP5, ảnh bằng chứng, 10 câu phản ánh và bonus
CI/CD **chưa được hoàn thành**. Không dùng điểm test tĩnh để kết luận đã build
image dưới 500 MB hoặc đã deploy cloud.

## 1. Cấu hình (không gửi secret vào chat)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Điền trực tiếp vào `.env`:

| Biến | Nội dung |
|---|---|
| `AGENT_API_KEY` | Key riêng bảo vệ `/ask`, không phải key LLM |
| `DATABASE_URL` | URI `postgresql://…` hoặc `postgres://…`, role chỉ đọc |
| `LLM_PRIMARY_BASE_URL` | HTTPS API base, thường kết thúc `/v1`; **không** thêm `/chat/completions` |
| `LLM_PRIMARY_API_KEY`, `LLM_PRIMARY_MODEL` | Provider chính |
| `LLM_SECONDARY_BASE_URL`, `LLM_SECONDARY_API_KEY`, `LLM_SECONDARY_MODEL` | Provider dự phòng; điền đủ cả ba hoặc để trống cả ba |
| `LLM_MAX_INPUT_USD_PER_MILLION`, `LLM_MAX_OUTPUT_USD_PER_MILLION` | Bắt buộc khi bật real mode: giá trần cao nhất của **cả hai** model, USD/1 triệu token, không có giá giả định |
| `REAL_AGENT_ENABLED` | `true` để demo thật; `false` để chạy mock |
| `REAL_AGENT_GLOBAL_BUDGET_USD` | Tổng ngân sách tháng cho toàn service; mặc định 10 USD |

`LLM_MAX_OUTPUT_TOKENS` mặc định 1200. Nếu provider yêu cầu, đổi
`LLM_OUTPUT_LIMIT_PARAMETER` từ `max_tokens` sang `max_completion_tokens`.
Hai provider phải hỗ trợ OpenAI Chat Completions **function/tool calling**;
đây không phải legacy `/completions` hoặc Responses API. Client không gửi
`temperature` để tránh xung đột với model không hỗ trợ tham số này.

Settings kiểm tra cấu hình lúc startup; bật real mode nhưng thiếu DB/provider/
giá token sẽ không khởi động. Khi cả hai provider lỗi, trả 502, **không chuyển
âm thầm sang mock**. API không streaming để giữ contract của lab.

### PostgreSQL hiện có

- Chỉ đọc các bảng trong schema `public`: `coins`, `health_scores`,
  `recommendations`, `narratives`, `narrative_health`, `market_price_daily`.
- Dùng role chỉ có `CONNECT`, schema `USAGE`, `SELECT` trên các bảng cần thiết;
  không cấp quyền owner/superuser, ghi dữ liệu, migration hoặc thực thi hàm tùy ý.
- Client cũng bật transaction read-only và statement timeout 8 giây.
- URL remote nên có `sslmode=verify-full` cùng CA phù hợp theo nhà cung cấp.
  Không bỏ kiểm tra TLS. Không đưa credential DB vào prompt LLM.
- Không tạo bảng, chạy migration, scheduler, collector hoặc ghi chat vào DB cũ.
  Redis **riêng cho lab** giữ history/quota/budget; không dùng Redis production
  đang chứa các key trùng tên. Không dùng `fake://` khi deploy/scale.
- Kết quả tool (giá/score/recommendation) được gửi tới provider LLM. Chỉ sử dụng
  dữ liệu bạn được phép gửi; không mở rộng tool sang dữ liệu người dùng/secret.

Schema đối chiếu từ [NarrativeHealth/src/db/schema.ts](https://github.com/ratrichero/NarrativeHealth/blob/main/src/db/schema.ts)
và ý tưởng từ [src/lib/chat](https://github.com/ratrichero/NarrativeHealth/tree/main/src/lib/chat).
Đây là tập con viết lại, không phải bản sao toàn bộ agent hoặc P4/P5 của dự án.
Schema DB đang chạy có thể khác GitHub: cần kiểm tra thật sau khi cấu hình.

## 2. Chạy demo

### Docker (máy đã cài Docker)

```bash
docker compose up --build -d
docker compose logs -f agent
```

Compose truyền các biến demo vào container, Redis qua `redis://redis:6379/0`.
Cổng app trong Compose cố định 8000 để khớp mapping; khi chạy image trực tiếp
trên cloud, Dockerfile đọc `$PORT`. `localhost` trong container **không phải**
máy host; DB phải truy cập được từ mạng container. Compose mặc định phục vụ
một instance, chưa thêm Nginx/load balancing; muốn `--scale agent=3` cần xử lý
port mapping/LB trước (các instance không thể cùng chiếm host port 8000).

### Python trực tiếp

```bash
# Chạy Redis riêng hoặc docker compose up -d redis, rồi:
python -m app.main
```

Mở `http://localhost:8000/docs` để thử `/ask`; nhập key trong header
`X-API-Key` và `X-User-Id` (ví dụ `demo`). Các câu thử:

- “Health score gần nhất của BTC trong NarrativeHealth là bao nhiêu?”
- “Đánh giá narrative AI từ dữ liệu đã lưu, nêu ngày dữ liệu.”
- “Cho tôi 7 giá đóng cửa gần nhất của BTC trong DB.”

Hoặc gọi bằng Python để đọc key từ `.env`, không copy key vào shell history:

```bash
python - <<'PY'
import httpx
from app.config import get_settings
s = get_settings()
r = httpx.post(f"http://localhost:{s.port}/ask",
    headers={"X-API-Key": s.agent_api_key, "X-User-Id": "demo"},
    json={"question": "Health score BTC gần nhất? Nêu rõ ngày dữ liệu."},
    timeout=150)
print(r.status_code)
print(r.json())
PY
```

Agent có ba tool, chỉ SQL tham số hóa, không có `execute_sql`:

| Tool | Dữ liệu |
|---|---|
| `get_coin_health(symbol)` | Điểm, thay đổi, status, recommendation gần nhất |
| `get_narrative_health(name)` | Điểm, thay đổi, số coin gần nhất; tên khớp không phân biệt hoa thường |
| `get_price_history(symbol, days)` | Tối đa 60 hàng close theo ngày gần nhất trong DB |

Dữ liệu là **snapshot**, không phải giá realtime. Không có đặt lệnh giao dịch.
Mỗi tool trả nguồn/thời điểm truy vấn và ngày dữ liệu nếu có. Khi không có dữ
liệu hoặc DB lỗi, agent được chỉ dẫn nói rõ thay vì bịa; prompt không bảo đảm
LLM luôn tuân thủ, nên đối chiếu số liệu trực tiếp với DB khi demo.

## 3. Chi phí và bảo vệ

- Trước network call: reserve ngân sách qua Redis `WATCH/MULTI`, đồng thời
  theo user và toàn service (đổi `X-User-Id` không tạo ngân sách tổng mới).
- Tối đa 4 lượt LLM, tối đa 4 tool/lượt ở 3 lượt đầu; lượt cuối chỉ tổng hợp.
  Mỗi lượt tối đa một attempt chính + một dự phòng. Không retry vô hạn.
- Input bị giới hạn trước mỗi attempt bằng kích thước UTF-8 transcript + tool
  definitions + phần đệm 1024, so với `LLM_MAX_INPUT_TOKENS` (mặc định 32000).
  Đây là **ước lượng bảo thủ, không phải tokenizer chính thức**.
- Cộng usage của tất cả lượt thành công. Attempt lỗi/mất usage bị tính tạm
  mức trần, không coi như miễn phí. Refund phần reserve chưa dùng, kể cả khi
  lỗi giữa chừng hoặc sang tháng; receipt chống settle trùng.
- Response `cost_usd` là **ước lượng theo giá trần**, không phải hóa đơn.
  `cost_is_estimate=true`; `usage_complete=false` nếu có attempt không rõ usage.
  Trường tokens là phần usage đã biết, không bịa token cho attempt lỗi.
- Nếu process chết hoặc Redis settlement lỗi: giữ reservation để fail closed.
  Đối soát trước khi chỉnh ledger thủ công; không xóa key tùy tiện.
- Deadline logic một turn 90 giây; từng call có timeout, giới hạn body 1 MB,
  tool output 4 KB JSON. Một thao tác blocking đang chạy có thể kéo dài qua
  deadline tới timeout của nó. Compose cho 150 giây graceful shutdown; trên
  cloud kiểm tra grace period của platform khi demo câu hỏi dài.
- Vẫn cần **hard spending cap ở provider**: tokenizer/giá/billing reasoning
  tokens, retry ngoài service hoặc sai cấu hình có thể làm phí thật khác.
  API-key dùng chung + user ID tùy khai không phải hệ thống đăng nhập đa tenant;
  chỉ chia sẻ key với người được phép demo, tránh public key trong frontend.

`/health` không kiểm tra dependency; `/ready` theo rubric chỉ kiểm tra Redis.
Readiness 200 **không chứng minh** DB/LLM hoạt động. Quan sát `/ask` có xác thực
và log `llm_attempt_failed`, `database_tool_failed`, `real_agent_failed`.
Log chỉ loại lỗi/status/provider, không in key, URL DB hoặc body lỗi upstream.

## 4. Test và trạng thái xác minh

```bash
pytest tests/test_cp1.py tests/test_cp2.py tests/test_cp3.py tests/test_cp4.py tests/test_real_agent.py -q
```

`conftest.py` bổ sung ở gốc ép **local tests** chạy mock trước khi test gốc đọc
`.env`; không sửa test gốc hoặc `grade.py`. Test adapter dùng `httpx.MockTransport`
và Redis/DB giả. `CP5` vẫn có thể gọi URL đã deploy theo đề (có thể tốn một request
thật nếu bạn điền `DEPLOY_API_KEY`).

Chưa xác minh kết nối PostgreSQL/LLM thật do chưa có credential; chưa build
Docker vì sandbox không có Docker. Bạn tự điền `.env`, chạy demo, rồi điền URL,
ảnh và kết quả thật vào `DEPLOYMENT.md`. Không bịa bằng chứng hoặc trả lời thay
các quan sát trong `exercises.md`.
