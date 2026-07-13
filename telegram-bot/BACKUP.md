# GOV-002 — Backup & Restore

## Cách hoạt động

- `scripts/backup_db.py --backup` chạy `pg_dump -F c` (custom format, nén sẵn), lưu vào
  `$DATA_DIR/backups/ftp_backup_<timestamp>.dump` — `DATA_DIR` là Railway persistent volume
  (mặc định `/data`, đã dùng chung với `config.json`/`state.json`).
- `bot.py` chạy job này tự động **hàng ngày lúc 03:30** (`job_backup_db`, xem `main()`).
- Retention: giữ tối đa 14 bản gần nhất (~2 tuần), luôn giữ ít nhất 1 bản bất kể tuổi
  (không bao giờ xoá sạch nếu có lỗi cấu hình ngày giờ).
- Nếu backup thất bại → bot gửi cảnh báo Telegram cho admin (`admin_telegram_id`).

## Giới hạn cần biết

Backup nằm **cùng Railway volume** với DB service (không phải S3/nơi khác). Nếu volume bị
xoá/hỏng hoàn toàn thì backup cũng mất theo. Đây là lựa chọn đơn giản nhất không cần thêm
credentials/service ngoài — nếu cần an toàn hơn, nâng cấp bằng cách thêm bước upload
`ftp_backup_*.dump` lên S3-compatible storage (Cloudflare R2, Backblaze B2...) sau khi tạo.

## Restore — quy trình

**⚠️ Đây là thao tác phá huỷ — restore sẽ GHI ĐÈ toàn bộ dữ liệu hiện tại trong DB đích.**
Luôn restore vào 1 DB test/staging trước, không bao giờ chạy thẳng lên production DB đang
phục vụ user mà không có kế hoạch downtime + xác nhận từ Harvey.

```bash
# 1. Liệt kê backup hiện có (chạy trên Railway hoặc local có DATA_DIR/DATABASE_URL)
railway run python scripts/backup_db.py --list

# 2. Dry-run trước (không --confirm) — chỉ in ra sẽ làm gì
railway run python scripts/backup_db.py --restore ftp_backup_20260713_033000.dump

# 3. Restore thật (CHỈ khi đã chắc chắn, tốt nhất trên DB test trước)
railway run python scripts/backup_db.py --restore ftp_backup_20260713_033000.dump --confirm
```

Restore dùng `pg_restore --clean --if-exists` — xoá object cũ trước khi tạo lại từ backup
(an toàn khi restore vào DB đã có schema cũ/khác).

## Test đã chạy (2026-07-13, session này)

- Retention logic (`_prune`) test bằng file giả lập timestamp cũ/mới — xác nhận giữ đúng
  1 bản mới nhất khi các bản khác quá 14 ngày, không xoá nếu chỉ còn 1 file.
- `cmd_restore` dry-run (không `--confirm`) — xác nhận không đụng file/DB, chỉ in cảnh báo.
- **CHƯA test `--backup`/`--confirm` restore thật** với `pg_dump`/`pg_restore` thật vì không
  có `DATABASE_URL` trong môi trường agent. Cần chạy tay 1 lần trên Railway:
  1. `railway run python scripts/backup_db.py --backup` — xác nhận file `.dump` được tạo,
     kiểm tra size hợp lý (không phải 0 byte).
  2. Restore thử vào 1 Postgres service TEST riêng (tạo tạm trên Railway, không phải service
     production) để xác nhận `pg_restore` chạy đúng, dữ liệu khớp — rồi xoá service test đó.
- Dockerfile: thêm `postgresql-client` (cho `pg_dump`/`pg_restore` có sẵn trong image) —
  **bug tìm thấy khi làm task này**: `.dockerignore` trước đó có dòng `scripts/` loại bỏ toàn
  bộ thư mục `scripts/` khỏi Docker build context, nghĩa là image production KHÔNG HỀ có
  `scripts/t2_arima.py`/`t2_xgboost.py`/`t2_ensemble.py` — mọi `_run_t2_script()` gọi từ
  `bot.py` (dự báo T+2 hàng ngày, retrain Chủ nhật, reweight 30 ngày) đã luôn fail âm thầm
  trên Railway kể từ khi các job đó được thêm (chỉ hoạt động khi test local, `_run_t2_script`
  nuốt lỗi + chỉ log, không crash bot nên không ai để ý). Đã sửa `.dockerignore` để copy
  `scripts/` (trừ `scripts/models/` — model file gitignored, tạo lại bằng `--train`).
