# Contingency Plan — Railway → VPS + Coolify

> Không thực hiện ngay. Đây là kế hoạch DỰ PHÒNG, chỉ triển khai khi có quyết định
> rõ ràng từ Harvey (theo đúng quy trình release: staging → xác nhận → mới lên public).

## Khi nào cân nhắc chuyển

- Chi phí Railway vượt ngưỡng chấp nhận được so với doanh thu thật (hiện tại = 0,
  đang test) — hoặc khi app đã có doanh thu ổn định để tự trả tiền hạ tầng.
- Lại gặp giới hạn platform (dung lượng, RAM, số service) mà trả thêm tiền Railway
  không còn hợp lý so với tự quản VPS.
- Cần tính năng VPS mới có (full root access, cron ngoài app, tuning Postgres sâu...).

## Vì sao khó "chuyển êm" — ràng buộc kỹ thuật cần biết trước

1. **Bot dùng Telegram long-polling** — chỉ 1 tiến trình được phép `getUpdates()` với
   1 bot token tại 1 thời điểm. KHÔNG thể chạy song song bản Railway + bản VPS cùng
   token để test "chạy thử không ảnh hưởng" — Telegram sẽ tự chặn 1 trong 2.
2. **Dữ liệu dùng chung 1 Postgres** — không thể "chạy thử" VPS với dữ liệu thật mà
   không có nguy cơ lệch dữ liệu giữa 2 nơi nếu cả 2 cùng ghi.
3. Vì 2 ràng buộc trên, đây bắt buộc là 1 **cutover có thời gian ngừng ngắn** (vài
   phút–15 phút), không phải zero-downtime blue-green thông thường.

## Giai đoạn 1 — Chuẩn bị (làm trước, KHÔNG ảnh hưởng Railway đang chạy)

- [ ] Chọn nhà cung cấp VPS (Vietnix/TinoHost trong nước, hoặc Hetzner/DigitalOcean
      quốc tế) — cấu hình tối thiểu 1-2GB RAM, 20-30GB SSD.
- [ ] Cài Coolify lên VPS (1 dòng lệnh, độc lập hoàn toàn với Railway).
- [ ] Tạo Postgres MỚI trong Coolify (dữ liệu rỗng, chỉ để test schema).
- [ ] Deploy app (`telegram-bot/`) lên Coolify từ CÙNG repo GitHub, trỏ vào Postgres
      MỚI này bằng `DATABASE_URL` riêng — dùng **bot token TEST khác** (tạo qua
      @BotFather `/newbot`) để không đụng bot thật đang chạy Railway.
- [ ] Restore 1 bản backup gần nhất (`scripts/backup_db.py --restore`) vào Postgres
      Coolify — verify dữ liệu, verify Mini App/API chạy đúng, verify SePay
      webhook giả lập, verify job schedule chạy đúng giờ VN.
- [ ] Đăng ký domain thật cho VPS (Coolify tự cấp SSL Let's Encrypt) — tránh phụ
      thuộc IP, để sau này đổi hạ tầng khác chỉ cần đổi DNS.

→ Toàn bộ giai đoạn này **không rủi ro gì cho bản Railway đang chạy thật** — chạy
song song, xoá bỏ được bất cứ lúc nào nếu quyết định không chuyển nữa.

## Giai đoạn 2 — Cutover (CẦN 1 cửa sổ ngừng ngắn, làm giờ ít người dùng)

1. Backup lần cuối từ Railway Postgres ngay trước giờ cutover (`--backup`).
2. Dừng hẳn worker Railway (dừng long-polling, dừng schedule jobs) — **đây là lúc
   bot thật sự offline**, tính từ đây.
3. Restore bản backup cuối cùng vào Postgres Coolify (ghi đè bản test).
4. Đổi config Coolify app: dùng **bot token THẬT** (token production, không phải
   token test ở Giai đoạn 1) + `DATABASE_URL` trỏ Postgres Coolius mới.
5. Cập nhật các endpoint bên ngoài đang trỏ về domain Railway cũ:
   - SePay dashboard → webhook URL mới
   - `@BotFather` → `/setdomain` cho Telegram Login Widget → domain VPS mới
   - Bot menu button / Mini App URL → domain VPS mới
6. Start app trên Coolify — verify `/health`, verify Telegram bot phản hồi, verify
   1 giao dịch SePay thật (số tiền nhỏ) để chắc webhook hoạt động.
7. Theo dõi sát 24-48 giờ đầu trước khi coi là ổn định.

**Ước tính thời gian ngừng thực tế nếu diễn tập kỹ trước**: 15-30 phút.

## Giai đoạn 3 — Rollback (nếu VPS có vấn đề)

- **Không xoá project Railway** ít nhất 2 tuần sau cutover — chỉ dừng service, giữ
  nguyên để có thể bật lại trong vài phút nếu VPS gặp sự cố nặng.
- Giữ ít nhất 3 bản backup gần cutover tải về máy local (ngoài Railway/VPS) làm
  lưới an toàn cuối cùng.
- Nếu phải rollback: bật lại worker Railway, restore bản backup gần cutover nhất
  vào Postgres Railway (chấp nhận mất đúng khoảng dữ liệu từ lúc cutover tới lúc
  phát hiện sự cố).

## Việc KHÔNG được làm khi thực hiện

- Không xoá Postgres/volume Railway trước khi VPS đã ổn định ≥2 tuần.
- Không đổi `DATABASE_URL`/domain production mà chưa test đủ ở Giai đoạn 1.
- Không cutover ngoài giờ đã báo trước với Harvey — đúng theo GOV quy trình release
  hiện tại (staging → xác nhận → public), cutover hạ tầng còn rủi ro hơn 1 lần
  deploy code bình thường nên càng cần xác nhận rõ ràng trước khi bấm nút.
