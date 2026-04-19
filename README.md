# MedBot AI — Chatbot Tư vấn Y tế

Hệ thống chatbot sức khoẻ tích hợp Telegram, kết nối AI (Claude) với bác sĩ thực qua Doctor Dashboard. Người dùng chat trong **một thread duy nhất** — khi cần bác sĩ, bot tự relay hai chiều mà không cần mở chat mới.

## Kiến trúc

```
User (Telegram)
    ↓ text / ảnh / PDF / DOCX
Telegram Bot Gateway
    ↓ webhook
FastAPI Backend
    ├─ File Processor  (PDF/DOCX→text, image→base64)
    ├─ RAG Retriever   (LlamaIndex + ChromaDB)
    ├─ Claude AI       (claude-sonnet-4-20250514)
    └─ Scope Checker   (regex + Claude JSON)
         ↓ out-of-scope
Doctor Dashboard (WebSocket) ← bác sĩ nhận ca, reply
    ↓ relay
bot.send_message(user_chat_id)  → User nhận trong chat cũ
```

## Tech Stack

| Layer | Công nghệ |
|---|---|
| Telegram Bot | python-telegram-bot v21, webhook mode |
| Backend API | FastAPI + Uvicorn |
| AI Engine | Claude claude-sonnet-4-20250514 **hoặc** OpenAI GPT-4o (chọn qua `AI_ENGINE`) |
| RAG / Vector DB | LlamaIndex + ChromaDB + FastEmbed (BAAI/bge-small-en-v1.5) |
| File Processing | PyMuPDF, python-docx, Pillow |
| Realtime | WebSocket (FastAPI native) |
| Database | PostgreSQL 16 + SQLAlchemy async |
| Cache / Status | Redis 7 |
| Auth | JWT |
| Deploy | Docker Compose + Nginx |

---

## Cài đặt & Deploy

### 1. Chuẩn bị

```bash
git clone <repo>
cd MedBot

# Tạo file .env từ template
cp .env.example .env
```

Chỉnh sửa `.env`:

```env
TELEGRAM_TOKEN=<bot token từ @BotFather>
WEBHOOK_BASE_URL=https://yourdomain.com   # hoặc ngrok URL khi dev
JWT_SECRET=<random string dài>

# Chọn AI Engine
AI_ENGINE=anthropic          # hoặc "openai"

# Nếu dùng Claude (AI_ENGINE=anthropic)
ANTHROPIC_API_KEY=<Anthropic API key>
CLAUDE_MODEL=claude-sonnet-4-20250514

# Nếu dùng OpenAI (AI_ENGINE=openai)
OPENAI_API_KEY=<OpenAI API key>
OPENAI_MODEL=gpt-4o
```

### 2. Cấu hình Telegram Webhook

**Development (ngrok):**

```bash
ngrok http 80
# Copy URL ngrok vào WEBHOOK_BASE_URL trong .env
```

**Production:** trỏ domain thật về server, đảm bảo HTTPS.

### 3. Khởi động

```bash
docker compose up -d --build
```

Các service sẽ khởi động theo thứ tự: postgres → redis → chromadb → app → nginx.

### 4. Index Knowledge Base

```bash
bash scripts/init_kb.sh
# hoặc
docker compose run --rm embed-kb
```

Để thêm tài liệu y tế: đặt file `.txt`, `.pdf`, `.docx` vào `knowledge/medical_guidelines/` rồi chạy lại lệnh trên.

### 5. Chọn AI Engine

| `AI_ENGINE` | Model mặc định | API Key cần |
|---|---|---|
| `anthropic` | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |

Chỉ cần đổi biến `AI_ENGINE` trong `.env` và restart container — không cần thay đổi code:

```bash
# Chuyển sang OpenAI
echo "AI_ENGINE=openai" >> .env
echo "OPENAI_API_KEY=sk-..." >> .env
docker compose restart app
```

