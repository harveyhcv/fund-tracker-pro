# 📋 Plan — Fund Tracker Pro
> **Handoff document cho Claude Code & Cowork.**
> Đọc `claude.md` → `memory.md` → file này trước khi làm bất cứ điều gì.
> Cập nhật: 2026-04-13 | Người cập nhật: Claude Cowork (Daily Review auto)

---

## 🚨 SPRINT W16 — LÀM NGAY (Tuần 14–18/04/2026)

> **Claude Code đọc section này trước.** Đây là các task ưu tiên cao nhất, có thứ tự thực thi cụ thể.
> Tất cả phải xong trước khi tiếp tục Phase 4.

---

### ✅ TASK W16-0 — Áp dụng `token_alert_patch.py` vào `bot.py`
**Ưu tiên: P0-CRITICAL | File: `telegram-bot/bot.py`**
**Trạng thái: ⏳ Chưa làm — TCBS token đã hết hạn ~38h tính đến 09:00 ngày 13/04**

Patch đã viết sẵn tại `telegram-bot/token_alert_patch.py`. Hướng dẫn áp dụng tại `telegram-bot/APPLY_PATCH.md`.
Cần thực hiện **3 thay đổi trong `bot.py`**:

**Thay đổi A — Thêm import ở đầu file:**
```python
from token_alert_patch import send_token_alert_once, reset_token_alert
```

**Thay đổi B — Tìm đoạn gửi alert token hết hạn, thay bằng:**
```python
# Tìm pattern: if is_token_expired() hoặc if not token_valid():
#   send_message(chat_id, "⚠️ Token...")   ← đoạn này
# Thay thành:
if is_token_expired():
    send_token_alert_once(
        send_fn=lambda msg: send_message(chat_id, msg),
        message="⚠️ TCBS Token đã hết hạn! Vào browser → F12 → localStorage lấy token mới."
    )
```

**Thay đổi C — Tìm hàm lưu token mới, thêm `reset_token_alert()`:**
```python
def save_new_token(new_token):       # (tên hàm có thể khác trong bot.py)
    config["tcbs_token"] = new_token
    save_config(config)
    reset_token_alert()              # ← thêm dòng này
```

**Verify:** Grep xem patch đã được import chưa:
```bash
grep "token_alert_patch" telegram-bot/bot.py
```

---

### TASK W16-1 — Bảo mật `.gitignore` + Audit `bot.log`
**Ưu tiên: P0 | Ước tính: 15 phút | File: `.gitignore`, `telegram-bot/bot.log`**
**Trạng thái: ⏳ Chưa làm — tồn đọng 3 ngày liên tiếp (báo cáo 11, 12, 13/04)**

**Bước 1 — Kiểm tra `.gitignore` hiện tại:**
```bash
cat .gitignore 2>/dev/null | grep -E "config|bot.log|state"
```

**Bước 2 — Thêm các entry còn thiếu:**
```bash
# Thêm vào .gitignore nếu chưa có:
telegram-bot/config.json
telegram-bot/bot.log
telegram-bot/state.json
core_data/*.db
core_data/*.db-shm
core_data/*.db-wal
core_data/.fuse_hidden*
```

**Bước 3 — Kiểm tra config.json có đang bị git track không:**
```bash
git ls-files telegram-bot/config.json
# Nếu có output → chạy tiếp:
git rm --cached telegram-bot/config.json
```

**Bước 4 — Audit bot.log (kiểm tra credential leak):**
```bash
grep -i "authorization\|bearer\|token" telegram-bot/bot.log | head -5
# Nếu có kết quả chứa JWT → truncate log:
# > telegram-bot/bot.log
```

**Verify:** `git status` không thấy `config.json` trong danh sách tracked/modified.

---

### TASK W16-2 — Dọn `.fuse_hidden` + SQLite Connection Hardening
**Ưu tiên: P1 | Ước tính: 20 phút | Thư mục: `core_data/`**
**Trạng thái: ⏳ Chưa làm — 13 file tồn đọng từ crash 11/04, nav.db-shm chưa giải phóng**

**Bước 1 — Kiểm tra không còn process giữ DB:**
```bash
lsof core_data/nav.db 2>/dev/null
# Nếu output trống → an toàn. Nếu có PID → dừng process đó trước.
```

