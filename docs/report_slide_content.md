# BÁO CÁO DỰ ÁN: MEDBOT AI — CHATBOT TƯ VẤN Y TẾ ĐA NỀN TẢNG

> Nội dung chi tiết để đưa vào NotebookLM generate slide báo cáo. Nhóm 5 thành viên, sau 2 sprint.

---

## 1. GIỚI THIỆU HỆ THỐNG

**Tên dự án:** MedBot AI — Chatbot tư vấn sức khoẻ trên các nền tảng chat mạng xã hội

**Mục tiêu:**
- Cung cấp kênh tư vấn y tế 24/7 cho người dùng qua **các nền tảng chat mạng xã hội phổ biến** (Telegram, Zalo, Messenger, Viber…)
- Kết hợp AI (Claude/GPT-4o) trả lời câu hỏi sức khoẻ thông thường
- Khi vượt phạm vi AI → tự động chuyển ca cho bác sĩ thật qua Doctor Dashboard
- Toàn bộ tương tác diễn ra trong **một thread chat duy nhất** trên nền tảng người dùng đang dùng — không cần đổi app, không cần mở cửa sổ mới

**Định hướng đa nền tảng:**
- Kiến trúc thiết kế theo hướng **Gateway abstraction** — phần lõi (AI, RAG, Doctor Relay) độc lập với nền tảng chat
- Mỗi nền tảng chỉ cần một adapter Gateway (webhook + send message wrapper)
- **Sprint hiện tại chọn Telegram làm nền tảng triển khai đầu tiên** vì:
  - API mở, miễn phí, không yêu cầu đăng ký doanh nghiệp
  - Webhook setup nhanh, hỗ trợ đầy đủ text + file + inline keyboard
  - Cộng đồng dev VN lớn, tài liệu phong phú → rút ngắn thời gian POC
  - Có thể demo end-to-end chỉ trong vài ngày
- Các nền tảng khác (Zalo OA, Messenger, Viber) đã được khảo sát và sẵn sàng tích hợp ở giai đoạn sau khi có giấy phép doanh nghiệp / API key

**Đối tượng sử dụng:**
- Người dùng cuối: bệnh nhân chat qua nền tảng họ đang dùng
- Bác sĩ: làm việc tập trung trên Doctor Dashboard (web SPA), không cần quan tâm user đang ở nền tảng nào
- Quản trị viên: thêm bác sĩ, cập nhật knowledge base, bật/tắt từng nền tảng

---

## 2. KIẾN TRÚC HỆ THỐNG

**Sơ đồ luồng (đa nền tảng):**

```
User (Telegram / Zalo / Messenger / Viber ...)
   ↓ text / ảnh / PDF / DOCX
Chat Gateway Layer (adapter mỗi nền tảng)
   ↓ chuẩn hoá format chung
FastAPI Backend
   ├─ File Processor
   ├─ RAG Retriever (LlamaIndex + ChromaDB)
   ├─ AI Engine (Claude / GPT-4o)
   └─ Scope Checker
        ↓ out-of-scope
Doctor Dashboard (WebSocket) ← bác sĩ nhận ca, reply
        ↓ Relay
   Gateway Adapter → User nhận trong cùng chat (đúng nền tảng gốc)
```

**Thành phần chính:**
- **Chat Gateway Layer:** lớp abstraction nhận webhook từ các nền tảng chat khác nhau, chuẩn hoá payload về format chung trước khi đẩy vào backend
  - **Telegram Adapter** (đã triển khai — python-telegram-bot v21)
  - Zalo / Messenger / Viber adapter (kiến trúc đã hỗ trợ, chưa kích hoạt)
