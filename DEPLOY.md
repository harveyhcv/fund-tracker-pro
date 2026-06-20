# 🚀 Hướng Dẫn Deploy — Quỹ Tracker Pro Bot

Bot Telegram theo dõi NAV quỹ mở Việt Nam. Deploy lên cloud miễn phí để dùng 24/7.

---

## 🎯 Lựa Chọn Deploy (Tất Cả Miễn Phí)

| Platform | Free Tier | Sleep? | Độ khó | Link |
|----------|-----------|--------|--------|------|
| **Railway** | $5 credit/tháng (~500h) | Không | ⭐ Dễ nhất | railway.app |
| **Render** | 750h/tháng | Sau 15 phút idle | ⭐ Dễ | render.com |
| **Oracle Cloud** | 2 VM mãi mãi | Không bao giờ | ⭐⭐⭐ | cloud.oracle.com |
| **Fly.io** | 3 shared VMs | Không | ⭐⭐ Trung bình | fly.io |

**Bot cần chạy liên tục** → Khuyên dùng Railway hoặc Oracle Cloud.

---

## Bước 0: Chuẩn Bị — Tạo Bot Telegram

1. Nhắn tin cho [@BotFather](https://t.me/BotFather) trên Telegram
2. Gõ `/newbot` → đặt tên → nhận **BOT_TOKEN** (dạng `1234567890:AABBcc...`)
3. Lấy Chat ID của bạn: nhắn tin cho [@userinfobot](https://t.me/userinfobot) → nhận **ADMIN_TELEGRAM_ID**

---

## Option A: Railway (Khuyên Dùng)

### 1. Push code lên GitHub
```bash
git add .
git commit -m "Add deployment files"
git push origin main
```

### 2. Tạo project Railway
1. Vào [railway.app](https://railway.app) → Login bằng GitHub
2. **New Project** → **Deploy from GitHub repo** → chọn repo này
3. Railway tự detect `railway.toml` + `Dockerfile`

### 3. Thêm Volume (lưu config.json)
1. Dashboard → project → **+ Add Volume**
2. Mount path: `/data`

### 4. Set Environment Variables
Railway dashboard → **Variables** → thêm từng dòng:
```
BOT_TOKEN          = <token từ BotFather>
ADMIN_TELEGRAM_ID  = <chat id của bạn>
MORNING_TIME       = 08:00
EVENING_TIME       = 17:30
SIGNAL_INTERVAL    = 60
```

### 5. Deploy
Click **Deploy** → đợi ~2 phút → xem logs

### 6. Khởi tạo lần đầu
Nhắn tin cho bot: `/start` → bot tự tạo `config.json` trong volume `/data`

---

## Option B: Render.com

### 1. Tạo Background Worker
1. [render.com](https://render.com) → **New** → **Background Worker**
2. Connect GitHub repo
3. **Runtime**: Docker

### 2. Environment Variables
Thêm trong Render dashboard:
```
BOT_TOKEN          = ...
ADMIN_TELEGRAM_ID  = ...
DATA_DIR           = /data
```

### 3. Persistent Disk
Render dashboard → **Disks** → Add disk:
- Mount path: `/data`
- Size: 1 GB (miễn phí)

> ⚠️ Render free tier ngủ sau 15 phút không dùng → bot sẽ miss một số báo cáo tự động.
> Nâng lên Starter ($7/tháng) để luôn online.

---

## Option C: Oracle Cloud Always Free (Vĩnh Viễn Miễn Phí)

### 1. Tạo VM
1. Đăng ký [cloud.oracle.com](https://cloud.oracle.com) → **Always Free** resources
2. **Compute** → **Create Instance** → chọn **VM.Standard.E2.1.Micro** (Always Free)
3. OS: Ubuntu 22.04

### 2. SSH vào VM và setup
```bash
# SSH vào VM
ssh ubuntu@<VM_PUBLIC_IP>

# Cài Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker

# Clone repo
git clone https://github.com/YOUR_USERNAME/fund-tracker-pro.git
cd fund-tracker-pro

# Tạo .env
cp .env.example .env
nano .env  # Điền BOT_TOKEN và ADMIN_TELEGRAM_ID

# Build và chạy
docker build -t fund-tracker-bot .
docker run -d \
  --name bot \
  --restart always \
  --env-file .env \
  -v fund-tracker-data:/data \
  fund-tracker-bot

# Xem logs
docker logs -f bot
```

### 3. Auto-start sau reboot
```bash
# Đã có --restart always nên tự động restart
# Kiểm tra:
docker ps
```

---

## 🧪 Kiểm Tra Bot Đang Chạy

Sau khi deploy, test các lệnh này:

```
/start          → Xem menu + kiểm tra đã nhận diện bạn chưa
/getid          → Lấy Chat ID của bạn
/register Tên   → Đăng ký (nếu chưa có trong config)
/nav            → Test fetch NAV (thành công = bot đang kết nối fmarket)
/signal         → Xem tín hiệu kỹ thuật
/funds          → Danh sách quỹ có thể theo dõi
/watch TCBF     → Thêm quỹ vào danh mục
/admin users    → (admin only) Xem tất cả users
```

---

## 👥 Chia Sẻ Với Bạn Bè

1. Gửi link bot cho bạn bè: `t.me/TEN_BOT_CUA_BAN`
2. Bạn bè gõ `/start` → hướng dẫn hiện ra
3. Gõ `/register Tên Bạn` → tự đăng ký
4. Dùng `/funds` để xem quỹ, `/watch` để chọn quỹ theo dõi
5. Từ hôm sau sẽ tự động nhận báo cáo 08:00 và 17:30

**Bạn (admin) quản lý:**
```
/admin users                    → xem danh sách users
/admin kick 123456789           → xóa user
/admin broadcast Tin nhắn       → gửi thông báo tới tất cả
```

---

## 🔧 Update Bot

```bash
# Railway/Render: push code lên GitHub → tự động redeploy

# Oracle Cloud / Docker:
git pull
docker build -t fund-tracker-bot .
docker stop bot && docker rm bot
docker run -d --name bot --restart always --env-file .env -v fund-tracker-data:/data fund-tracker-bot
```

---

## 🆘 Troubleshooting

| Vấn đề | Nguyên nhân | Cách fix |
|--------|-------------|----------|
| Bot không phản hồi | BOT_TOKEN sai | Kiểm tra lại token từ BotFather |
| NAV = 0 / Không có dữ liệu | Quỹ TCBS cần token | Xem phần TCBS Auth bên dưới |
| Bot crash ngay lúc start | Thiếu BOT_TOKEN env | Đảm bảo đã set environment variables |
| `/admin` không hoạt động | ADMIN_TELEGRAM_ID sai | Dùng `/getid` để lấy ID đúng |

### TCBS Auth (cho quỹ TCFF, TCGF)
Các quỹ TCBS cần token xác thực. Bot sẽ tự cảnh báo khi token hết hạn.
Cách lấy token: chạy web dashboard (`server.py`) → Cài Đặt → TCBS Auth.
Sau khi có token, cập nhật `config.json` trong volume:
```json
{
  "tcbs_token": "eyJ..."
}
```
