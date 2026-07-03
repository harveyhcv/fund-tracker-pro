# Plan: Scale Fund Tracker Pro Bot cho vài nghìn user (public launch)

> Tạo: 2026-07-03. Trạng thái: DRAFT — chờ Harvey duyệt trước khi code.

## ⚠️ Blocker ngoài code (làm trước tiên)

- **Railway hiện đang ở "Limited Trial"** — không đủ để chạy bot 24/7 ở quy mô public.
  → Harvey cần nâng lên **Hobby ($5/mo) hoặc Pro** trên Railway Dashboard trước khi
    Giai đoạn 2 (webhook) đi vào production, vì webhook cần 1 public URL luôn sống.
  → Long-polling (hiện tại) cũng cần bot luôn chạy — Limited Trial dễ bị sleep/kill giữa chừng.

## Bối cảnh hiện tại (đã audit 2026-07-03)

- `profiles` (users) lưu trong `telegram-bot/config.json` — 1 file JSON, ghi đè toàn bộ mỗi lần đổi.
- Railway volume `/data` **không persistent trước đây** → users bị mất khi redeploy (đã fix bằng cách gắn Worker Volume — cần Harvey xác nhận mount path `/data` đã đúng).
- Bot dùng **long-polling** Telegram (`command_handler` chạy trong 1 thread, xử lý tuần tự).
- Đã có sẵn bảng PostgreSQL `users`, `portfolios`, `holdings`, `transactions`, `capital_events`,
  `dca_schedules` (schema đầy đủ, mã hoá field nhạy cảm bằng `*_enc`) — **nhưng chưa được dùng**.
  Code thực tế đang query bảng phẳng khác: `user_ccq_trades`, `user_gold_trades` (không mã hoá,
  không chuẩn hoá theo user_id/portfolio_id).
- Gửi báo cáo sáng/chiều: vòng lặp `for profile in profiles: tg_send(...)` tuần tự — Telegram
  giới hạn ~30 msg/s toàn cục.
- Không có rate limiting cho `/register`, `/research`, `/admin`.

## Giai đoạn 1 — Data foundation (users → PostgreSQL)

**Mục tiêu**: `config.json` chỉ còn giữ bot_token, admin_id, schedule, funds catalog.
Toàn bộ **user/profile** chuyển hẳn sang bảng `users` đã có sẵn.

**Việc cần làm**:
1. Viết migration script: đọc `profiles` hiện tại trong `config.json` → insert vào bảng `users`
   (telegram_id, display_name_enc, is_admin, is_active). Chạy 1 lần, có `--dry-run`.
2. Sửa `find_profile_by_chat()`, `/register`, `/admin users`, `/admin kick`, `/admin broadcast`
   trong `bot.py` → đọc/ghi bảng `users` qua `db.py` thay vì `config.get("profiles")`.
3. `watched_funds` mỗi user: thêm cột hoặc bảng phụ `user_watched_funds` (vì hiện đang là field
   tự do trong JSON profile, chưa có trong schema `users`).
4. Giữ `_ADMIN_PROFILE_SEED` logic (reconcile Harvey) nhưng target bảng `users` thay vì JSON.
5. Test: `/register`, `/getid`, `/portfolio`, `/admin users` với user thật (Harvey + Khoa) —
   xác nhận không mất dữ liệu qua redeploy.
6. Sau khi ổn định ≥3 ngày, xoá field `profiles` khỏi `config.json` schema.

**Rủi ro**: nếu migration sai, mất user hiện có (chỉ có Harvey — rủi ro thấp lúc này, nhưng
sẽ không còn thấp nữa 1 khi đã public).

**Không đổi hành vi user** — API/lệnh Telegram giữ nguyên, chỉ đổi nơi lưu trữ.

## Giai đoạn 2 — Webhook thay long-polling

**Mục tiêu**: bot nhận update qua HTTPS webhook (Telegram → Railway `miniapp_server`)
thay vì poll liên tục — giảm tải, scale tốt hơn, tận dụng HTTP server đã có sẵn.

**Việc cần làm**:
1. Thêm route `POST /telegram/webhook` vào `miniapp_server.py` (đã có `HTTPServer` chạy sẵn).
2. Gọi Telegram API `setWebhook` với URL Railway (`https://worker-production-daa4.up.railway.app/telegram/webhook`)
   khi bot khởi động (thay vì long-polling loop).
3. Xử lý update trong webhook handler — tái dùng logic hiện có trong `command_handler`,
   tách phần "parse + dispatch" ra hàm dùng chung.
4. Thêm secret token xác thực webhook (Telegram hỗ trợ `secret_token` header) — tránh giả mạo request.
5. Rollback plan: giữ long-polling code, chỉ tắt bằng flag ENV nếu webhook có vấn đề.

**Phụ thuộc**: cần Railway ở Hobby/Pro tier (đã nêu ở Blocker) để URL luôn ổn định.

## Giai đoạn 3 — Batch/async gửi tin nhắn

**Mục tiêu**: job sáng/chiều không block hàng phút khi gửi cho hàng nghìn user.

**Việc cần làm**:
1. Đổi vòng lặp `tg_send` tuần tự → dùng `concurrent.futures.ThreadPoolExecutor` (đơn giản,
   không cần rewrite toàn bộ sang asyncio) với concurrency giới hạn (~20 luồng) để tôn trọng
   Telegram rate limit (~30 msg/s global).
2. Bắt lỗi từng user riêng (vd: user block bot → `403 Forbidden`) — không để 1 lỗi làm hỏng
   cả batch; đánh dấu `is_active=false` trong DB nếu user block bot 3 lần liên tiếp.
3. Theo dõi thời gian chạy job qua log — cảnh báo nếu job sáng/chiều chạy quá 5 phút.

## Giai đoạn 4 — Rate limit & abuse protection

**Mục tiêu**: bot public dễ bị spam `/register` ảo, `/research` liên tục gây tốn API quota
(TCBS/fmarket) hoặc DB load.

**Việc cần làm**:
1. `/register`: thêm cooldown giữa các lần gọi `/register`, `/research`, `/nav` (vd: 1 lệnh/5s/user)
   bằng in-memory dict — key theo chat_id, đơn giản, đủ dùng ở quy mô nghìn user single-instance.
2. Giới hạn broadcast/admin command chỉ admin — đã có, giữ nguyên.
3. Cân nhắc CAPTCHA nhẹ qua Telegram (nút inline "Tôi không phải bot") nếu spam bot tràn vào.

## Thứ tự thực hiện & session split

Vì đây là thay đổi nhiều phiên, sẽ tách thành các commit nhỏ, mỗi giai đoạn deploy + test
riêng trước khi sang giai đoạn tiếp — **không gộp 4 giai đoạn vào 1 lần deploy** để dễ rollback.

1. ✅ Plan này (đang chờ duyệt)
2. Giai đoạn 1 — implement + deploy + test riêng
3. Giai đoạn 2 — implement + deploy + test riêng (sau khi Railway tier đã nâng cấp)
4. Giai đoạn 3
5. Giai đoạn 4