**Bước 2 — Xóa fuse_hidden files:**
```bash
rm -f core_data/.fuse_hidden*
ls core_data/ | grep fuse  # Phải không còn kết quả
```

**Bước 3 — Hardening SQLite trong TẤT CẢ scripts Python dùng nav.db:**

Tìm tất cả file Python connect nav.db:
```bash
grep -rl "sqlite3.connect\|nav.db" scripts/ telegram-bot/ dashboard/ --include="*.py"
```

Đảm bảo mỗi file đều có pattern sau (thêm nếu thiếu):
```python
conn = sqlite3.connect('core_data/nav.db', timeout=30)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')
try:
    # ... logic ...
finally:
    conn.close()
```

**Verify:**
```bash
ls -la core_data/ | grep fuse   # Phải trống
python3 -c "import sqlite3; conn=sqlite3.connect('core_data/nav.db'); print(conn.execute('SELECT COUNT(*) FROM nav').fetchone()); conn.close()"
```

---

### TASK W16-3 — Tạo `scripts/token_manager.py`
**Ưu tiên: P1 | Ước tính: 2–3h | File mới: `scripts/token_manager.py`**
**Trạng thái: ⏳ Chưa làm — W16-0 phải xong trước (cần `send_token_alert_once`)**

Tạo file `scripts/token_manager.py` với logic sau:

```python
#!/usr/bin/env python3
"""token_manager.py — Kiểm tra JWT TCBS token freshness.

Dùng:
  python3 scripts/token_manager.py --check   # check + alert nếu gần hết hạn
  python3 scripts/token_manager.py --status  # in trạng thái ra stdout (không alert)
"""
import argparse, base64, datetime, json, os, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "telegram-bot/config.json"
STATE_PATH  = ROOT / "telegram-bot/state.json"

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())

def decode_jwt_exp(token: str) -> int | None:
    """Parse JWT payload → trả về Unix timestamp 'exp', hoặc None nếu lỗi."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        return payload.get("exp")
    except Exception:
        return None

def check_token(alert: bool = True) -> dict:
    """Kiểm tra token, trả về dict trạng thái."""
    cfg = load_config()
    token = cfg.get("tcbs_token", "")
    now = datetime.datetime.now().timestamp()

    if not token:
        return {"status": "missing", "remaining_minutes": 0}

    exp = decode_jwt_exp(token)
    if exp is None:
        return {"status": "unreadable", "remaining_minutes": 0}

    remaining = exp - now
    remaining_minutes = int(remaining / 60)

    if remaining <= 0:
        status = "expired"
    elif remaining < 3600:          # < 1h
        status = "critical"
    elif remaining < 7200:          # < 2h
        status = "warning"
    else:
        status = "ok"

    result = {"status": status, "remaining_minutes": remaining_minutes, "exp": exp}

    if alert and status in ("expired", "critical", "warning"):
        _send_alert(cfg, status, remaining_minutes)

    return result

def _send_alert(cfg: dict, status: str, remaining_minutes: int):
    """Gửi Telegram alert — dùng send_token_alert_once để tránh spam."""
    sys.path.insert(0, str(ROOT / "telegram-bot"))
    from token_alert_patch import send_token_alert_once

    if status == "expired":
        msg = "🔴 TCBS JWT Token ĐÃ HẾT HẠN! Vào Dashboard Settings → refresh ngay."
    elif status == "critical":
        msg = f"🟠 TCBS JWT Token sắp hết hạn! Còn {remaining_minutes} phút."
    else:
        msg = f"🟡 TCBS JWT Token còn {remaining_minutes} phút — chuẩn bị refresh."

    # Lấy chat_id từ config
    chat_id = cfg.get("telegram_chat_id") or cfg.get("admin_chat_id")
    bot_token = cfg.get("telegram_token") or cfg.get("bot_token")
    if not (chat_id and bot_token):
        print(f"[token_manager] Không tìm thấy bot_token/chat_id trong config: {msg}")
        return

    import urllib.request
    def send_fn(text):
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)

    sent = send_token_alert_once(send_fn, msg)
    if sent:
        print(f"[token_manager] Alert đã gửi: {msg}")
    else:
        print(f"[token_manager] Alert đã gửi trước đó — bỏ qua (dedup)")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check",  action="store_true", help="Check + gửi alert nếu cần")
    parser.add_argument("--status", action="store_true", help="In trạng thái, không alert")
    args = parser.parse_args()

    result = check_token(alert=args.check)
    status = result["status"]
    mins   = result["remaining_minutes"]

    icons = {"ok": "✅", "warning": "🟡", "critical": "🟠", "expired": "🔴", "missing": "❓", "unreadable": "❓"}
    print(f"[token_manager] {icons.get(status, '?')} Status: {status.upper()} | Còn: {mins} phút")

    if status == "expired":
        sys.exit(1)  # Exit code 1 → crontab có thể phát hiện

if __name__ == "__main__":
    main()
```

