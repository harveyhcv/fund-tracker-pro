"""GOV-002 — Backup tự động PostgreSQL (pg_dump) + retention + restore.

Dùng chung `DATABASE_URL` (ENV, giống db.py). Backup lưu vào Railway persistent
volume (`DATA_DIR`/backups, mặc định `/data/backups` — khớp `DATA_DIR` mà
`bot.py`/`config.json` đã dùng), format custom (`pg_dump -F c`) để `pg_restore`
hỗ trợ restore chọn lọc bảng nếu cần, nén sẵn.

Usage:
    python scripts/backup_db.py --backup                  # tạo backup mới + prune cũ
    python scripts/backup_db.py --list                     # liệt kê backup hiện có
    python scripts/backup_db.py --restore <file> --confirm  # restore (PHÁ HUỶ dữ liệu hiện tại!)

KHÔNG BAO GIỜ tự ý restore mà không có --confirm — đây là thao tác phá huỷ,
đọc README/BACKUP.md trước khi chạy trên production.
"""
import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

RETENTION_DAYS = 14  # giữ 14 bản backup gần nhất (chạy 1 lần/ngày = ~2 tuần)


def _backup_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    d = data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("LỖI: DATABASE_URL chưa set trong ENV", file=sys.stderr)
        sys.exit(1)
    return url


def cmd_backup() -> None:
    url = _database_url()
    out_dir = _backup_dir()
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"ftp_backup_{ts}.dump"

    try:
        result = subprocess.run(
            ["pg_dump", url, "-F", "c", "-f", str(out_file)],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        print("LỖI: pg_dump không tìm thấy — cần cài postgresql-client (xem Dockerfile)", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print(f"LỖI pg_dump: {result.stderr[:500]}", file=sys.stderr)
        if out_file.exists():
            out_file.unlink()
        sys.exit(1)

    size_kb = out_file.stat().st_size / 1024
    print(f"OK: backup {out_file.name} ({size_kb:.0f} KB)")
    _prune(out_dir)


def _prune(out_dir: Path) -> None:
    """Xoá backup cũ hơn RETENTION_DAYS. Không bao giờ xoá nếu chỉ còn <=1 file
    (tránh mất backup duy nhất do lỗi cấu hình)."""
    files = sorted(out_dir.glob("ftp_backup_*.dump"), key=lambda p: p.stat().st_mtime)
    if len(files) <= 1:
        return
    cutoff = datetime.datetime.now().timestamp() - RETENTION_DAYS * 86400
    removed = 0
    for f in files[:-1]:  # luôn giữ file mới nhất bất kể tuổi
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    if removed:
        print(f"Đã xoá {removed} backup cũ hơn {RETENTION_DAYS} ngày")


def cmd_list() -> None:
    out_dir = _backup_dir()
    files = sorted(out_dir.glob("ftp_backup_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("Chưa có backup nào")
        return
    for f in files:
        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = f.stat().st_size / 1024
        print(f"{f.name}\t{mtime}\t{size_kb:.0f} KB")


def cmd_restore(filename: str, confirmed: bool) -> None:
    out_dir = _backup_dir()
    path = Path(filename)
    if not path.is_absolute():
        path = out_dir / filename
    if not path.exists():
        print(f"LỖI: không tìm thấy {path}", file=sys.stderr)
        sys.exit(1)
    if not confirmed:
        print(
            "⚠️  DRY-RUN — restore từ", path.name, "sẽ GHI ĐÈ dữ liệu hiện tại trong DB.\n"
            "Chạy lại với --confirm để thực hiện thật."
        )
        return

    url = _database_url()
    result = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "-d", url, str(path)],
        capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0:
        print(f"LỖI pg_restore: {result.stderr[:1000]}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: đã restore từ {path.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--restore", metavar="FILE")
    ap.add_argument("--confirm", action="store_true", help="Bắt buộc để restore thật (không phải dry-run)")
    args = ap.parse_args()

    if args.backup:
        cmd_backup()
    elif args.list:
        cmd_list()
    elif args.restore:
        cmd_restore(args.restore, args.confirm)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