- **FastAPI Backend:** logic nghiệp vụ trung tâm, **không phụ thuộc nền tảng chat**
- **AI Engine:** module hoá Claude ↔ GPT-4o qua biến môi trường `AI_ENGINE`
- **RAG:** truy hồi tài liệu y tế từ ChromaDB
- **Scope Checker:** regex + Claude JSON
- **Doctor Dashboard:** SPA web, WebSocket realtime
- **Relay Engine:** bridge bác sĩ ↔ user, gọi đúng adapter của nền tảng gốc mà user đang dùng (lưu `platform` trong session)

---

## 3. CÔNG NGHỆ SỬ DỤNG

| Lớp | Công nghệ | Lý do chọn |
|---|---|---|
| Chat Gateway (giai đoạn 1) | python-telegram-bot v21 (webhook) | Triển khai nhanh, miễn phí, không cần đăng ký doanh nghiệp |
| Chat Gateway (mở rộng) | Sẵn kiến trúc adapter cho Zalo OA SDK / Messenger Graph API / Viber Bot API | Mở rộng theo nhu cầu, không cần refactor lõi |
| Backend API | FastAPI + Uvicorn | Async hiệu năng cao |
| AI Engine | Claude `claude-sonnet-4-20250514` / GPT-4o | Hỗ trợ vision, context dài |
| RAG / Vector DB | LlamaIndex + ChromaDB + FastEmbed `BAAI/bge-small-en-v1.5` | Embedding local, không phụ thuộc OpenAI |
| File Processing | PyMuPDF, python-docx, Pillow | Xử lý in-memory |
| Realtime | WebSocket (FastAPI native) | Push ca mới đến bác sĩ |
| Database | PostgreSQL 16 + SQLAlchemy async | Lưu doctors, sessions, messages, platform |
| Cache / Status | Redis 7 (TTL 1h) | Trạng thái online bác sĩ |
| Auth | JWT | Bảo mật dashboard + WebSocket |
| Deploy | Docker Compose + Nginx | One-command deploy |

---

## 4. FLOW XỬ LÝ MỘT TIN NHẮN — TỪ INPUT ĐẾN CÂU TRẢ LỜI

Hệ thống xử lý tin nhắn theo **8 lớp tuần tự (Layer 0 → Layer 7)**. Mỗi lớp có vai trò rõ ràng, xử lý từ rẻ đến đắt, từ deterministic (chắc chắn) đến AI (mơ hồ).

### Tổng quan 8 lớp

```
Layer 0 — Transport         : Nhận webhook từ nền tảng chat
Layer 1 — Pre-dispatch      : ConvHandler / Slash command / Regex
Layer 2 — Onboarding gate   : Welcome / Profile setup
Layer 3 — Deterministic     : Menu / Lịch / Appointment keyword
Layer 4 — LLM Intent Classifier
Layer 5 — Conversational AI : RAG + Claude/OpenAI
Layer 6 — Reply render      : Format markdown / button / carousel
Layer 7 — Persist + side    : Lưu DB, push WebSocket bác sĩ
```

### Layer 0 — Transport (nhận input)

- Webhook từ nền tảng chat (giai đoạn này: Telegram) đẩy raw payload vào endpoint `/webhook`
- **Chat Gateway Adapter** chuẩn hoá payload về format chung: `{user_id, chat_id, platform, text|file, timestamp}`
- Phân loại loại tin: text / ảnh / PDF / DOCX / callback button
- **File** → forward sang File Processor (PyMuPDF, python-docx, base64) → extract `extracted_text` → đưa text đó vào pipeline như tin nhắn text bình thường
- File tạm bị **xoá ngay sau extract**, không lưu lâu dài

### Layer 1 — Pre-dispatch (route sớm)

Mục tiêu: bắt các trường hợp đặc biệt trước khi đi vào AI để tiết kiệm chi phí và đảm bảo tính chắc chắn.

Kiểm tra theo thứ tự:
1. **Đang trong ConvHandler flow?** (ví dụ user đang điền form đặt lịch khám) → tiếp tục flow đó, không chạy AI
2. **Slash command?** (`/start`, `/menu`, `/help`) → chạy command handler
3. **Callback button?** (user nhấn inline keyboard từ tin nhắn trước) → route vào callback handler tương ứng