### 6. Kiểm tra

```bash
# Health check
curl http://localhost/health

# Xem logs
docker compose logs -f app
```

---

## Sử dụng

### Telegram Bot (Người dùng)

1. Tìm bot trên Telegram, bắt đầu chat.
2. **Gửi câu hỏi sức khoẻ thông thường** → bot trả lời bằng AI.
3. **Gửi câu hỏi cần bác sĩ** (kê đơn, chẩn đoán, thủ thuật) → bot hiển thị danh sách bác sĩ đang online.
4. **Chọn bác sĩ** → yêu cầu gửi đến bác sĩ.
5. Khi bác sĩ nhận ca → user nhận thông báo trong cùng chat, tiếp tục nhắn tin bình thường.
6. **Upload file** (PDF đơn thuốc, ảnh xét nghiệm, DOCX) → bot xử lý và phân tích, tự động chuyển bác sĩ nếu cần.

### Doctor Dashboard

Truy cập: `http://yourdomain.com/dashboard/`

**Đăng nhập:**
- Tài khoản demo mặc định: `doctor1` / `doctor123`
- Sau khi đăng nhập, bác sĩ tự động chuyển sang trạng thái **Online**.

**Workflow:**

1. **Nhận ca mới** → notification xuất hiện, ca hiển thị ở sidebar trái.
2. **Xem thông tin ca**: lịch sử chat với AI, summary, chuyên khoa, mức độ khẩn cấp.
3. **Nhấn "Nhận ca"** → session chuyển sang `active`, user nhận thông báo.
4. **Chat trực tiếp**: gõ tin nhắn → relay qua bot đến user (hiển thị `BS. Tên: nội dung`).
5. **Chuyển ca**: nhập doctor_id của bác sĩ khác → ca chuyển tự động.
6. **Kết thúc ca**: nhấn "✖ Kết thúc ca", nhập ghi chú → user nhận thông báo kết thúc.

**Quản lý trạng thái:**
- Dropdown góc trái: `Online` / `Bận` / `Offline`
- Khi `Offline` hoặc `Bận`, user sẽ không thấy bác sĩ trong danh sách chọn.

---

## API Endpoints

### Chat

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/chat` | Gửi tin nhắn text |
| POST | `/api/chat/file` | Upload file (PDF/DOCX/ảnh) |
| GET | `/api/doctors/online?specialty=Nội tổng quát` | Danh sách bác sĩ online |

**POST /api/chat:**
```json
{
  "telegram_chat_id": 123456789,
  "user_id": "tg_123456789",
  "message": "Tôi bị đau đầu 2 ngày",
  "session_id": null
}
```

Response in-scope:
```json
{"type": "ai_reply", "content": "...", "session_id": "uuid"}
```

Response out-of-scope:
```json
{
  "type": "request_doctor",
  "reason": "Yêu cầu kê đơn thuốc",
  "specialty": "Nội tổng quát",
  "urgency": "medium",
  "doctors": [{"id": "uuid", "name": "BS. Nguyễn Minh Tuấn", "specialty": "..."}]
}
```

### Doctor

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/doctor/login` | Đăng nhập, nhận JWT token |
| POST | `/api/doctor/status` | Cập nhật trạng thái (online/busy/offline) |
| POST | `/api/doctor/send` | Gửi tin nhắn relay đến user |
| POST | `/api/doctor/accept` | Nhận ca |
| POST | `/api/doctor/transfer` | Chuyển ca |
| POST | `/api/doctor/close` | Kết thúc ca |
| GET | `/api/doctor/cases` | Danh sách ca đang xử lý |