**Thêm vào crontab (chạy mỗi 30 phút, ngày thường):**
```bash
# Xem crontab hiện tại:
crontab -l
# Thêm dòng:
*/30 * * * 1-5 cd /path/to/"Fund Tracker Pro" && python3 scripts/token_manager.py --check >> /tmp/token_check.log 2>&1
```

**Unit tests cần viết (`tests/test_token_manager.py`):**
- `test_decode_jwt_exp_valid`: JWT hợp lệ → trả về exp đúng
- `test_decode_jwt_exp_invalid`: JWT rác → trả về None
- `test_status_expired`: exp trong quá khứ → status="expired"
- `test_status_warning`: exp còn 90 phút → status="warning"
- `test_status_ok`: exp còn 6 giờ → status="ok"
- `test_missing_token`: config không có token → status="missing"

**Verify:**
```bash
python3 scripts/token_manager.py --status
# → [token_manager] 🔴 Status: EXPIRED | Còn: -XXXX phút  (vì token đã hết hạn)
python3 -m pytest tests/test_token_manager.py -v
```

---

### TASK W16-4 — Bot `/portfolio` command
**Ưu tiên: P1 | Ước tính: 3–4h | File: `telegram-bot/bot.py`**
**Trạng thái: ⏳ Chưa làm — làm SAU khi W16-0, W16-1, W16-2 xong**

Implement `/portfolio` command đọc từ `config.json["profiles"][user]["portfolio"]`.

**Output format Telegram:**
```
📊 DANH MỤC — Harvey
──────────────────────
TCBF   10.500 CCQ
 Giá vốn: 12,500 → Hiện: 13,245 (+5.96%) 🟢 MUA
 Giá trị: 139,072,500 đ | Lãi: +7,822,500 đ

SSISCA  5.200 CCQ
 Giá vốn: 21,200 → Hiện: 20,800 (-1.89%) ⚪ HOLD
 Giá trị: 108,160,000 đ | Lỗ: -2,080,000 đ
──────────────────────
💰 Tổng: 247,232,500 đ | Lãi: +5,742,500 đ (+2.37%)
```

**Cần viết 8–10 unit tests** trong `tests/test_portfolio_command.py`.

---

## 📋 THỨ TỰ THỰC THI CHO CLAUDE CODE

```
1. W16-0  ← Ngay lập tức (token đã expire)
2. W16-1  ← Bảo mật (< 15 phút)
3. W16-2  ← Dọn dẹp DB (< 20 phút, bắt buộc trước Phase 4)
4. W16-3  ← Tạo token_manager.py + tests
5. W16-4  ← /portfolio command
6. Phase 4 tiếp tục (TASK 4-B, 4-E) ← sau khi W16-0 đến W16-3 xong
```

---

---

## 🗺️ TRẠNG THÁI TỔNG QUAN

```
Phase 0  ✅  Config, QA suite 138 tests
Phase 1  ✅  Live API verify — fmarket OK, TCBS OK, Telegram OK
Phase 2A ✅  RotatingFileHandler + Watchdog ping 00:01
Phase 2B ✅  Tách NAV → nav_data.json (3-layer architecture)
Phase 2C ✅  Swift signal threshold sync Python ↔ Swift
Phase 3A ✅  POST /refresh-nav + bot push + stale banner → 150 tests
Phase 3B ✅  Start Dashboard.command + TCBS token alert + per-fund stale badge
             + manual NAV input + setup_launchagent.sh
             + FUNDS_CONFIG fix (VCBFTBF→31, TCBF→22)
Phase 3C ✅  _handle_tcbs_auth_error (bot auto-alert 401) + scripts/update_hist.py
             + Dashboard header badge "Dữ liệu đến DD/MM" → 154 tests

Phase 4  🔄  CORE DATA — Thu thập NAV history (đang thực thi — xem chi tiết bên dưới)
```

