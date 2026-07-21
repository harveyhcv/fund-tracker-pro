"""Emergency cleanup — chạy trước bot.py khi worker khởi động.

Xoá backup files thừa trong DATA_DIR/backups, giữ tối đa KEEP bản mới nhất.
Không cần DB connection, không fail nếu thư mục trống.
"""
import os
import sys
from pathlib import Path

KEEP = 3  # giữ 3 bản gần nhất khi emergency cleanup


def main():
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    backup_dir = data_dir / "backups"
    if not backup_dir.exists():
        print("[cleanup] /data/backups không tồn tại, bỏ qua")
        return

    files = sorted(backup_dir.glob("ftp_backup_*.dump"), key=lambda p: p.stat().st_mtime)
    total = len(files)
    total_mb = sum(f.stat().st_size for f in files) / 1024 / 1024

    print(f"[cleanup] Tìm thấy {total} backup files, tổng {total_mb:.0f} MB")

    if total <= KEEP:
        print(f"[cleanup] Đủ ít ({total} <= {KEEP}), không xoá")
        return

    to_delete = files[:-KEEP]
    for f in to_delete:
        mb = f.stat().st_size / 1024 / 1024
        f.unlink()
        print(f"[cleanup] Đã xoá {f.name} ({mb:.0f} MB)")

    freed = sum(f.stat().st_size for f in to_delete) / 1024 / 1024
    print(f"[cleanup] Giải phóng {freed:.0f} MB, còn lại {KEEP} bản")


if __name__ == "__main__":
    main()
