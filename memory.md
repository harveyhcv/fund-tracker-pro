# 🧠 Memory — Fund Tracker Pro

> Claude đọc file này ĐẦU TIÊN để khôi phục context từ phiên trước.

---

## 📌 Kiến trúc hiện tại

- **3 file chính liên kết**: `dashboard/Quy Tracker Dashboard.html` + `dashboard/server.py` + `telegram-bot/bot.py`
- **server.py** chạy port 8080 — serve `dashboard/` folder + proxy API config/TCBS auth
- **Dashboard** là HTML thuần (không React/Vue) — Chart.js 4.4.4 cho biểu đồ NAV
- **Bot** chạy độc lập — schedule library + long-polling Telegram (manual, không dùng python-telegram-bot)
- **Swift Xcode project** trong `ios/` — skeleton, CHƯA PHÁT TRIỂN

## ✅ Đã hoàn thành

- Web Dashboard v4.2: dark theme (#060b14), IBM Plex Mono, tín hiệu MUA/BÁN/HOLD với emoji
- server.py: serve static + /bot-config + /save-nav + /tcbs-auth/otp + /tcbs-auth/verify
- Bot: scheduler sáng 08:00 + chiều 17:30 (T2-T6) + signal check mỗi 60 phút + 8 commands
- **Test suite**: 138 tests / 4 module / 100% pass — nằm trong `tests/`

## ⚠️ Lưu ý quan trọng (ĐÃ XÁC NHẬN)

- `server.py` và `Quy Tracker Dashboard.html` nằm trong **`dashboard/`** subfolder
- `bot/config.json` path trong server.py: `ROOT / "telegram-bot" / "config.json"` (ROOT = project root)
  - `ROOT = Path(__file__).parent.parent` (server.py ở dashboard/, ROOT là Fund Tracker Pro/)
- `tg_send` dùng `requests.POST` (không phải GET) → khi mock phải dùng `patch("bot.requests.post")`
- Signal system là **mean-reversion** (KHÔNG phải momentum):
  - Uptrend mạnh → RSI cao (overbought) → score âm → **BÁN**
  - Downtrend mạnh → RSI thấp (oversold) → score dương → **MUA**
  - Score ≥6 → MUA MẠNH 🟢🟢 | ≥3 → MUA 🟢 | ≤-6 → BÁN MẠNH 🔴🔴 | ≤-3 → BÁN 🔴 | else → HOLD ⚪
- Khi sửa endpoint trong server.py → kiểm tra JS trong HTML có gọi đúng không

## 🧪 Test Suite (`tests/`)

| File | Scope | Tests |
|------|-------|-------|
| test_indicators.py | RSI, BB, MACD, calc_signal | 47 |
| test_nav_fetch.py | fetch_fmarket, fetch_tcbs, get_nav_series | 34 |
| test_commands.py | tg_send, job_morning, job_check_signals, find_profile | 26 |
| test_server.py | server.py HTTP endpoints | 31 |

Chạy: `cd tests && python3 -m pytest -v`

## ✅ Phase 2B — Tách NAV ra nav_data.json (10/04/2026)

**Vấn đề cũ:** `_save_nav` dùng regex patch `var cn={...}` baked-in trong HTML → HTML nặng 1MB, fragile.

**Giải pháp thực thi:**
- Thêm `GET /nav-data` endpoint → serve `dashboard/nav_data.json`
- Sửa `_save_nav` → ghi vào `nav_data.json` (có `_lastRefresh` meta field), xóa regex HTML patch
- Dashboard HTML: IIFE → `async function`, fetch `/nav-data` thay thế `var cn={BIG_DATA}`
- HTML giảm **213 KB** (1MB → 843KB), không còn regex patch vào HTML
- Bug fix bonus: `test_signal_score_mapping` dùng `open("bot.py")` relative → sửa thành `Path(__file__).parent.parent / "telegram-bot/bot.py"`

**Test suite sau thay đổi:** 140/140 ✅

**Kiến trúc 3 lớp dữ liệu (QUAN TRỌNG):**
```
HIST.chart[]     → Full history từ ngày thành lập → HIST cutoff (2026-04-02)
nav_data.json    → INCREMENTAL: chỉ điểm date > histCutoff (~2KB, không trùng HIST)
S.cachedNav[]    → localStorage = merge từ nav_data.json + fresh fetch
navSeries(code)  → HIST.chart + cachedNav.filter(date > lastH)  ← merge point
```

**Logic incremental:**
- Frontend gửi `histCutoff: {TCBF: "2026-04-02", ...}` trong POST /save-nav
- server.py filter: chỉ lưu điểm `date > histCutoff[code]`
- Merge existing nav_data.json với data mới (giữ quỹ không có trong payload)
- Fallback: nếu không có histCutoff → trim 500 điểm cuối (backward-compat)

**Lưu ý quan trọng:**
- `nav_data.json` trống {} — populate khi user click "Lưu NAV" hoặc bot chạy
- Dashboard hoạt động nhờ localStorage + HIST (không cần nav_data.json ngay)
- `_lastRefresh` trong nav_data.json được ưu tiên hơn `_bkRef` baked vào HTML

## ✅ Phase 3A — Auto-refresh NAV + Stale Banner (10/04/2026)

**3 cải tiến đã thực hiện:**

### 1. POST /refresh-nav (server.py)
- Endpoint mới fetch NAV trực tiếp từ fmarket/TCBS (server-side, không cần bot)
- Hằng số `FUNDS_CONFIG` + `HIST_CUTOFF` trong server.py
- `_fetch_fmarket_nav(fmarket_id, from_date)` — dùng `urllib` (không cần requests)
- `_fetch_tcbs_nav(code, token, from_date)` — kèm TCBS auth từ config.json
- Chỉ lưu điểm delta sau HIST cutoff (2026-04-02), merge với existing nav_data.json

### 2. Bot push sau job_morning (bot.py)
- `_HIST_CUTOFF` dict (khớp server.py) — `{"TCBF":"2026-04-02",...}`
- `_push_nav_to_server(nav_data, config)` — POST /save-nav sau job_morning
- Không crash khi server offline (ConnectionError → debug log)
- `fetch_tcbs(code, token, from_date=None)` — thêm param từ lịch sử tốn kém

### 3. Stale banner (Dashboard HTML)
- `_bizDays(from, to)` — đếm ngày làm việc
- `_showStaleBanner(ld, gap)` — inject fixed div vào top of body khi gap > 3 ngày làm việc
- Nút "Cập nhật NAV" gọi POST /refresh-nav → reload page sau 1.5s
- Chỉ hiện khi dữ liệu thực sự stale — ẩn khi data up-to-date

**Test suite: 150/150 ✅** (+10 tests mới: TestRefreshNav x8, TestFetchTcbs from_date x2)

## ⚠️ Lưu ý quan trọng (BỔ SUNG)

- `_push_nav_to_server()` trong bot.py chỉ gửi 1 điểm NAV mới nhất mỗi lần (từ job_morning)
  - Để populate đầy đủ delta cần bấm "Cập nhật NAV" trong Dashboard (gọi /refresh-nav)
- `HIST_CUTOFF` trong server.py và `_HIST_CUTOFF` trong bot.py phải khớp nhau (hiện tại đều "2026-04-02")
- `/refresh-nav` đọc TCBS token từ `telegram-bot/config.json` (nếu file tồn tại)
- Stale banner màu amber (`#92400e`), chuyển xanh khi refresh thành công

## ✅ Phase 3C — TCBS Auth Alert + HIST Script + Header Badge (10/04/2026)

### 1. _handle_tcbs_auth_error (bot.py)
- Thêm module-level `_tcbs_auth_fail_codes: set` — populated bởi `fetch_tcbs` khi nhận 401/403
- `fetch_tcbs` phân biệt 401/403 vs lỗi khác: `break` ngay (không thử URL thứ 2) + add code vào set
- `_handle_tcbs_auth_error(config, codes)` — gửi Telegram cảnh báo với link Dashboard Settings
- `job_morning` và `job_check_signals` reset set trước fetch, gửi alert sau nếu set không rỗng
- **4 tests mới** trong `TestHandleTcbsAuthError` — 154/154 ✅

### 2. scripts/update_hist.py (MỚI)
- Script Python chạy thủ công khi nav_data.json > 30 ngày
- Fetch toàn bộ lịch sử từ fmarket/TCBS cho 5 quỹ
- Patch `const HIST={...}` trong HTML + cập nhật `_bkRef`
- Patch `HIST_CUTOFF` trong server.py và `_HIST_CUTOFF` trong bot.py (cùng ngày)
- Reset nav_data.json về `{}`
- Hỏi xác nhận trước khi ghi, tạo backup HTML.bak

### 3. Dashboard header badge "Dữ liệu đến" (HTML)
- IIFE: fix typo "Cap nhat" → "Dữ liệu đến: DD/MM/YYYY"
- refreshNAV() callback: sau khi fetch thành công hiện "Dữ liệu đến: DD/MM · Làm mới: HH:MM"

## 🔜 Có thể phát triển tiếp

- Swift iOS app (khi bắt đầu: update claude.md, thêm agents iOS)
- Deploy server lên VPS thay vì chạy local Mac
- Thêm /portfolio command đầy đủ (hiện tại là stub)
- P1: Dashboard hiển thị "Dữ liệu đến DD/MM" badge trong header (đã có _lastRefresh)
- P1: Script update_hist.py khi gap > 30 ngày (bake lại HIST.chart)

---

*Cập nhật: 2026-04-10 — Phase 3A: /refresh-nav + bot push + stale banner, 150 tests xanh*