**Test suite hiện tại:** `154/154 ✅` (Phiên 6: fix test domain apipubaws→apiextaws)

---

## ✅ PHASE 4 PROGRESS (Phiên 6 — 2026-04-11)

### Đã hoàn thành
- **TASK 4-A** ✅ `scripts/collect_core_data.py` đã tồn tại + hoạt động (dùng SQLite nav.db)
  - Cũng có: `scripts/fetch_missing_funds.py`, `scripts/import_tcbs_export.py`, `scripts/tcbs_export_snippet.js`
- **TASK 4-C** ✅ TCCF đã bị xóa → TCGF thêm vào `config.json`, `config.example.json`, `server.py`, `nav.db`
- **TASK 4-E (partial)** ✅ Tìm được **MAFPF1 = fmarket_id 45** (660 pts mới, từ 2020-02-07)
- **Bug fix**: `test_nav_fetch.py` domain fix `apipubaws` → `apiextaws`
- **Bug fix**: `fetch_missing_funds.py` Python 3.9 compat (`int | None` → `= None`)

### Trạng thái core_data/nav.db hiện tại

| Fund | Pts | From | Status |
|------|-----|------|--------|
| DCDS | 3565 | 2004-05-20 | ✅ Full |
| SSISCA | 2091 | 2014-09-26 | ✅ Full |
| VNDBF | 1694 | 2019-07-05 | ✅ Full |
| MBVF | 1586 | 2014-04-25 | ✅ Full |
| MIRAEF | 1350 | 2018-01-12 | ✅ Full |
| BVPF | 1147 | 2017-01-02 | ✅ Full |
| VCBFTBF | 1041 | 2013-12-26 | ✅ Full |
| DCBF | 1065 | 2013-06-10 | ✅ Full |
| MAFEQI | 1186 | 2014-10-21 | ✅ Full |
| TCBF | 1137 | 2019-07-02 | ⚠ fmarket chỉ có từ 2019 — TCBS có từ 2015 |
| VCBFBCF | 972 | 2014-08-27 | ✅ Full |
| MAFPF1 | 667 | 2020-02-07 | ✅ Full (mới fetch phiên này) |
| ESBF | 7 | 2026-03-27 | ⚠ Cần tìm fmarket_id |
| ESSCF | 7 | 2026-03-27 | ⚠ Cần tìm fmarket_id |
| MBBF | 7 | 2026-03-27 | ⚠ Cần tìm fmarket_id |
| VCBFEF | 7 | 2026-03-27 | ⚠ Cần tìm fmarket_id |
| TCFF | 8 | 2026-04-03 | ⚠ Cần TCBS browser export |
| TCGF | 1 | 2026-04-11 | ⚠ Cần TCBS browser export |
| VNDAF | 0 | — | ⚠ Cần tìm fmarket_id |

### Ghi chú quan trọng (Phiên 6)
- fmarket API `/res/product/get-nav-history` hoạt động với headers Chrome đầy đủ
- fmarket data hiện tại **dừng ở 2025-12-04** — data từ 2026-01-01 đến nay cần từ nguồn khác
- `/res/public/fund/filter` và `/res/public/fund/chart-nav` trả về 404 (endpoint đã bị xóa)
- `fetch_missing_funds.py` đã fix Python 3.9 compat

---

## 🚨 PHASE 4 — CORE DATA (Tiếp theo)

### Mục tiêu

Thu thập toàn bộ lịch sử NAV của tất cả 31 quỹ từ ngày thành lập đến nay.
Dữ liệu sau khi verify sẽ **khóa cứng** — chỉ cho phép append điểm mới, không sửa/xoá.

