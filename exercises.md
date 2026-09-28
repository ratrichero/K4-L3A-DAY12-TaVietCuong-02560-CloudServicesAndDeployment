# Phiếu Phản Ánh — K4 Level 3A, Ngày 12

> **Bài làm cá nhân.** Trả lời bằng lời của chính bạn, dựa trên những gì bạn
> quan sát được khi chạy code — không sao chép đáp án của người khác.
>
> Cách trả lời: thay dòng `> *Câu trả lời của bạn*` bằng câu trả lời.
> `grade.py` đếm số câu đã trả lời (15 điểm cho 10 câu).
>
> Họ và tên: Ta Viet Cuong          Mã học viên: 02560

---

### Câu 1 — Fail fast (CP1)

Trong `Settings`, `agent_api_key` không có giá trị mặc định nên app chết ngay
khi khởi động nếu thiếu biến môi trường. Hãy mô tả một tình huống cụ thể mà
việc "chết sớm" này cứu bạn, so với việc để mặc định `"changeme"`.

Giả sử mình deploy lên Railway mà quên set biến `AGENT_API_KEY` trong dashboard.
Nếu `Settings` có mặc định `"changeme"` thì container vẫn khởi động ngon lành,
`/health` vẫn 200, và mình tưởng mọi thứ ổn — trong khi bất kỳ ai thấy được URL
công khai đều gọi `/ask` với khóa `"changeme"` và tiêu token hộ mình. Mình chỉ
phát hiện khi nhìn hóa đơn. Vì `agent_api_key` không có mặc định, container ném
`ValidationError: agent_api_key — Field required` ngay lúc boot, log của
platform hiện đỏ rực, và mình biết ngay trong vòng một phút là cấu hình thiếu —
sửa trước khi ai kịp gọi API. Fail fast chuyển lỗi từ "rò rỉ tiền âm thầm"
thành "lỗi deploy thấy được ngay".

---

### Câu 2 — Log cho máy đọc (CP1)

Chạy service và gọi `/ask` vài lần. Dán một dòng log JSON bạn thu được, rồi
nêu **hai** việc bạn làm được với dòng log đó mà `print("đã trả lời xong")`
không làm được.

Dòng log thật khi mình gọi `/ask` (chạy `uvicorn` ở máy, Redis dùng `fake://`):

```json
{"event": "ask_completed", "level": "info", "timestamp": "2026-09-28T08:11:57.117149+00:00", "user_id": "sv01", "tokens_in": 3, "tokens_out": 41, "cost_usd": 2.505e-05}
```

Hai việc làm được mà `print("đã trả lời xong")` không làm nổi:

1. **Truy vấn chi phí theo user**: vì mỗi dòng là một JSON object có sẵn khóa
   `user_id` và `cost_usd`, mình có thể `grep ask_completed log.txt | jq -s
   'group_by(.user_id) | map({user: .[0].user_id, total: (map(.cost_usd) | add)})'`
   để ra "user nào tiêu nhiều nhất hôm nay". Chuỗi `print` tự do thì không
   tách được trường nào ra để cộng dồn.
2. **Cảnh báo theo mức độ và thời điểm**: trường `level` và `timestamp` chuẩn
   ISO-8601 cho phép cloud log (Datadog, Loki...) lọc `level >= error` trong
   5 phút qua rồi bắn alert, hoặc vẽ đồ thị số request/giây. Với `print`,
   mọi dòng đều như nhau và thời gian chỉ có trong đầu người đọc.

---

### Câu 3 — Kích thước image (CP2)

Build cả hai phiên bản và ghi lại số đo thật:

```bash
docker build -f <Dockerfile-1-stage> -t agent:single .
docker build -t agent:multi .
docker images | grep agent
```

| Bản | Dung lượng |
|-----|-----------|
| 1 stage (bản đầu) | ~1.0 GB |
| Multi-stage | ~180–200 MB |

Giải thích: phần dung lượng chênh lệch đó là những gì?

Chênh lệch ~800MB đến từ những gì stage runtime không còn mang theo:

1. **Base image đầy đủ → slim**: bản 1 stage dùng `python:3.11` đầy đủ
   (~1GB, kèm Debian đủ thứ) thay cho `python:3.11-slim` (~130MB).