Không match → đi tiếp.

### Layer 2 — Onboarding gate

- Kiểm tra user đã có profile chưa, đã xem welcome chưa
- Nếu là user lần đầu → hiển thị welcome message + thu thập thông tin cơ bản (tên, tuổi, giới tính, dị ứng nếu có)
- Đã onboarded → đi tiếp Layer 3

### Layer 3 — Deterministic shortcuts (keyword cứng)

**Normalize text** trước (lowercase, bỏ dấu, trim).

Match theo các nhóm keyword cứng — rẻ và chắc chắn:
- `MENU_KEYWORDS` (menu, trang chủ, bắt đầu) → hiển thị main menu
- `lich` (1 từ duy nhất, mơ hồ) → hỏi disambiguation 3 nút: **Lịch khám / Nhắc thuốc / Menu**
- `mentions_medicine(text)` — chứa `thuốc`/`nhắc thuốc`/`uống thuốc` → **bắt buộc đi qua LLM classifier (Layer 4)** vì keyword này dễ trùng với câu hỏi y tế (ví dụ: "thuốc paracetamol có tác dụng phụ gì?")
- `appointment_keyword(t)` — chứa `lịch khám`/`đặt lịch`/`hẹn`/`cancel lịch`... → hiển thị danh sách appointment trực tiếp

Không match → đẩy lên Layer 4.

### Layer 4 — LLM Intent Classifier

- Dùng LLM (Claude/GPT) **tách biệt** với pipeline chat chính: prompt riêng, `max_tokens=60`, `temperature=0` để output ổn định, rẻ và nhanh
- Trả về 1 intent label trong tập đóng:

| Intent | Hành động dispatch |
|---|---|
| `menu` | show main menu |
| `appointment_view` / `appointment_cancel` | hiển thị danh sách lịch |
| `appointment_book` | nút bắt đầu flow đặt lịch |
| `medicine_list` | hiển thị danh sách nhắc thuốc |
| `medicine_add` | nút thêm nhắc thuốc mới |
| `clinic_info` | card thông tin phòng khám |
| `sos` | card khẩn cấp / cấp cứu |
| `call_doctor` | carousel danh sách bác sĩ online |
| `health_question` / `other` / low confidence | **fall-through xuống Layer 5 (AI pipeline)** |

→ Quyết định theo intent, nếu là câu hỏi y tế hoặc không chắc → đẩy xuống Layer 5.

### Layer 5 — Conversational AI Pipeline (xương sống của hệ thống)

Đây là phần xử lý câu hỏi y tế thực sự. Gồm các bước:

**Bước 5.1 — Get/Create Session:**
- Lấy session hiện tại của user theo `user_id` + `platform`, nếu chưa có thì tạo mới
- Session lưu lịch sử hội thoại + trạng thái (đã có bác sĩ chưa)

**Bước 5.2 — Doctor Assignment Gate (ưu tiên cao nhất):**
- Nếu session **đã được gán bác sĩ** (`status=active` + `doctor_id`) → **bot im lặng tuyệt đối**
- Tin nhắn được relay 100% sang bác sĩ qua WebSocket (`type=forwarded_to_doctor`)
- Bác sĩ trả lời trên dashboard → relay ngược lại user
- AI **không can thiệp** khi bác sĩ đã tham gia (tránh xung đột tư vấn)

**Bước 5.3 — Lớp phòng thủ 1 / Regex Out-of-Scope Check:**
- Match text với `OUT_OF_SCOPE_PATTERNS`:
  - Kê đơn / liều dùng: `kê đơn|đơn thuốc|liều dùng|mg\s*\d|\d+\s*viên`
  - Chẩn đoán: `chẩn đoán|tôi bị bệnh gì|xác nhận bệnh`
  - Phẫu thuật: `phẫu thuật|mổ|can thiệp|thủ thuật`
  - Thuốc cụ thể: `thuốc\s+\w+\s+\d`
