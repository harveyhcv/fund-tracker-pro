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

### Phase 5B hoàn thiện (2026-06-20) — Encryption + /add-trade + Backfill

#### telegram-bot/crypto.py (MỚI)
- AES-256-GCM via `cryptography` lib
- `get_master_key()` — đọc `ENCRYPTION_KEY` env → SHA-256 → 32 bytes
- `derive_user_key(master_key, enc_salt)` — HKDF-SHA256, per-user key
- `make_auth_hash(telegram_id, master_key)` — HMAC-SHA256 cho users table
- `encrypt/decrypt(data, key)` — 12-byte nonce ‖ ciphertext+tag
- `encrypt_decimal/decrypt_decimal`, `encrypt_str/decrypt_str`

#### db.py (bổ sung)
- `get_user_info(telegram_id)` → {id, enc_salt} — read-only, không tạo mới
- `get_or_create_portfolio(user_uuid, name_enc)` → portfolio_id
- `get_portfolio_id(user_uuid)` → portfolio_id | None (không tạo)
- `add_transaction(...)` → tx UUID (immutable ledger INSERT)
- `upsert_holding(...)` — units_enc + avg_cost_enc
- `get_holdings_raw(user_uuid, portfolio_id)` → [{fund_code, units_enc, avg_cost_enc}]
- `get_pending_backfill(as_of)` → signals cần điền nav_at_settlement
- `get_nav_on_or_after(fund_code, target_date)` → nav từ nav_history (trong 7 ngày)

#### bot.py (bổ sung)
- `_CRYPTO_AVAILABLE` flag + `import crypto as _crypto`
- `_ensure_db_user(telegram_id, profile_name)` → (uuid, portfolio_id, user_key) — tạo nếu chưa có
- `_get_db_user(telegram_id)` → (uuid, portfolio_id, user_key) | None — chỉ đọc
- `_msg_portfolio_from_db(profile, raw_holdings, nav_data, user_key)` → message string
- `/portfolio` handler: thử DB path → decrypt holdings → P&L; fallback về config.json
- `/add-trade MÃ buy/sell CCQ tổng_tiền [ngày]` — ghi transaction + upsert holding
  - Tính nav_at_order = amount / units
  - Weighted avg cost khi buy: (prev_units × prev_avg + buy_units × nav) / new_units
  - Sell: giữ nguyên avg_cost (average cost method)
- `job_backfill_settlement()` — chạy 09:00 hàng ngày, tra nav_history → backfill_settlement_nav
- Schedule: `schedule.every().day.at("09:00").do(job_backfill_settlement)`

#### ENV cần thêm (Railway)
- `ENCRYPTION_KEY` — bất kỳ string nào (ít nhất 32 ký tự ngẫu nhiên)

#### Test suite sau Phase 5B: **280 tests** ✅
- `tests/test_phase5b.py` — 51 tests mới:
  - TestCrypto (18): get_master_key, derive_user_key, make_auth_hash, encrypt/decrypt, decimal/str roundtrip, tamper detection
  - TestAddTradeCommand (18): validation, DB unavailable, crypto missing, buy/sell success, holding upsert, weighted avg, date handling
  - TestPortfolioDbPath (6): DB path, P&L display, fallback cases
  - TestBackfillJob (9): DB flag, pending signals, fill/skip logic, error handling, multi-signal

### Phase 5C — Quick Trade + /navall + /research + Auto NAV Alert (2026-06-21)

#### bot.py (bổ sung — Phase 5C)
- `/buy MÃ số_CCQ tổng_tiền [ngày]` — shortcut cho `/add-trade MÃ buy ...` (không cần gõ "buy")
- `/sell MÃ số_CCQ tổng_tiền [ngày]` — tương tự cho sell
- `_cmd_add_trade(token, chat_id, profile, fund_code, tx_type, units, amount, order_date)` — helper
  - Tách ra từ `/add-trade` handler → dùng chung bởi /add-trade, /buy, /sell
- `/navall` — NAV tất cả quỹ trong config (không giới hạn watched_funds)
  - Format compact: emoji + mã + NAV + chg_pct + signal
- `/research MÃ` — phân tích chuyên sâu 5 trường phái (~1271 chars)
  - Gọi `get_nav_series()` + `calc_signal()` + `compute_research_stats()` + `msg_research()`
- `compute_research_stats(pts)` — tính thêm: 52w high/low, 1yr return, 30d vol (annualized), max drawdown
- `msg_research(code, d, stats, fund_name)` — format 5 trường phái: Technical / Value / Momentum / DCA / Risk
- `job_nav_change_alert()` — auto notification khi nav_date thay đổi (fired mỗi t_int phút)
  - Dùng `state["last_nav_dates"]` để track thay đổi, chỉ gửi khi có quỹ mới
  - Scheduled: `schedule.every(t_int).minutes.do(job_nav_change_alert)` (cùng interval với signal check)

#### Test suite: 280/280 ✅ (không cần test mới — logic _cmd_add_trade covered bởi test_phase5b.py)

### Phase 5D — /dca Rebalancer (2026-06-21)