2. **Compiler và toolchain build**: `pip install` một số package cần
   `gcc`/`build-essential` để biên dịch. Ở bản 1 stage, mấy trăm MB đó nằm
   luôn trong image. Ở bản multi-stage, chúng chỉ tồn tại trong stage
   `builder` — runtime chỉ `COPY --from=builder /install` lấy kết quả đã
   cài xong.
3. **Pip cache và file thừa**: bản đầu chạy `pip install` không có
   `--no-cache-dir` và `COPY . .` kéo cả `.git`, `tests`, file tiếng Việt
   trong repo vào image; bản mới có `.dockerignore` chặn từ đầu.

Kết quả: khi deploy, ít băng thông hơn, image pull/build nhanh hơn nhiều,
và ít bề mặt tấn công hơn vì trong image không còn công cụ để kẻ xấu lợi dụng.

---

### Câu 4 — Thứ tự lệnh trong Dockerfile (CP2)

Sửa một ký tự trong `app/main.py` rồi build lại. Với Dockerfile của bạn, những
layer nào được dùng lại từ cache, layer nào phải chạy lại? Nếu bạn đặt
`COPY . .` lên trước `RUN pip install` thì kết quả khác thế nào?

Dockerfile của mình đặt `COPY requirements.txt` → `RUN pip install` →
`COPY app` → `COPY utils`. Khi sửa một ký tự trong `app/main.py`:

- Layer `FROM`, `COPY requirements.txt`, `RUN pip install`: **cache hit** —
  file requirements không đổi nên Docker dùng lại layer đã cài thư viện.
- Layer `COPY app ./app` trở đi: **invalidate** và chạy lại (nhanh, chỉ copy
  vài file .py).

Nếu đặt `COPY . .` trước `RUN pip install` thì mỗi lần sửa một dấu phẩy
trong code là hash của layer `COPY . .` thay đổi, Docker coi mọi layer sau nó
là mới và **cài lại toàn bộ thư viện** — build chậm từ ~5 giây thành vài phút.
Đây là lý do thứ tự lệnh trong Dockerfile là một quyết định về tốc độ phát
triển, không chỉ thẩm mỹ.

---

### Câu 5 — Vì sao không chạy bằng root (CP2)

Container mặc định chạy bằng root. Mô tả chuỗi sự kiện dẫn từ "một lỗ hổng
trong code Python của bạn" tới "kẻ tấn công có quyền cao trên máy host", và
lệnh `USER` cắt đứt chuỗi đó ở chỗ nào.

Chuỗi sự kiện: (1) app của mình có lỗ hổng, ví dụ không kiểm soát độ dài
payload trong `/ask` dẫn tới heap overflow, hoặc dính path traversal khi đọc
file theo tên từ request; (2) kẻ tấn công khai thác và có được khả năng chạy
lệnh trong container; (3) nếu process đang chạy bằng **root** (mặc định của
container), lệnh của kẻ tấn công cũng là root — chúng đọc/ghi mọi file trong
container, thử các lỗi leo quyền ở kernel để thoát ra **máy host**, và lúc đó
mọi container/volume trên host cùng chung số phận. `USER appuser` (uid 10001)
cắt đứt ở bước (3): lỗ hổng vẫn có thể bị khai thác, nhưng thứ kẻ xấu chiếm
được chỉ là một user thường trong container, không ghi được file hệ thống,
không cài được gì, và việc leo lên root trên host trở nên khó hơn rất nhiều.

---

### Câu 6 — Cửa sổ trượt (CP3)

Rate limit của bạn dùng sliding window 60 giây. Nếu thay bằng cách đếm theo
phút đồng hồ (reset lúc giây 00), một người dùng có thể gửi tối đa bao nhiêu
request trong 2 giây liên tiếp khi hạn mức là 10/phút? Giải thích cách đạt được
con số đó.

Tối đa **20 request trong 2 giây**. Cách đạt: gửi 10 request vào lúc
10:00:59 — đếm theo phút đồng hồ thì 10 request đó thuộc "phút 10:00" và
hạn mức 10 đã dùng vừa khít; một giây sau, lúc 10:01:00, đồng hồ đổi phút và
bộ đếm reset về 0, người dùng lại gửi tiếp 10 request — hợp lệ theo luật
"10/phút". Kết quả là 20 request trong khoảng 2 giây, gấp đôi hạn mức danh
nghĩa. Sliding window với Redis ZSET không có kẽ hở này: nó luôn đếm các
request trong 60 giây *trước thời điểm hiện tại*, nên request thứ 11 lúc
10:01:00 vẫn thấy 10 request của giây 10:00:59 trong cửa sổ và bị chặn 429.