**Lưu trữ:** `core_data/<CODE>.json` — mỗi quỹ một file.
**Format:** `[{"date": "yyyy-mm-dd", "nav": 12345.67}, ...]` — sorted by date, no duplicates.

---

### TASK 4-A — Tạo script `scripts/collect_core_data.py`

Script fetch full NAV history cho tất cả fmarket funds. Chạy một lần duy nhất.

**Logic:**
```python
#!/usr/bin/env python3
"""collect_core_data.py — Thu thập toàn bộ NAV history từ fmarket.

Chạy: python3 scripts/collect_core_data.py
Output: core_data/<CODE>.json cho mỗi quỹ có fmarket_id
"""
import json, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG = json.loads((ROOT / "telegram-bot/config.json").read_text())
CORE_DIR = ROOT / "core_data"
CORE_DIR.mkdir(exist_ok=True)

FMARKET_URL = "https://api.fmarket.vn/res/product/get-nav-history"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://fmarket.vn",
    "Referer": "https://fmarket.vn/",
    "User-Agent": "Mozilla/5.0",
}

def fetch_fmarket_full(fmarket_id: int) -> list:
    payload = json.dumps({
        "isAllData": 1,
        "productId": fmarket_id,
        "fromDate": None,
        "toDate": None
    }).encode()
    req = urllib.request.Request(FMARKET_URL, data=payload, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    navs = (data.get("data") or {}).get("navHistories") or []
    pts = []
    for n in navs:
        d = (n.get("navDate") or n.get("tradingDate") or "")[:10]
        v = float(n.get("navPerShare") or n.get("nav") or 0)
        if d and v > 0:
            pts.append({"date": d, "nav": v})
    return sorted(pts, key=lambda p: p["date"])

def save_core(code: str, pts: list):
    out = CORE_DIR / f"{code}.json"
    if out.exists():
        existing = json.loads(out.read_text())
        existing_dates = {p["date"] for p in existing}
        new_pts = [p for p in pts if p["date"] not in existing_dates]
        merged = sorted(existing + new_pts, key=lambda p: p["date"])
    else:
        merged = pts
    out.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")))
    return len(merged)

funds = CONFIG.get("funds", {})
for code, info in funds.items():
    fid = info.get("fmarket_id")
    if not fid:
        print(f"⚠ {code}: fmarket_id=null — bỏ qua (cần TCBS)")
        continue
    try:
        pts = fetch_fmarket_full(fid)
        total = save_core(code, pts)
        print(f"✅ {code} (id={fid}): {total} điểm → {pts[-1]['date']}")
    except Exception as e:
        print(f"❌ {code}: {e}")
    time.sleep(0.5)
```

**Chạy lệnh:**
```bash
cd "Fund Tracker Pro"
python3 scripts/collect_core_data.py
```

**Kết quả mong đợi** (các quỹ có fmarket_id):

| Code | fmarket_id | Kỳ vọng |
|---|---|---|
| TCBF | 22 | ~3800+ điểm |
| SSISCA | 11 | ~2100+ điểm |
| VCBFTBF | 31 | ~1500+ điểm |
| VCBFBCF | 32 | ~1500+ điểm |
| MAFEQI | 72 | ~? điểm |
| MBVF | 47 | ~? điểm |
| BVPF | 14 | ~? điểm |
| MIRAEF | 38 | ~? điểm |
| VNDBF | 37 | ~? điểm |
| DCDS | 28 | ~? điểm |
| DCBF | 27 | ~? điểm |

---

### TASK 4-B — Lưu 3 quỹ TCBS từ Browser

**Bối cảnh:** TCBF, TCFF, TCGF không có fmarket_id — chỉ có trên TCBS.
- TCBS API bị lỗi RSA signing (không thể gọi từ Python)
- Dữ liệu đã có sẵn trong Chrome localStorage (từ session đang mở)

**Trạng thái dữ liệu đã thu thập (từ Chrome, 11/04/2026):**

| Quỹ | Điểm | Từ ngày | Đến ngày | Trạng thái |
|---|---|---|---|---|
| TCBF | 3,868 | 2015-09-08 | 2026-04-10 | ✅ Có trong browser |
| TCFF | 2,684 | 2018-12-05 | 2026-04-10 | ✅ Có trong browser |
| TCGF | 5,941 | 2010-01-04 | 2026-04-10 | ✅ Có trong browser |

