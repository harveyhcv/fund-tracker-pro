# backups/ — KHÔNG commit lên git (xem .gitignore)

Folder này chứa dữ liệu nhạy cảm (PII, lịch sử giao dịch, thanh toán) — chỉ tồn
tại local, không bao giờ push lên GitHub hay bất kỳ remote nào.

## Nội dung

### `v1.0-code-snapshot/`
Snapshot mã nguồn tại tag `v1.0` (commit `1bd0f3a3`, 2026-07-12), lấy bằng
`git archive v1.0`. Mục đích: audit sau này — có thể xem/diff lại chính xác
code đang chạy ở thời điểm v1.0 mà không cần đào lại git history.

Phục hồi lại thành 1 repo riêng nếu cần chạy thử:
```bash
cd backups/v1.0-code-snapshot
git init && git add -A && git commit -m "v1.0 restored snapshot"
```

### `v1.0-data-snapshot/`
Snapshot TOÀN BỘ dữ liệu Postgres (mọi bảng trong schema `public`, export JSON,
đọc-only) tại thời điểm chuyển từ v1.0 sang v1.1 (2026-07-13). Đây là bản chụp
1 lần phục vụ audit cutover, KHÔNG phải cơ chế backup định kỳ.
`_manifest.json` ghi lại thời điểm chụp + số dòng mỗi bảng.

### `db/` (tự động tạo bởi `scripts/backup_db.py`, GOV-002)
Backup định kỳ hàng ngày (03:30, `job_backup_db()` trong `bot.py`), format
`pg_dump -F c` (custom, nén + hỗ trợ `pg_restore` chọn lọc bảng). Giữ 14 bản
gần nhất, luôn giữ ít nhất 1 bản bất kể tuổi.

Trên Railway, thư mục thật là `DATA_DIR/backups` (= `/data/backups`, volume
persistent) — không phải thư mục `backups/` này trong repo. Local dev dùng
`backups/` ở repo root làm mặc định khi `DATA_DIR` không được set.

Lệnh dùng:
```bash
python scripts/backup_db.py --backup           # backup ngay
python scripts/backup_db.py --list             # xem danh sách
python scripts/backup_db.py --restore <file>   # dry-run — chỉ xem sẽ làm gì
python scripts/backup_db.py --restore <file> --confirm  # restore THẬT (phá huỷ dữ liệu hiện tại!)
```

## Quy tắc

- Không bao giờ đổi các dòng trong `.gitignore` để cho phép commit thư mục này.
- Nếu cần chia sẻ 1 phần dữ liệu ra ngoài (vd gửi accountant, auditor bên ngoài),
  export riêng phần cần thiết, KHÔNG gửi nguyên cả `v1.0-data-snapshot/` hay `db/`.
