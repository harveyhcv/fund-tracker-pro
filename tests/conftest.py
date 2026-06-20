"""
conftest.py — Cấu hình pytest cho Fund Tracker Pro test suite.
Thêm đường dẫn tới telegram-bot/ và dashboard/ vào sys.path để
các test file có thể import bot và server trực tiếp.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BOT_DIR = PROJECT_ROOT / "telegram-bot"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"

# Thêm vào đầu sys.path để ưu tiên hơn các package đã cài
for p in [str(BOT_DIR), str(DASHBOARD_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)