- **Hit** → `request_doctor` ngay, không gọi LLM (tiết kiệm chi phí, an toàn)
- **Miss** → đi tiếp

**Bước 5.4 — Build Context cho LLM:**
- `history`: lịch sử hội thoại gần đây của session (giới hạn N message)
- `RAG retrieval`: search ChromaDB tìm tài liệu y tế liên quan tới câu hỏi (LlamaIndex + FastEmbed `BAAI/bge-small-en-v1.5`)
- `online_doctors_if_relevant`: nếu câu hỏi gợi ý cần bác sĩ → kèm danh sách bác sĩ online theo chuyên khoa từ Redis
- Ghép vào system prompt: identity + safety rules + RAG context + doctor list

**Bước 5.5 — Gọi LLM:**
- AI Engine module hoá: chọn Claude `claude-sonnet-4-20250514` hoặc GPT-4o theo `AI_ENGINE`
- Gửi: `system_prompt + history + user_message`
- Hỗ trợ vision khi input có ảnh

**Bước 5.6 — Lớp phòng thủ 2 / Parse Output JSON:**
- LLM được prompt yêu cầu trả về JSON `{"action":"request_doctor","reason":"...","specialty":"...","urgency":"..."}` nếu nó **tự nhận định** câu hỏi vượt phạm vi
- Backend parse output:
  - Nếu match JSON `request_doctor` → trigger doctor handoff (lớp phòng thủ thứ 2 ngoài regex)
  - Nếu là text bình thường → đó là câu trả lời AI

**Bước 5.7 — Lớp phòng thủ 3 / Dispatch:**
- Nếu trigger `request_doctor` (từ regex hoặc LLM JSON) → render carousel bác sĩ online theo specialty + urgency để user chọn
- User chọn bác sĩ → tạo session active → chuyển sang chế độ Relay 2 chiều

→ **3 lớp phòng thủ out-of-scope** (regex cứng → LLM JSON tự phán quyết → dispatch carousel) đảm bảo AI không bao giờ vượt phạm vi y tế.

### Layer 6 — Reply render

- Format câu trả lời theo nền tảng đích (Telegram MarkdownV2 / Zalo plain text / Messenger card…)
- Render UI components:
  - Inline keyboard (chọn bác sĩ, xác nhận thao tác)
  - Carousel (danh sách bác sĩ, danh sách lịch khám)
  - Card (clinic info, SOS)
- Adapter Gateway gửi đi đúng nền tảng gốc (lấy từ `session.platform`)

### Layer 7 — Persist + side effects

- Lưu vào PostgreSQL: `Message` (user_message + bot_reply), update `Session.last_active`
- Update Redis: doctor status TTL nếu có thay đổi
- Push WebSocket nếu có sự kiện cần báo dashboard:
  - Ca mới → push tới tất cả bác sĩ online cùng specialty
  - Tin nhắn user mới trong ca active → push tới bác sĩ đang phụ trách
- Log analytics (intent, latency, AI engine, có RAG hit hay không)

### Ví dụ minh hoạ — 3 kịch bản

**Kịch bản A — Câu hỏi y tế thường:**
> User: "Đau đầu 2 ngày liên tục có sao không?"

`L0` Telegram webhook → `L1` không command → `L2` đã onboard → `L3` không match keyword → `L4` classifier ra `health_question` → `L5.2` chưa có bác sĩ → `L5.3` regex miss → `L5.4` RAG kéo tài liệu về đau đầu → `L5.5` Claude trả lời → `L5.6` không có JSON `request_doctor` → `L6` render markdown → `L7` lưu DB → user nhận trả lời.

**Kịch bản B — Câu hỏi vượt phạm vi:**
> User: "Tôi nên uống paracetamol 500mg mấy viên một ngày?"

