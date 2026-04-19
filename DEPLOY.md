# MedBot — Hướng dẫn Deploy Ubuntu

## Yêu cầu hệ thống

- Ubuntu 22.04+ (hoặc 20.04)
- Docker Engine ≥ 24 + Docker Compose v2
- Nginx (cài trên host, không dùng Docker nginx)
- Domain trỏ A-record về IP server (nếu dùng SSL)

---

## 1. Cài Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker          # áp dụng ngay mà không cần logout
docker --version       # kiểm tra
```

---

## 2. Cài Nginx trên host

```bash
sudo apt update && sudo apt install -y nginx
sudo systemctl enable nginx
```

---

## 3. Kéo code về server

```bash
git clone git@github.com:tranbadat/Medbot.git /opt/medbot
cd /opt/medbot
```

---

## 4. Tạo file `.env`

```bash
cp .env.example .env
nano .env
```

Các biến bắt buộc:

```env
# Bot
TELEGRAM_TOKEN=your_telegram_bot_token

# Database
DATABASE_URL=postgresql+asyncpg://medbot:medbot123@postgres:5432/medbot
POSTGRES_USER=medbot
POSTGRES_PASSWORD=medbot123        # đổi mật khẩu mạnh hơn
POSTGRES_DB=medbot

# Redis
REDIS_URL=redis://redis:6379/0

# ChromaDB
CHROMA_HOST=chromadb
CHROMA_PORT=8000

# AI
AI_ENGINE=claude                   # hoặc openai
ANTHROPIC_API_KEY=sk-ant-...       # nếu dùng Claude
OPENAI_API_KEY=sk-...              # nếu dùng OpenAI

# Auth
JWT_SECRET=change_this_to_random_secret_32chars

# Clinic info
CLINIC_NAME=Phòng khám Đa khoa MedBot
CLINIC_ADDRESS=Số 1 Đường Đại Cồ Việt, Hà Nội
CLINIC_PHONE=02838230000
CLINIC_EMAIL=contact@medbot.vn
CLINIC_HOURS=T2-T6: 07:30-20:00 | T7: 07:30-17:00 | CN: 08:00-12:00

# Webhook — đổi thành domain hoặc IP server
WEBHOOK_BASE_URL=https://medbot.tranbadat.vn

# Zalo OA (tuỳ chọn)
ZALO_APP_ID=
ZALO_APP_SECRET=
ZALO_OA_ACCESS_TOKEN=
ZALO_OA_REFRESH_TOKEN=

# Session
SESSION_TIMEOUT_MINUTES=30
```

---

## 5. Khởi động Docker services

```bash
cd /opt/medbot
docker compose up -d --build

# Theo dõi log khởi động
docker compose logs -f app

# Kiểm tra app đã sẵn sàng
curl http://127.0.0.1:8000/health
# → {"status":"ok"}
```

> App chỉ bind `127.0.0.1:8000` — không expose ra internet, nginx trên host sẽ proxy vào.

---

## 6. Cấu hình Nginx

```bash
# Symlink file config vào sites-enabled
sudo ln -s /opt/medbot/nginx/medbot.conf /etc/nginx/sites-enabled/medbot

# Xoá default site nếu còn
sudo rm -f /etc/nginx/sites-enabled/default

# Kiểm tra cú pháp
sudo nginx -t

# Reload
sudo systemctl reload nginx
```

---

## 7. Index Knowledge Base (chạy 1 lần)

```bash
docker compose run --rm embed-kb
```

> Chạy lại mỗi khi thêm/sửa file trong `knowledge/medical_guidelines/`.

---

## 8. SSL với Let's Encrypt *(tuỳ chọn — khuyến nghị cho production)*

> Yêu cầu: domain đã trỏ A-record về IP server, port 80 mở.

```bash
sudo apt install -y certbot python3-certbot-nginx

# Cấp chứng chỉ và tự động sửa nginx config
sudo certbot --nginx -d medbot.tranbadat.vn

# Kiểm tra auto-renew
sudo certbot renew --dry-run
```

Sau bước này certbot tự thêm `listen 443 ssl` và redirect 80 → 443 vào file nginx.

Cập nhật `.env`:

```env
WEBHOOK_BASE_URL=https://medbot.tranbadat.vn
```

Restart app để webhook URL được áp dụng:

```bash
docker compose restart app
```

---

## 9. Tạo tài khoản bác sĩ demo

```bash
# Seed chạy tự động khi app khởi động (xem api/main.py _seed_demo_doctor)
# Tài khoản mặc định: doctor1 / doctor123
# Đổi mật khẩu qua admin dashboard sau khi đăng nhập lần đầu
```

---

## Lệnh thường dùng

```bash
# Xem log realtime
docker compose logs -f app

# Restart app (sau khi cập nhật code)
git pull && docker compose up -d --build app

# Restart tất cả
docker compose restart

# Dừng toàn bộ
docker compose down

# Dừng và xoá dữ liệu (cẩn thận!)
docker compose down -v

# Vào shell app container để debug
docker compose exec app bash

# Kiểm tra trạng thái các service
docker compose ps
```

---

## Cấu trúc cổng

```
Internet
   │  80/443
   ▼
Nginx (host)
   │  127.0.0.1:8000
   ▼
Docker app (FastAPI)
   ├── postgres (internal)
   ├── redis    (internal)
   └── chromadb (internal)
```

---

## Troubleshooting

**App không khởi động — lỗi DB connection:**
```bash
docker compose logs postgres   # kiểm tra postgres healthy chưa
docker compose restart app
```

**Telegram webhook không nhận được update:**
```bash
# Kiểm tra webhook đã đăng ký chưa
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo
# pending_update_count > 0 là đang nhận
```

**Nginx 502 Bad Gateway:**
```bash
curl http://127.0.0.1:8000/health   # kiểm tra app còn sống không
docker compose ps                   # kiểm tra container status
```

**Hết dung lượng disk (ChromaDB / Postgres data):**
```bash
docker system df                    # xem dung lượng Docker dùng
docker image prune -f               # xoá image cũ không dùng
```