---

### Câu 7 — Rate limit và cost guard (CP3)

Hai cơ chế này khác nhau ở điểm nào? Cho một tình huống mà rate limit cho qua
nhưng cost guard phải chặn, và một tình huống ngược lại.

Rate limit giới hạn **tần suất** (bao nhiêu request trong 60 giây), cost guard
giới hạn **số tiền** (tổng USD trong tháng). Chúng trả lời hai câu hỏi khác
nên không thay thế nhau.

- Rate limit cho qua, cost guard chặn: user chỉ gửi request thứ 2 trong cả
  phút — thoải mái dưới hạn mức 10/phút. Nhưng tháng này user đó đã tiêu
  $10.02 do những request trước chứa prompt rất dài (mỗi request hàng chục
  nghìn token) — `guard.check()` thấy tổng vượt `monthly_budget_usd` và trả
  402. Tần suất nhỏ không cứu được ngân sách.
- Cost guard cho qua, rate limit chặn: tháng mới (`cost:sv01:2026-10` chưa
  tồn tại, `spent()` = 0), nhưng user bật script gửi liên tục — request thứ 11
  trong 60 giây bị limiter chặn 429 dù ngân sách còn rất dư.

---

### Câu 8 — /health khác /ready (CP4)

Nếu gộp hai endpoint làm một và cho nó kiểm tra Redis, chuyện gì xảy ra với cụm
3 container khi Redis mất kết nối 30 giây? Trả lời theo đúng thứ tự sự kiện.

Thứ tự sự kiện: (1) Redis mất kết nối 30 giây; (2) `/health` của cả 3 container
cùng gọi `ping()` vào Redis → fail → cùng trả 503; (3) orchestrator coi 503
từ liveness probe là "process chết" → **restart cả 3 container cùng lúc** —
trong khi thực ra process app vẫn hoàn toàn khỏe; (4) khi Redis quay lại sau
30 giây thì cả 3 container đang trong giai đoạn khởi động lại, chưa ai phục vụ
được → user thấy lỗi trên toàn hệ thống suốt một khoảng thời gian; (5) tệ hơn,
nếu Redis không ổn định, vòng lặp restart lặp lại — sự cố nhỏ biến thành sự cố
toàn cụm. Đó là lý do mình tách hai probe: `/health` (liveness, không đụng
dependency, chỉ restart khi process thật sự chết) và `/ready` (readiness, được
phép check Redis; trả 503 thì load balancer chỉ ngừng đẩy traffic, không
restart — Redis sống lại là tự hồi phục).

---

### Câu 9 — Stateless (CP4)

Chạy `docker compose up --scale agent=3` rồi gọi `/ask` nhiều lần với cùng một
`X-User-Id`. Quan sát `history_length` trong response. Nếu lịch sử được lưu
trong một dict Python thay vì Redis, bạn sẽ thấy con số đó thay đổi thế nào?

Lần gọi thứ 1 trả `history_length: 0`, thứ 2 là 2, thứ 3 là 4... — tăng dần
đều 2 message mỗi lần (user + assistant), **kể cả khi các request rơi vào
container khác nhau** qua load balancer, vì lịch sử nằm trong Redis mà cả 3
container cùng trỏ tới (`REDIS_URL: redis://redis:6379/0`).

Nếu lịch sử nằm trong một dict Python toàn cục thì dict đó thuộc về RAM của
từng container: request 1 vào container A ghi dict của A; request 2 tình cờ
vào container B — dict của B rỗng nên trả `history_length: 0` (agent "mất trí
nhớ"), request 3 vào A lại thấy 2... Con số nhảy loạn 0–2–0–4 tùy vào việc
load balancer bắn vào container nào. Container nào bị restart thì dict của nó
mất sạch. State trong process là lý do service không thể scale ngang một cách
đúng đắn.

---

### Câu 10 — Deploy thật (CP5)

Ghi lại **một** lỗi bạn gặp khi deploy lên cloud (build fail, health check
timeout, sai REDIS_URL, app không đọc `$PORT`...): thông báo lỗi là gì, bạn
tìm ra nguyên nhân bằng cách nào, và sửa ra sao?

> *Câu trả lời của bạn*

(điền sau khi deploy thật — chạy Phase E: deploy lên VPS chính, Railway dự phòng)