### Session & WebSocket

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/session/connect` | Tạo/kết nối session với bác sĩ |
| WS | `/ws/doctor/{doctor_id}` | WebSocket stream cho bác sĩ (ca mới, tin nhắn) |
| WS | `/ws/session/{session_id}` | WebSocket stream cho 1 session |

---

## Thêm bác sĩ mới

Kết nối vào PostgreSQL và insert:

```sql
INSERT INTO doctors (id, name, specialty, username, password_hash, is_active)
VALUES (
  gen_random_uuid(),
  'BS. Trần Thị Lan',
  'Nhi khoa',
  'doctor2',
  -- bcrypt hash của password, ví dụ dùng Python:
  -- from passlib.hash import bcrypt; bcrypt.hash("password123")
  '$2b$12$...',
  true
);
```

Hoặc dùng Python script:

```python
from passlib.hash import bcrypt
print(bcrypt.hash("your_password"))
```

---

## Cấu trúc thư mục

```
MedBot/
├── api/
│   ├── main.py              # FastAPI app + Telegram bot lifecycle
│   ├── routes/
│   │   ├── chat.py          # /api/chat, /api/chat/file, /api/doctors/online
│   │   ├── doctor.py        # /api/doctor/* + JWT auth
│   │   └── session.py       # /api/session/connect
│   └── websocket.py         # WebSocket connection manager
├── bot/
│   ├── handlers/
│   │   ├── message.py       # Xử lý tin nhắn text
│   │   ├── file.py          # Xử lý file/ảnh upload
│   │   └── callback.py      # InlineKeyboard callback (chọn bác sĩ)
│   └── relay.py             # bot.send_message wrapper
├── core/
│   ├── claude_client.py     # Anthropic API wrapper + system prompt
│   ├── rag.py               # LlamaIndex + ChromaDB retriever
│   ├── file_processor.py    # PDF/DOCX/image → text/base64
│   ├── scope_checker.py     # Regex + Claude JSON parse
│   ├── doctor_selector.py   # Redis online status matching
│   └── config.py            # Settings (pydantic-settings)
├── db/
│   ├── models.py            # SQLAlchemy: Doctor, Session, Message
│   ├── database.py          # Async engine, session factory
│   └── redis_client.py      # Doctor status cache
├── knowledge/
│   ├── medical_guidelines/  # Tài liệu y tế nguồn RAG
│   └── embed_kb.py          # Script index hoá vào ChromaDB
├── dashboard/
│   └── index.html           # Doctor Dashboard (static SPA)
├── nginx/
│   └── nginx.conf           # Reverse proxy + WebSocket support
├── scripts/
│   └── init_kb.sh           # Script index knowledge base
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Xử lý File Upload

| Loại file | Cách xử lý |
|---|---|
| PDF | PyMuPDF: extract text từng trang, max 50 trang |
| DOCX | python-docx: paragraphs + tables → plain text |
| JPG / PNG | Encode base64 → Claude vision |
| File > 20MB | Từ chối, thông báo user |

File xử lý **in-memory**, KHÔNG lưu lâu dài. File tạm bị xóa ngay sau khi extract. Chỉ `extracted_text` được lưu vào PostgreSQL.

---

## Scope Logic

Claude tự quyết định in/out-of-scope dựa trên system prompt. Ngoài ra còn có **regex fallback** để tránh false negative:

```python
OUT_OF_SCOPE_PATTERNS = [
    r"kê đơn|đơn thuốc|liều dùng|mg\s*\d|\d+\s*viên",
    r"chẩn đoán|tôi bị bệnh gì|xác nhận bệnh",
    r"phẫu thuật|mổ|can thiệp|thủ thuật",
    r"thuốc\s+\w+\s+\d",
]
```

---

## Troubleshooting

**Bot không nhận webhook:**
```bash
# Kiểm tra webhook đã set chưa
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo
```

**ChromaDB empty / RAG không hoạt động:**
```bash
docker compose run --rm embed-kb
```

**Reset database:**
```bash
docker compose down -v   # XÓA toàn bộ data
docker compose up -d --build
```

**Xem logs realtime:**
```bash
docker compose logs -f app
docker compose logs -f postgres
```