- `msg_dca_suggest(profile, nav_data, budget)` — phân bổ theo weight = max(0, score + 6)
  - MUA MẠNH(12) > MUA(9) > HOLD(6) > BÁN(3) > BÁN MẠNH(0 = bỏ qua)
  - Làm tròn 1000đ, hiển thị % + amount + [score]
- `/dca [AMOUNT]` — gợi ý phân bổ ngay với số tiền tùy chọn
- `/dca setup AMOUNT` — lưu `monthly_dca` vào profile trong config.json
- `/dca off` — xóa monthly_dca
- `job_dca_reminder()` — chạy 09:00 hàng ngày, chỉ gửi khi day==1; gửi cho profile có monthly_dca
- Schedule: `schedule.every().day.at("09:00").do(job_dca_reminder)`
- Test suite: 280/280 ✅ (unchanged)

#### Pending (Phase 6)
- Webhook mode thay long-polling (giảm latency, cần public URL trên Railway)
- Telegram Mini App (WebApp) — cá nhân hóa dashboard trực tiếp trong Telegram

## 🔜 Có thể phát triển tiếp

- Swift iOS app (khi bắt đầu: update claude.md, thêm agents iOS)
- Inline keyboard (Reply keyboard buttons) cho UX tốt hơn
- Webhook mode thay long-polling (giảm latency)

## ⚠️ AUDIT 2026-07-09 — BACKLOG.md không khớp thực tế

BACKLOG.md (viết trước đó, có lẽ bởi phiên plan khác) mô tả Phase 1 Mini App
theo kiến trúc `dashboard/miniapp/` + endpoint gộp vào `server.py`. Nhưng thực tế
**Mini App đã được xây dựng từ trước** với kiến trúc khác hẳn:

- `telegram-bot/miniapp/index.html` (158KB) — Telegram WebApp SDK, không phải `dashboard/miniapp/`
- `telegram-bot/miniapp_server.py` (~1900 dòng) — server HTTP riêng, port `PORT_MINIAPP`/8443,
  khởi động qua thread trong `bot.py main()` (`from miniapp_server import start_in_thread`)
- Auth: verify HMAC `X-Init-Data` header **mỗi request** (`_validate_init_data`, `_auth_write`)
  — KHÔNG trao đổi session-token 1 lần như spec BACKLOG, nhưng tương đương bảo mật
- Đã có: `/api/me`, `/api/signals`, `/api/dca`, `/api/trades`, `/api/gold*`, `/api/admin/*`,
  auto-register user khi mở app lần đầu, portfolio P&L on-demand từ DB

**Bài học**: Luôn audit code thực tế trước khi tin BACKLOG.md — file này có thể lỗi thời nếu
được viết ra trước một phiên implement khác không cập nhật lại nó.

## ✅ Phase 2 — Freemium Gate (GATE-001/002/003, 2026-07-09)

- `telegram-bot/db.py`: thêm `_ensure_user_tiers_table()` (lazy-create, cùng pattern
  `bot_profiles`), `get_tier(telegram_id)` (tự downgrade 'pro'→'free' khi `pro_expires_at`
  đã qua), `set_tier(telegram_id, tier, pro_expires_at)` (upsert, gọi sau khi thanh toán)
- `telegram-bot/db.py`: thêm `set_watched_funds(telegram_id, funds)` — REPLACE watched_funds
  (khác `ensure_watched_funds` là UNION merge)
- `telegram-bot/miniapp_server.py`: thêm `FREE_FUND_LIMIT = 2`, `_get_tier()`, `_check_tier()`
  (middleware GATE-002, gửi 403 `{"error":"pro_required","upgrade_url":"/buy"}`)
- **Bug tìm thấy + fix**: `_api_update_watched` (POST `/api/me/watched_funds`) trước đó lấy
  `profile` từ DB (`_find_profile` ưu tiên `bot_profiles` table) nhưng mutate + `_save_cfg()`
  chỉ ghi vào `config.json` → add-fund KHÔNG persist khi chạy production trên Railway
  (DATABASE_URL set). Đã sửa: gọi `db.set_watched_funds()` khi `db_backed=True`.
- `/api/me` giờ trả thêm `tier`, `pro_expires_at`, `free_fund_limit` để frontend dùng cho GATE-004
- **Chưa verify integration thật** (không có DATABASE_URL trong môi trường agent) — cần
  deploy Railway để test `user_tiers` table tạo đúng + tier check hoạt động end-to-end
- Test suite: 55/280 fail nhưng **KHÔNG liên quan** đến thay đổi này — đã xác nhận bằng cách
  chạy test không đụng db.py/miniapp_server.py (test_commands.py JWT expiry) vẫn fail tương tự;
  nguyên nhân là lệch encoding console Windows (mangled Vietnamese text "C� ph�p") + JWT
  test dùng token mẫu đã hết hạn theo ngày hệ thống hiện tại — pre-existing, không phải do session này

**Việc tiếp theo (GATE-004)**: modal "Nâng cấp Pro" trong `telegram-bot/miniapp/index.html`
khi nhận response 403 `pro_required` — dùng `tier`/`free_fund_limit` đã có sẵn từ `/api/me`.

---

*Cập nhật: 2026-07-09 — Audit Mini App thực tế + Freemium Gate (GATE-001/002/003)*