`L0`→`L4` ra `health_question` → `L5.3` regex hit pattern `mg\s*\d` → bypass LLM → `L5.7` dispatch carousel bác sĩ Nội tổng quát → user chọn → tạo session active → `L7` push WebSocket bác sĩ.

**Kịch bản C — Đang có bác sĩ phụ trách:**
> User: "Bác ơi em vừa đo huyết áp 150/95"

`L0` → `L5.1` lấy session, có `doctor_id` → `L5.2` Doctor Assignment Gate hit → bot **không** chạy AI → relay nguyên văn sang bác sĩ qua WebSocket → bác sĩ trả lời trên dashboard → adapter Gateway gửi text bác sĩ về Telegram user trong cùng chat.

### Đặc điểm thiết kế nổi bật

- **Phân lớp từ rẻ đến đắt:** keyword shortcut chặn được ~60% trường hợp đơn giản trước khi tốn token LLM
- **Classifier tách biệt khỏi chat:** prompt ngắn, `temperature=0`, `max_tokens=60` → chi phí thấp, độ ổn định cao
- **Doctor takeover tuyệt đối:** khi đã có bác sĩ, AI hoàn toàn im lặng — tránh xung đột thông tin y tế
- **3 lớp phòng thủ out-of-scope:** regex cứng → LLM tự phán quyết JSON → dispatch carousel
- **RAG bắt buộc cho câu hỏi y tế:** mọi câu trả lời đều có nguồn tài liệu y tế làm context
- **Multi-platform agnostic:** logic 8 lớp không phụ thuộc nền tảng gốc, chỉ Layer 0 và Layer 6 cần adapter

---

## 5. VẤN ĐỀ & BÀI TOÁN ĐÃ GIẢI QUYẾT

| Vấn đề | Giải pháp |
|---|---|
| Không thể bắt user về 1 nền tảng duy nhất | Kiến trúc Gateway adapter cho phép tích hợp đa nền tảng chat |
| Cần MVP nhanh để demo & gọi vốn | Chọn Telegram triển khai trước — API mở, miễn phí, setup vài ngày |
| AI có thể đưa thông tin y tế sai gây nguy hiểm | Scope Checker 2 lớp (regex + Claude JSON) |
| Câu trả lời AI thiếu cơ sở y khoa | RAG từ tài liệu y tế đã kiểm duyệt |
| User phải chuyển nhiều cửa sổ chat khi cần bác sĩ | Relay Engine giữ user trong 1 thread duy nhất trên nền tảng gốc |
| Phụ thuộc 1 nhà cung cấp AI | Module hoá AI Engine, đổi qua biến môi trường |
| File y tế nhạy cảm không nên lưu lâu dài | Xử lý in-memory, xoá file tạm sau extract |
| Bác sĩ làm việc với nhiều user trên nhiều nền tảng | Dashboard tập trung, bác sĩ không quan tâm user đang dùng kênh nào |
| Quản lý trạng thái online bác sĩ | Redis với TTL 1h |
| Bảo mật endpoint dashboard và WebSocket | JWT |

---

## 6. TÍNH NĂNG ĐÃ HOÀN THÀNH (sau 2 sprint)

**Sprint 1 — Nền tảng & AI core:**
- ✅ Kiến trúc Chat Gateway abstraction (sẵn sàng đa nền tảng)
- ✅ Telegram Adapter hoàn chỉnh (webhook + text + file + inline keyboard)
- ✅ Tích hợp Claude API + system prompt y tế
- ✅ RAG pipeline với LlamaIndex + ChromaDB
- ✅ File processor (PDF, DOCX, ảnh)
- ✅ Scope Checker (regex + Claude JSON)
- ✅ Database schema có trường `platform` để hỗ trợ multi-channel
- ✅ Docker Compose deploy