**Cách lưu (2 cách, chọn 1):**

**Cách 1 — Dùng Chrome tool, tạo download blob (dễ nhất):**
```javascript
// Chạy trong Chrome console tại tcinvest.tcbs.com.vn
// Sau khi đã có window._allData
const json = JSON.stringify(window._allData, null, 2);
const blob = new Blob([json], {type: 'application/json'});
const a = document.createElement('a');
a.href = URL.createObjectURL(blob);
a.download = 'tcbs_core_data.json';
a.click();
// → File lưu vào ~/Downloads/tcbs_core_data.json
```

Sau đó Python đọc và lưu vào core_data/:
```bash
python3 -c "
import json
from pathlib import Path
src = Path.home() / 'Downloads/tcbs_core_data.json'
core = Path('core_data')
core.mkdir(exist_ok=True)
data = json.loads(src.read_text())
for code, pts in data.items():
    pts_sorted = sorted(pts, key=lambda p: p['date'])
    (core / f'{code}.json').write_text(json.dumps(pts_sorted, separators=(',', ':')))
    print(f'{code}: {len(pts_sorted)} pts → {pts_sorted[-1][\"date\"]}')
"
```

**Cách 2 — Chạy lại Chrome session và save qua /save-core-data:**
Endpoint đã có trong server.py. Vì HTTPS→HTTP bị blocked, navigate về localhost:8080 trước:
```javascript
// 1. Lưu data vào localStorage key đặc biệt khi đang ở TCBS
localStorage.setItem('_export_TCBF', JSON.stringify(window._allData.TCBF));
localStorage.setItem('_export_TCFF', JSON.stringify(window._allData.TCFF));
localStorage.setItem('_export_TCGF', JSON.stringify(window._allData.TCGF));
// 2. Navigate đến localhost — đọc từ LocalStorage không được vì khác origin
// → Dùng Cách 1 (blob download) là đơn giản nhất
```

---

### TASK 4-C — Fix config.json (xoá TCCF, thêm TCGF)

**Phát hiện mới (11/04/2026):** TCCF **không tồn tại**. Quỹ thứ 3 của TCBS là **TCGF** (Quỹ Tăng Trưởng Techcombank, 5,941 điểm từ 2010).

**Sửa `telegram-bot/config.json`:**
```json
// XOÁ entry "TCCF"
// THÊM entry "TCGF":
"TCGF": {
  "name": "Quỹ Tăng Trưởng Techcombank",
  "fmarket_id": null,
  "tcbs": true
}
```

Cũng cập nhật `dashboard/server.py` trong `FUNDS_CONFIG`:
```python
# XOÁ "TCCF"
# THÊM:
"TCGF": {"source": "tcbs", "fmarket_id": None, "tcbs_fallback": True},
```

---

### TASK 4-D — Verify và Lock core_data

Sau khi 4-A và 4-B xong:

1. **Kiểm tra coverage:**
```bash
python3 -c "
import json
from pathlib import Path
for f in sorted(Path('core_data').glob('*.json')):
    pts = json.loads(f.read_text())
    print(f'{f.stem}: {len(pts)} pts | {pts[0][\"date\"]} → {pts[-1][\"date\"]}')
"
```

2. **Kết quả mong đợi** — coverage đủ:
   - Tất cả quỹ có fmarket_id: full history từ ngày thành lập
   - TCBF/TCFF/TCGF: từ 2010-2018 đến 2026-04-10+

3. **Lock cơ chế:** `_handle_save_core_data` trong server.py đã implement append-only logic (chỉ thêm điểm mới, không sửa/xoá). Không cần thêm gì.

---

### TASK 4-E — Tìm fmarket_id cho các quỹ còn thiếu

Các quỹ trong config.json có `fmarket_id: null` nhưng **không phải TCBS**:

| Code | Tên | Cần làm |
|---|---|---|
| VCBFEF | VCB Fund Cổ Phiếu | Tìm fmarket_id |
| MAFPF1 | Manulife Hưu Trí | Tìm fmarket_id |
| MBBF | MB Capital Trái Phiếu | Tìm fmarket_id |
| ESSCF | Eastspring Cổ Phiếu | Tìm fmarket_id |
| ESBF | Eastspring Trái Phiếu | Tìm fmarket_id |
| VNDAF | VinaCapital Cổ Phiếu | Tìm fmarket_id |

