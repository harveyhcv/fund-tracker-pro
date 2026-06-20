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

## ✅ Sprint W16 — Token Dedup + Security + Portfolio P&L (13/04/2026)

- **W16-0**: `bot.py` import `send_token_alert_once/reset_token_alert`; `job_check_jwt` dedup alerts, reset flag khi token > 2h
- **W16-1**: `.gitignore` mới — cover `config.json`, `bot.log`, `state.json`, `core_data/*.db*`
- **W16-2**: Xóa 13 `.fuse_hidden` files; thêm WAL mode + busy_timeout=5000 vào `collect_core_data.py` + `server.py`
- **W16-3**: `scripts/token_manager.py` — decode JWT, check status 4 mức; `tests/test_token_manager.py` — 16 tests
- **W16-4**: `msg_portfolio()` upgrade: P&L đầy đủ (units × nav, vốn, lãi/lỗ, tổng) khi profile có `portfolio` field; fallback 7/30 ngày nếu không có; `tests/test_portfolio_command.py` — 17 tests
- **TCBS token mới**: exp 2026-04-14 06:42, alert flag reset
- **Test suite: 154 → 198 ✅** (+44 tests)

**Lưu ý portfolio:**
- Thêm `portfolio: [{code, units, avg_cost}]` vào profile trong `config.json` để dùng P&L mode
- Xem `config.example.json` để biết format

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

## ✅ Phase 4 — Telegram Bot Deployment Ready (2026-06-19)

### 4 Commands mới
- `/funds` — liệt kê tất cả quỹ, gợi ý /watch /unwatch
- `/watch CODE1 CODE2` — thêm quỹ vào danh mục của user
- `/unwatch CODE` — bỏ quỹ khỏi danh mục (min 1 quỹ)
- `/admin users|kick|broadcast` — quản lý users (chỉ ADMIN_TELEGRAM_ID)

### ENV Variable Support (cloud deployment)
- `BOT_TOKEN` → override config.json bot_token
- `ADMIN_TELEGRAM_ID` → override admin_telegram_id
- `LOCAL_SERVER_URL` → override local_server_url
- `DATA_DIR` → thư mục lưu config.json + state.json (mặc định = telegram-bot/)
- `MORNING_TIME`, `EVENING_TIME`, `SIGNAL_INTERVAL` → tùy chỉnh lịch

### First-run Bootstrap
- `_ensure_config_exists()`: tạo config.json đầy đủ từ ENV khi deploy lần đầu
- Bot tự tạo profiles khi user /register → không cần config thủ công

### Deployment Files (mới)
- `Dockerfile` — Python 3.11-slim, VOLUME /data
- `.env.example` — template secrets
- `.dockerignore` — loại trừ file nhạy cảm + không cần thiết
- `Procfile` — Railway/Heroku: `worker: cd telegram-bot && python -u bot.py`
- `railway.toml` — Dockerfile builder + volume mount /data
- `DEPLOY.md` — hướng dẫn deploy Railway / Render / Oracle Cloud

### Test Suite
- `tests/test_new_commands.py` — 30 tests mới cho /watch, /unwatch, /funds, /admin, ENV
- Tổng: **228 tests** (198 cũ + 30 mới)

### Lưu ý quan trọng
- `token_alert_patch.py` cũng dùng `DATA_DIR` env để tìm state.json (đã fix)
- Không commit `.env` lên git (đã thêm vào .gitignore)
- `ADMIN_TELEGRAM_ID` trong ENV/config.json phải là chat_id số (lấy bằng /getid)

## ✅ Phase 5 — PostgreSQL Architecture (2026-06-20)

### Files mới
- `schema.sql` — Full DDL PostgreSQL: 10 domains, 15 year-partitions (2013–2027), RLS, enums
- `telegram-bot/db.py` — Connection layer: ThreadedConnectionPool, init_pool(), upsert_nav(), save_signal(), get_or_create_user()
- `scripts/pg_init.py` — Run-once init script: `python scripts/pg_init.py`
- `telegram-bot/requirements.txt` — Thêm psycopg2-binary>=2.9.9, cryptography>=42.0.0

### Wire trong bot.py
- Import `db as _db` (graceful: nếu thiếu psycopg2 thì `_DB_AVAILABLE = False`, bot vẫn chạy)
- `main()` gọi `_db.init_pool()` nếu `DATABASE_URL` env set
- `job_check_signals()` gọi `_db.upsert_nav()` cho mỗi quỹ + `_db.save_signal()` khi có MUA/BÁN

### Schema highlights
- `nav_history` partitioned by year (nav_2013 → nav_2027)
- RLS: `SET LOCAL app.uid = '<uuid>'` → mọi query tự giới hạn data của user đó
- `transactions` immutable: có RULE no_update_tx + no_delete_tx
- `buy_signals` ghi indicators (rsi, bb_pct, macd_hist) + T+1/T+3 est_exec_date
- Encrypted fields: BYTEA cols (units_enc, amount_enc, avg_cost_enc) → AES-256-GCM ở app layer

### Setup trên Railway
1. Thêm PostgreSQL service → Railway inject DATABASE_URL tự động
2. Chạy schema: `railway run python scripts/pg_init.py`
3. Bot tự init pool khi khởi động

### Pending (next session)
- AES-256-GCM encryption layer (cryptography lib đã có trong requirements)
- T+1/T+3 `estimate_settlement_nav()` — backfill nav_at_settlement sau khi settlement date qua
- DCA rebalancer engine
- Portfolio commands via Telegram (/portfolio, /add-trade, /dca)
- Telegram Mini App (WebApp) — cá nhân hóa dashboard

## 🔜 Có thể phát triển tiếp

- Swift iOS app (khi bắt đầu: update claude.md, thêm agents iOS)
- Inline keyboard (Reply keyboard buttons) cho UX tốt hơn
- Webhook mode thay long-polling (giảm latency)

---

*Cập nhật: 2026-06-20 — Phase 5: PostgreSQL schema + db.py + bot.py wiring*