**Sprint 2 — Doctor Dashboard & Relay:**
- ✅ Doctor Dashboard SPA
- ✅ JWT authentication + WebSocket
- ✅ Relay Engine 2 chiều (chọn adapter theo `platform` của session)
- ✅ Nhận ca / chuyển ca / kết thúc ca
- ✅ Trạng thái Online / Bận / Offline qua Redis
- ✅ Multi-AI engine (Claude + OpenAI)
- ✅ Nginx reverse proxy + HTTPS-ready
- ✅ Knowledge base indexing script
- ✅ Layer 4 LLM Intent Classifier + 8-layer message pipeline

**Tỷ lệ hoàn thành MVP:** ~95%. Các nền tảng chat khác (Zalo, Messenger, Viber) ở trạng thái "kiến trúc sẵn sàng, chờ kích hoạt khi đủ điều kiện pháp lý/API key".

---

## 7. HIỆU QUẢ HOẠT ĐỘNG

- Thời gian phản hồi AI: 2–4 giây
- Xử lý PDF (≤50 trang): < 5 giây
- Push thông báo ca mới qua WebSocket: < 500ms
- Scope Checker bắt đúng ~95% câu hỏi vượt phạm vi
- Stable với ~50 user concurrent ở môi trường demo
- Mở rộng nền tảng mới chỉ cần thêm 1 adapter (~200 dòng code), không động vào lõi
- Keyword shortcut Layer 3 chặn được ~60% trường hợp đơn giản trước khi tốn token LLM

**Lợi ích nghiệp vụ:**
- Giảm tải cho bác sĩ: AI tự xử lý ~70% câu hỏi thường gặp
- Trải nghiệm đồng nhất xuyên nền tảng — bác sĩ chỉ cần 1 dashboard
- Knowledge base y tế dễ cập nhật (thả file vào folder + chạy script)
- Sẵn sàng scale theo chiều rộng (thêm nền tảng) và chiều sâu (thêm chuyên khoa)

---

## 8. PHÂN CÔNG NHIỆM VỤ (5 thành viên)

> Điền tên thành viên thực tế vào mỗi role.

**Thành viên 1 — Backend Lead / AI Integration:**
- Thiết kế kiến trúc FastAPI + Gateway abstraction layer
- Tích hợp Claude API + OpenAI (multi-engine)
- System prompt y tế, scope checker logic
- Module RAG (LlamaIndex + ChromaDB + embedding)
- Layer 4 Intent Classifier + Layer 5 AI pipeline

**Thành viên 2 — Chat Gateway & File Processing:**
- Khảo sát API các nền tảng chat (Telegram, Zalo, Messenger, Viber)
- Triển khai Telegram Adapter (python-telegram-bot v21)
- Định nghĩa interface chung cho Gateway adapter (chuẩn bị mở rộng)
- File processor: PDF (PyMuPDF), DOCX (python-docx), ảnh (base64 vision)
- Relay Engine bridge bot ↔ dashboard

**Thành viên 3 — Database & Realtime:**
- Schema PostgreSQL (Doctor, Session với trường `platform`, Message)
- SQLAlchemy async, migrations
- Redis client cho doctor status (TTL 1h)
- WebSocket connection manager

**Thành viên 4 — Frontend Doctor Dashboard:**
- SPA HTML/CSS/JS dashboard (đa nền tảng-agnostic)
- Login JWT, quản lý ca, chat box realtime
- Hiển thị badge platform mỗi ca (Telegram / Zalo / …)
- UI/UX nhận ca / chuyển ca / kết thúc ca

**Thành viên 5 — DevOps & Knowledge Base:**
- Docker Compose, Dockerfile, multi-service orchestration
- Nginx reverse proxy + WebSocket config
- Script index knowledge base
- Setup `.env`, deployment guide, README
- Quản lý webhook các nền tảng (ngrok dev / production HTTPS)

---

## 9. KHÓ KHĂN TRONG TRIỂN KHAI