**Cách tìm:** Chạy đoạn script trong TASK 4-A (search range 1-200):
```bash
python3 -c "
import requests, time
headers = {'Content-Type':'application/json','Origin':'https://fmarket.vn','Referer':'https://fmarket.vn/'}
for fid in range(1, 200):
    try:
        r = requests.post('https://api.fmarket.vn/res/product/get-nav-history',
            json={'isAllData':1,'productId':fid,'fromDate':None,'toDate':None},
            headers=headers, timeout=8)
        if r.ok:
            data = r.json().get('data',{}) or {}
            navs = data.get('navHistories',[])
            if navs and len(navs) > 100:
                code = data.get('productCode','?') or navs[0].get('productCode','?')
                print(f'ID {fid:3d}: {code:12s} {len(navs)} pts → {navs[-1].get(\"navDate\",\"\")[:10]}')
    except: pass
    time.sleep(0.2)
"
```

Kết quả từ script này → cập nhật `config.json` với fmarket_id mới.

---

## 📍 ROADMAP P0 — SAU PHASE 4

### P0-A — Script cập nhật HIST.chart hàng tháng

**Vấn đề:** `HIST.chart` cutoff tại `2026-04-02`. Sau 30+ ngày, `nav_data.json` phình to.

**Khi Phase 4 xong:** `core_data/` chứa full history → `update_hist.py` đọc từ `core_data/` thay vì fetch lại từ API.

**File:** `scripts/update_hist.py` (skeleton đã có)

---

## 📍 ROADMAP P1 — Tháng tới

### P1-A — Bot: Command `/portfolio` hoàn chỉnh
### P1-B — Auto-renew TCBS token (OTP flow)
### P1-C — Dashboard: Fund selector (theo dõi thêm quỹ ngoài 5 quỹ mặc định)

---

## 📍 ROADMAP P2 — Phase 5 iOS (SAU KHI WEB + CORE DATA HOÀN THIỆN)

> **Chỉ bắt đầu khi:** Phase 4 và P0-A xong, Harvey confirm Web ổn định.

**Skeleton sẵn:** `ios/` — ContentView.swift, MathEngine.swift, NetworkManager.swift, Models.swift

**Thứ tự implement iOS:**
1. `NetworkManager.swift` — đọc từ `core_data/` qua `http://mac-ip:8080/core-data/<CODE>`
2. `MathEngine.swift` — đã sync threshold (≥6/≤-6), wire vào UI
3. `ContentView.swift` — port từ Dashboard HTML v4.3
4. Portfolio Management UI

---

## 🧪 CÁCH CHẠY TEST SUITE

```bash
cd "Fund Tracker Pro/tests"
python3 -m pytest -v   # 154 tests
```

---

## ⚠️ NGUYÊN TẮC KHÔNG VI PHẠM

1. **Không sửa iOS** cho đến khi Web + Core Data hoàn thiện
2. **Không hardcode API keys** — luôn đọc từ `config.json`
3. **154/154 tests phải xanh** sau mọi thay đổi server.py hoặc bot.py
4. **core_data/ là append-only** — không sửa/xoá điểm NAV đã lưu
5. **HIST_CUTOFF** trong `server.py` và `_HIST_CUTOFF` trong `bot.py` phải luôn khớp
6. **TCCF không tồn tại** — dùng TCGF (Quỹ Tăng Trưởng Techcombank)

---

## 🗂️ Files quan trọng

| File | Đường dẫn |
|------|-----------|
| Dashboard HTML | `dashboard/Quy Tracker Dashboard.html` |
| Server | `dashboard/server.py` (port 8080) |
| NAV delta | `dashboard/nav_data.json` |
| **Core data** | **`core_data/<CODE>.json`** ← mới |
| Bot | `telegram-bot/bot.py` |
| Bot config | `telegram-bot/config.json` |
| Collect script | `scripts/collect_core_data.py` ← cần tạo |
| Tests | `tests/` — 154 tests |