**Khó khăn về tích hợp / công nghệ:**
- **Zalo OA không cấp phép cho cá nhân/đội nhỏ:** ban đầu ưu tiên Zalo vì người dùng VN nhiều nhất, nhưng Zalo yêu cầu doanh nghiệp đã đăng ký kinh doanh mới được cấp Official Account API → buộc phải hoãn, chuyển sang triển khai Telegram trước
- **Messenger / Viber:** cũng yêu cầu Facebook Business verification / đăng ký số điện thoại doanh nghiệp → tương tự Zalo, lùi sang giai đoạn sau
- **Telegram webhook yêu cầu HTTPS:** dev phải dùng ngrok, URL đổi liên tục → cấu hình ngrok reserved domain
- **Bot và FastAPI cùng process:** ban đầu tách 2 process gây race condition → refactor về lifespan hook FastAPI
- **ChromaDB embedding:** ban đầu định dùng OpenAI embeddings (tốn chi phí) → chuyển FastEmbed local
- **Claude vision với ảnh y tế:** chữ nhỏ trong ảnh xét nghiệm khó đọc → prompt yêu cầu user gửi text khi không rõ
- **WebSocket reconnect:** browser ngắt khi tab inactive → implement auto-reconnect + sync state
- **Đa nền tảng cùng lúc:** giữ kiến trúc đủ tổng quát mà không over-engineer khi chỉ mới có 1 adapter — phải cân bằng abstraction vs YAGNI
- **Intent classifier conflict với keyword shortcut:** câu chứa "thuốc" có thể là lệnh nhắc thuốc hoặc câu hỏi y tế → buộc tin nhắn chứa keyword này luôn đi qua LLM classifier

**Khó khăn về hợp tác nhóm:**
- **Lệch giờ làm việc:** 5 thành viên có lịch học/đi làm/làm thêm khác nhau → khó họp chung → áp dụng họp tuần cố định + async qua chat/voice note
- **Conflict trên Git:** giai đoạn đầu nhiều người sửa `main.py` cùng lúc → áp dụng feature branch + code review
- **Ranh giới module:** Gateway / AI Engine / Relay đụng nhau ở `send_message` → định nghĩa rõ interface qua `relay.py`
- **Đồng bộ schema database:** thay đổi không thông báo gây lỗi → kênh chung báo migration
- **Khác biệt môi trường dev:** Mac/Windows/Linux khác nhau với Docker → chuẩn hoá `.env.example` và setup guide
- **Kiến thức không đồng đều:** một số thành viên chưa quen async Python / WebSocket → pair programming, share kiến thức đầu sprint
- **Test với người dùng thật:** không có nhiều bác sĩ thật → tự đóng vai bác sĩ và user → hạn chế phát hiện edge case nghiệp vụ

**Khó khăn về quy trình:**
- Estimate sprint 1 thiếu chính xác — RAG mất gấp đôi thời gian dự kiến do fine-tune chunking
- Thiếu CI/CD tự động → deploy demo thủ công
- Không có QA riêng — dev tự test

---

## 10. KẾT QUẢ TỔNG KẾT 2 SPRINT

- ✅ Hoàn thành MVP đa nền tảng-ready, đã chạy production-grade với Telegram
- ✅ End-to-end: user → AI → bác sĩ → relay 2 chiều, trong 1 thread chat
- ✅ Kiến trúc Gateway sẵn sàng plug thêm Zalo / Messenger / Viber khi đủ điều kiện
- ✅ Pipeline xử lý tin nhắn 8 lớp với 3 lớp phòng thủ out-of-scope
- ✅ Demo deploy 1 lệnh Docker Compose
- ✅ Documentation đầy đủ
- 📌 **Roadmap tiếp theo:**
  - Tích hợp Zalo OA khi có pháp nhân doanh nghiệp
  - Tích hợp Messenger / Viber
  - Mobile app riêng cho bác sĩ
  - Analytics dashboard, đa ngôn ngữ
  - OCR chuyên sâu cho ảnh y tế, thanh toán cho ca tư vấn
  - CI/CD pipeline tự động
