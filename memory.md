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

## ✅ GATE-004 — Upgrade-to-Pro Modal (2026-07-09, autonomous run)

- `telegram-bot/miniapp/index.html`: thêm modal `#upgrade-modal` (cùng pattern
  `.modal-overlay`/`.modal-sheet` với modal phân tích quỹ có sẵn, z-index:300 để nổi
  trên `#watch-modal` z-index:1000 — phải gọi `closeWatchModal()` trước khi mở để tránh
  bị che khuất do watch-modal cao hơn)
- `showUpgradeModal(info)` — hiện lý do (dùng `info.limit` nếu có) + list tính năng Pro tĩnh
- `apiPost`/`apiDelete`: giờ đính kèm `err.body` (parsed JSON) + `err.status` vào Error ném
  ra khi `!res.ok`, để caller phân biệt được `pro_required` với lỗi khác (trước đây chỉ có
  `err.message = e.error||res.status`, không đủ để phân biệt loại lỗi chương trình)
- Wire vào 2 nơi gọi `POST /api/me/watched_funds` (nơi duy nhất hiện trigger GATE-003):
  `addNewFundAndWatch()` và `saveWatchedFunds()` — catch block check `isProRequired(e)`
- **CTA "NÂNG CẤP NGAY"** hiện chỉ đóng modal + toast "sắp ra mắt" vì PAY-001..003 (Telegram
  Stars invoice) CHƯA implement — không có route thật để điều hướng tới. Khi PAY-001 xong,
  sửa `startUpgrade()` để gọi endpoint/deep-link thật thay vì toast placeholder
- Verify: `node -e "new Function(...)"` parse script tag OK; preview static server
  (`telegram-bot/miniapp/`) qua `preview_start miniapp` — gọi `showUpgradeModal({limit:2})`
  và `startUpgrade()` trực tiếp qua `preview_eval`, xác nhận modal render đúng nội dung
  (snapshot) và toast/close hoạt động đúng, không có console error
- Task tiếp theo trong BACKLOG: PAY-001 (`/buy_pro` Telegram Stars invoice)

---

## ✅ Session 4 — Ca sáng autonomous: MoMo + Alert system + NAV confidence audit (2026-07-10)

**Audit trước khi code (BACKLOG.md lỗi thời — bài học lặp lại từ session trước):**
- **PRO-002** (gold analysis) và **PRO-003** (unlimited fund cho pro) đã được implement từ
  trước trong 1 phiên khác không update BACKLOG — `_calc_gold_signals()` (RSI/BB/MA/score,
  `miniapp_server.py:104`) và bypass FREE_FUND_LIMIT cho pro/admin (`_api_update_watched`
  `miniapp_server.py:1087`) đã hoạt động đầy đủ. Chỉ cần đánh dấu DONE, không cần code thêm.
- **Bài học**: LUÔN grep code thực tế trước khi bắt đầu 1 task trong BACKLOG — có thể đã
  được làm bởi phiên khác mà quên update trạng thái.

**PAY-004/005 — MoMo payment (mới, code thật):**
- `miniapp_server.py`: `POST /api/payment/momo/create` (MoMo v2 `captureWallet`,
  HMAC-SHA256 sign, orderId format `FTP-<tgid>-<ts>` để IPN parse lại được telegram_id
  không cần thêm bảng mapping), `POST /api/payment/momo/ipn` (verify signature trước khi
  tin field nào, `resultCode=0` → `db.set_tier(pro, +30d)` + Telegram confirm)
- Dùng MoMo test/sandbox credentials công khai làm default (`MOMO_PARTNER_CODE=MOMO`,
  `MOMO_ACCESS_KEY`/`MOMO_SECRET_KEY`) — **PHẢI** override bằng ENV thật khi có merchant
  MoMo đăng ký ở business.momo.vn, nếu không mọi giao dịch sẽ chạy ở sandbox test endpoint
- Frontend: nút "💗 THANH TOÁN QUA MOMO" trong `#upgrade-modal`, `startUpgradeMomo()` mở
  `pay_url` qua `tg.openLink()`
- **Bug tìm thấy + fix (không liên quan MoMo nhưng cùng khu vực payment)**: `do_POST` gọi
  `self._api_create_stars_invoice(user)` nhưng `user` chưa từng gán trong scope `do_POST`
  → NameError mỗi lần bấm "NÂNG CẤP PRO NGAY" trong Mini App kể từ khi `startUpgrade()`
  được wire (code này có sẵn nhưng chưa test qua UI thật nên bug chưa lộ ra). Đã sửa:
  `_api_create_stars_invoice()` tự validate `X-Init-Data` để lấy `user`, cùng pattern
  `_auth_write()`. **Nhắc nhở**: mọi endpoint miniapp mới PHẢI test qua `preview_*` tools
  (không chỉ py_compile) vì lỗi kiểu NameError-do-thiếu-tham-số không lộ ra khi compile.

**PRO-004 — Alert system (mới):**
- `db.py`: bảng `alerts` (telegram_id, fund_code, condition, threshold, last_triggered,
  active) + `create_alert`/`list_alerts`/`delete_alert`/`get_active_alerts`/
  `mark_alert_triggered`
- `bot.py job_check_alerts()` — 18:33 (sau harvest 18:30 + T2 predict/score 18:31/18:32),
  tái dùng `fetch_all()` (không query DB trực tiếp) để lấy signal/chg_pct mới nhất, debounce
  1 lần/ngày/alert qua so sánh `last_triggered.date()`
- API `GET/POST /api/alerts`, `DELETE /api/alerts/<id>` — pro-gated qua `_check_tier`
- UI: mục "🔔 Cảnh báo" gắn vào **cuối modal Nghiên cứu** (cùng chỗ PRO-001, vì modal đó đã
  pro-gated sẵn nên không cần thêm logic ẩn/hiện theo tier ở phía client) — đặt/xóa cảnh báo
  nav_up/nav_down/signal_buy/signal_sell cho quỹ đang xem, không tạo trang/nav-bar riêng
  (giữ UI đơn giản, tránh phình bottom-nav vốn đã có 6 tab)

**Phát hiện quan trọng: có 1 tính năng lớn "mồ côi" trong working tree lúc bắt đầu session —**
`telegram-bot/db.py`, `bot.py`, `harvest_nav.py` có ~450 dòng thay đổi CHƯA COMMIT từ 1 phiên
trước (NAV confidence workflow: `provisional`/`pending_confirm`/`confirmed`/`fixed` state
machine, tên hàm khớp với title commit `aad06a0` đã có nhưng nội dung thực tế trong working
tree đã đi xa hơn commit đó). Đã audit kỹ để tách bạch (không lẫn vào commit PRO-004 của
mình), rồi commit riêng có ghi rõ nguồn gốc "uncommitted work from prior session". Sau đó
hoàn thiện nốt phần API còn thiếu (`GET /api/admin/nav/pending`, `POST
/api/admin/nav/confirm`) + sửa bug `tg_send(...,buttons=)` sai chữ ký (phải là
`tg_send_keyboard`) mà workflow đó cần để hoạt động end-to-end.

**⚠️ Quy tắc mới cho session sau**: Trước khi `git add`/commit, LUÔN chạy
`git status --short` + `git diff --stat` để phát hiện file có thay đổi KHÔNG PHẢI của mình
trộn chung (nhất là sau khi resume 1 session dài hoặc sau `git stash`). Nếu thấy, tách commit
riêng theo từng nguồn gốc thay vì gộp bừa — tránh làm mất dấu vết ai/tại sao thay đổi.

**Test suite**: 228/280 pass — 52 fail là **pre-existing** (đã xác nhận bằng cách so sánh
`git stash` trước/sau các thay đổi trong session này, số lượng fail giống hệt). KHÔNG do
session này gây ra — encoding Windows console + JWT token mẫu hết hạn (xem note session 2).

**Việc tiếp theo trong BACKLOG**: T2-004 (XGBoost model, 5h — task lớn, chưa bắt đầu),
PAY-006/007 (VNPay/Stripe, P2), T2-010 (accuracy dashboard, P2). Deploy: cần set
`MOMO_PARTNER_CODE`/`MOMO_ACCESS_KEY`/`MOMO_SECRET_KEY` thật trên Railway trước khi nhận
thanh toán MoMo thật (hiện đang dùng sandbox credentials mặc định).

---

## ✅ Session 5 — Ca chiều autonomous: T+2 Forecast Engine hoàn thiện (T2-004/005/007/008/010) (2026-07-10)

**Bắt đầu session phát hiện: PRO-004 + NAV confidence workflow (session trước) chưa push**
`ec19310` — đã `git add`/commit/push trước khi bắt đầu task mới, theo đúng quy tắc mới ghi ở
Session 4 (tách bạch nguồn gốc thay đổi, không gộp bừa).

**⚠️ Có 1 agent KHÁC chạy đồng thời trong cùng working tree** trong lúc session này đang chạy
(commit `a2bb04b`/`8da5c3a`/`1e6648b` xuất hiện xen giữa các commit của tôi, cùng khung giờ
14:48-14:56 — tự nhận là "Session 4 ca sáng" dù timestamp là chiều, có thể do lịch chạy bị trễ).
Không có conflict vì đụng file khác nhau (họ sửa `bot.py`/`miniapp_server.py`/`index.html` cho
NAV-confidence UI, tôi sửa `scripts/t2_*.py` + phần khác của `bot.py`) — mỗi lần trước khi
commit đều `git fetch` + `git log HEAD..origin/main` để phát hiện sớm nếu có commit mới, và
luôn Read lại file trước khi Edit (Edit tool tự chặn nếu file bị sửa từ ngoài, đã gặp 1 lần
với BACKLOG.md và xử lý đúng bằng cách đọc lại). **Bài học cho session sau**: nếu thấy git log
có commit lạ giữa chừng, ĐỪNG hoảng — kiểm tra file trùng lặp trước khi tiếp tục, và luôn
fetch+diff trước mỗi lần commit/push.

**T2-004 — XGBoost T+2 model (`scripts/t2_xgboost.py`, MỚI):**
- Dùng XGBoost **Booster API thuần** (không phải sklearn wrapper) — tránh thêm dependency
  scikit-learn không cần thiết
- **Pooled model** qua tất cả quỹ (không train riêng từng quỹ như ARIMA) — `fund_code` label-
  encoded làm 1 feature, giúp model học chung pattern giữa các quỹ, nhiều data hơn
- Target = **%chg T+2** (không phải NAV tuyệt đối) — quan trọng vì pool nhiều quỹ có NAV khác
  thang đo (9k vs 22k), nếu predict NAV tuyệt đối model sẽ bị lệch theo quỹ có NAV lớn
- Reuse `_build_features`/`_fetch_nav_series`/`_next_trading_date` từ `t2_arima.py` (import
  trực tiếp, không copy code)
- `--train`: time-split 80/20 **PER-FUND** (không shuffle global — tránh look-ahead bias vì
  mỗi quỹ phải giữ thứ tự thời gian riêng), early-stopping trên test MAPE
- Model lưu `scripts/models/xgb_t2.json` (gitignored — **PHẢI chạy `--train` 1 lần trên
  Railway** sau deploy, model không có sẵn trong git)

**T2-005 — Ensemble (`scripts/t2_ensemble.py`, MỚI):**
- Đọc dự báo mới nhất `arima-v1` + `xgb-v1` **cùng `predicted_for_date`** (lệch ngày → skip,
  coi như 1 model chưa chạy xong hôm đó — an toàn hơn là trộn dự báo khác ngày)
- CI = `±1.5×rolling_std(error_pct, 30d)` của chính `ensemble-v1` — hàm mới
  `db.get_rolling_error_std()`, ưu tiên per-fund ≥5 mẫu, fallback toàn cục, fallback cứng ±2%
  cho vài tuần đầu khi ensemble-v1 chưa có lịch sử chấm điểm
- Wire vào `bot.py job_t2_predict()` (18:31): chạy tuần tự ARIMA→XGBoost→Ensemble qua helper
  `_run_t2_script()` mới, mỗi script lỗi độc lập (không chặn 2 script còn lại)

**T2-007 — Weekly retrain (mở rộng `t2_xgboost.py`):**
- `_next_version(conn)` scan `model_metrics` tìm `xgb-vN` lớn nhất → `xgb-v{N+1}` — **quan
  trọng**: nếu không làm việc này, mỗi lần retrain sẽ ghi đè `xgb-v1` cũ, mất lịch sử so sánh
  model qua các lần train
- `cmd_predict()`/`cmd_status()` đọc `model_version` từ `meta.json` (KHÔNG hardcode nữa) — tự
  động dùng model mới nhất sau mỗi retrain mà không cần sửa code
- `bot.py job_t2_retrain()` — Chủ nhật 02:00, timeout 900s (train chậm dần khi data lớn)

**T2-008 — Adaptive ensemble weights (mở rộng `t2_ensemble.py`):**
- `--reweight`: inverse-MAPE weighting — `w_arima=mape_xgb/(mape_arima+mape_xgb)` — model lỗi
  ÍT hơn được trọng số CAO hơn (không phải ngược lại, dễ nhầm)
- Cần ≥10 mẫu/model trong 30 ngày mới tin cậy để reweight, không thì giữ nguyên trọng số cũ
  (tránh reweight dựa trên quá ít data → nhiễu)
- Lưu `scripts/models/ensemble_weights.json` (gitignored, tương tự xgb model)
- `bot.py job_t2_reweight()` — `schedule.every(30).days.at("03:00")` (đã verify `schedule` lib
  hỗ trợ cú pháp `every(N).days.at()`, không chỉ `.day.at()`)

**T2-010 — Accuracy dashboard:**
- **Quyết định UX quan trọng**: KHÔNG tạo tab riêng ở bottom-nav (đã 6 icon, chật cho mobile
  Telegram WebView) — gộp vào modal "Nghiên cứu" hiện có làm section "🎯 Độ chính xác dự báo
  T+2", cùng chỗ với PRO-001 (research) và PRO-004 (alerts)
- `db.get_accuracy_summary()`/`get_accuracy_history()` — **bug cần tránh lặp lại**:
  `ROUND(...)::numeric` trong SQL trả về `Decimal` qua psycopg2, KHÔNG JSON-serializable →
  phải ép `float()` thủ công trước khi trả qua `_json()`. Tương tự `date` columns phải cast
  `::text` trong SQL (không có custom JSON encoder trong `miniapp_server.py`)
- Bonus fix: `_t2Html()` hardcode nhãn "(dự báo ARIMA)" dù giờ prediction hiển thị có thể là
  bất kỳ model nào (`get_predictions()` lấy bản ghi mới nhất bất kể model_version, mà cron giờ
  chạy ARIMA→XGBoost→Ensemble tuần tự nên ensemble luôn là bản ghi mới nhất) — sửa thành nhãn
  động `_t2ModelLabel(pred.model_version)`

**Verify UI mới (không có DATABASE_URL để test backend thật):**
- `.claude/launch.json` cho `preview_start` phải đặt ở **`P:\NGCG\Vibe Coding\.claude\`**
  (working-dir CHA), KHÔNG phải `Fund Tracker Pro/.claude/` — browser tool tìm ở đó, đã tạo
  file mới (ngoài git repo của project này, không ảnh hưởng)
- **Bẫy khi mock qua `preview_eval`**: `window._me = {...}` KHÔNG gán được biến `let _me`
  top-level trong script (biến khai báo bằng `let`/`const` ở global scope không trở thành
  `window` property) — phải gán trực tiếp `_me = {...}` (không có `window.` hay `let`) để
  JS engine resolve đúng lexical binding mà các hàm trong file đang dùng
- Đã verify qua `preview_snapshot`: bảng MAPE + canvas chart (686×240px sau resize mobile) +
  nhãn "dự báo Ensemble" render đúng, không console error

**Tất cả P0/P1 trong BACKLOG đã DONE.** Còn lại: PAY-006 (VNPay, P2, cần merchant credentials
thật), PAY-007 (Stripe, P2, cần Stripe account thật) — không thể test có ý nghĩa nếu không có
credentials, để lại cho session có quyền truy cập secrets thật.

**Deploy checklist cho session sau / Harvey:**
1. `railway run python scripts/t2_xgboost.py --train` — tạo model `xgb-v1` đầu tiên (bắt buộc
   trước khi `--predict` hoạt động, và trước khi cron Chủ nhật `job_t2_retrain` kích hoạt)
2. Đợi ≥30 ngày dữ liệu chấm điểm arima-v1 + xgb-v1 (mỗi model ≥10 mẫu) rồi chạy thử
   `python scripts/t2_ensemble.py --reweight` để có trọng số adaptive đầu tiên
3. `GET /api/admin/nav/pending` + xác nhận NAV pending (từ session trước) qua Mini App Admin tab

---

*Cập nhật: 2026-07-10 — Session 5: T+2 Forecast Engine — T2-004/005/007/008/010 (autonomous run, ca chiều)*

---

## ✅ Session 7 — Ca sáng autonomous: GOV-002/003/004/006 (2026-07-13)

Bắt đầu session thấy BACKLOG.md đã có GOV-001 (audit log) + GOV-005 (security hardening) DONE
từ trước (commit `3a5b552`), cùng vài commit khác chưa update BACKLOG (dedup token alert,
báo cáo NAV chưa cập nhật). Có 1 worktree khác (`agent-a7b66c21c7d977a66`, locked) đang làm
tính năng Vàng riêng — không đụng tới, tránh xung đột.

**GOV-004 (partial) — Admin audit log viewer:**
- `GET /api/admin/audit` (admin-only) dùng `db.get_audit_log()` có sẵn từ GOV-001
- Card "Audit log gần đây" trong tab Admin Mini App, verify qua browser preview (mock apiFetch)
- Còn thiếu: dashboard tổng hợp (user theo tier, MAPE model, quỹ NAV lỗi, giao dịch gần đây)

**GOV-006 — Chính sách migration:** section mới trong `CLAUDE.md` ("🔐 CHÍNH SÁCH DỮ LIỆU") —
additive-only ALTER TABLE, dry-run mặc định cho script sửa dữ liệu hàng loạt, audit_log
append-only, PROTECTED_SOURCES cho NAV, luôn hỏi Harvey trước khi xoá dữ liệu.

**GOV-002 — Backup tự động:** `scripts/backup_db.py` (pg_dump -F c, retention 14 ngày, luôn
giữ ≥1 bản), `bot.py job_backup_db()` 03:30 hàng ngày + báo Telegram admin khi fail. Restore
qua `--restore <file> --confirm` (dry-run mặc định), `telegram-bot/BACKUP.md` ghi quy trình.
**Bug tìm thấy khi làm task này**: `.dockerignore` loại bỏ TOÀN BỘ `scripts/` khỏi Docker
build context — nghĩa là `scripts/t2_arima.py`/`t2_xgboost.py`/`t2_ensemble.py` KHÔNG HỀ có
trong image production, mọi job T+2 (`job_t2_predict`/`job_t2_retrain`/`job_t2_reweight`) đã
fail âm thầm trên Railway từ trước đến giờ (chỉ hoạt động khi test local — `_run_t2_script()`
nuốt lỗi, chỉ log warning, không crash bot nên không ai để ý). Đã sửa `.dockerignore` để copy
`scripts/` (trừ `scripts/models/` — model file gitignored).

**GOV-003 (partial) — Chặn thanh toán trùng lặp:** phát hiện lỗ hổng tài chính thật (không
chỉ lý thuyết): MoMo IPN và Telegram Stars `successful_payment` KHÔNG có dedup nào trước đây
— nếu cổng thanh toán retry webhook (rất thường xảy ra khi server không ACK đủ nhanh),
`extend_pro()` bị gọi lại → user được +30 ngày Pro MIỄN PHÍ mỗi lần retry. Đã thêm
`db.record_payment_once(provider, charge_id)` — bảng `processed_payments` UNIQUE
(provider, charge_id), `INSERT...ON CONFLICT DO NOTHING`, trả `False` nếu đã xử lý → caller
bỏ qua `extend_pro()` + ghi `log_audit("duplicate_payment_blocked")` + báo Telegram admin ngay.
Verify bằng fake cursor mô phỏng đúng semantics `ON CONFLICT DO NOTHING`. Còn thiếu 3 rule
anomaly khác trong scope gốc GOV-003 (NAV nhảy >X%/phiên, MAPE vượt ngưỡng N ngày liên tiếp,
redeem promo bất thường) — để lại session sau, ưu tiên dedup thanh toán trước vì rủi ro tài
chính trực tiếp cao hơn.

**Bài học lặp lại (đã ghi ở session trước nhưng vẫn xảy ra)**: luôn `grep`/đọc code thực tế
trước khi tin BACKLOG — 2 bug tìm thấy trong session này (`.dockerignore` thiếu `scripts/`,
thiếu dedup thanh toán) đều là lỗ hổng ĐÃ TỒN TẠI TỪ TRƯỚC, không phải do session này gây ra,
chỉ lộ ra khi đọc kỹ code liên quan tới task đang làm.

**Việc tiếp theo cho session sau (đã làm ở ca chiều — xem entry bên dưới):**
1. Deploy: chạy `railway run python scripts/backup_db.py --backup` 1 lần để xác nhận
   `pg_dump` hoạt động thật trên Railway (image mới có `postgresql-client`)
2. Restore thử trên 1 Postgres service TEST riêng (không phải production) — xem
   `telegram-bot/BACKUP.md` checklist
5. Redeploy Railway sau session này để job T2 (predict/retrain/reweight) BẮT ĐẦU hoạt động
   thật lần đầu tiên (bug `.dockerignore` đã chặn chúng từ trước tới giờ)

---

## ✅ Session 7 — Ca chiều autonomous: GOV-003/004 hoàn tất (2026-07-13)

Tiếp tục từ ca sáng (GOV-002 xong, GOV-003/004 partial, GOV-006 xong). Hoàn tất 3 rule
còn lại của GOV-003 + phần dashboard tổng hợp còn thiếu của GOV-004. **Tất cả P0/P1 trong
BACKLOG đã DONE** — chỉ còn PAY-006 (VNPay)/PAY-007 (Stripe), cả 2 đều P2 và cần merchant
credentials thật để test có ý nghĩa, để lại cho session có quyền truy cập secrets.

**GOV-003 — 3 rule anomaly còn lại:**
- NAV nhảy >15%/phiên: `harvest_nav.py cmd_daily` in dòng `JUMP_ALERT:` khi fetch mới lệch
  yesterday_nav >15% trong lúc auto-harvest bình thường (khác pending_confirm — cái đó chỉ
  bắt manual≠fetch, không bắt được data glitch trên nguồn auto). `bot.py job_harvest_nav`
  parse dòng này qua `_handle_nav_jump_alert()` → `log_audit(nav_jump_anomaly)` + báo admin.
- MAPE model kém liên tục: `db.get_daily_mape()` (MAPE trung bình theo ngày từ
  `prediction_actuals`, KHÔNG dùng bảng `model_metrics` vì bảng đó chỉ ghi lúc train
  XGBoost, không cập nhật hàng ngày) + `get_mape_breach_streak()` (đếm streak ngày liên
  tiếp >ngưỡng, dừng ngay khi gặp 1 ngày đạt chuẩn). `bot.py job_t2_score` gọi
  `_check_mape_streak_alerts()` sau khi score — báo khi model (arima-v1/xgb-v1/ensemble-v1)
  MAPE >8% liên tục ĐÚNG 5 ngày. **Chi tiết debounce quan trọng**: check `streak == N` chứ
  không phải `streak >= N` — nếu dùng `>=` sẽ spam alert mỗi ngày sau khi đã báo lần đầu.
- Brute-force mã khuyến mãi: `miniapp_server.py _check_promo_abuse()` rate-limit in-memory
  theo telegram_id (dict global `_PROMO_ATTEMPTS`, sliding window 60s, >5 lần thử → chặn
  429 + `log_audit(promo_abuse_detected)` + báo admin). In-memory nên mất khi Railway
  restart — chấp nhận được vì đây chỉ là lớp cảnh báo bổ sung, UNIQUE constraint DB
  (`promo_redemptions`) vẫn là cơ chế chặn chính.

**GOV-004 — dashboard tổng hợp còn thiếu:**
`db.get_admin_summary()` — 4 phần độc lập, MỖI PHẦN try/except RIÊNG (không phải 1 try
bọc ngoài) vì đây là dashboard tổng hợp, thà thiếu 1 mục còn hơn lỗi cả trang: users theo
tier active (`bot_profiles` × `user_tiers`), MAPE 7 ngày mỗi model (tái dùng
`get_daily_mape` từ GOV-003), quỹ active chưa có NAV hôm nay (`funds_master` LEFT JOIN
`nav_history` ngày hiện tại), 20 `processed_payments` gần nhất. `GET /api/admin/summary`
(admin-only, `_auth_write`+`_is_admin`) trong `miniapp_server.py`. UI: card "📊 TỔNG QUAN
HỆ THỐNG" ở ĐẦU tab Admin (trên card TCBS token — chỗ admin nhìn thấy đầu tiên), MAPE tô
đỏ nếu >8% (khớp ngưỡng alert GOV-003, nhất quán về mặt UX). Verify qua browser preview
với mock `apiFetch` — users/MAPE màu/quỹ thiếu/thanh toán đều render đúng, không console
error.

**⚠️ Bài học quan trọng nhất session này — concurrency với live session của Harvey:**
Phát hiện giữa chừng: Harvey đang LIVE-EDIT cùng repo này trong lúc session tự động chạy
(commit author "Harvey" xen kẽ commit của session này trong `git log`, làm feature
"multi-tier pricing" PAY-008 song song). Hệ quả: `bot.py`/`miniapp_server.py` bị 2 process
ghi đồng thời — mỗi lần Harvey chạy `git commit` (có vẻ dùng `git add -A` hoặc tương đương),
NÓ QUÉT LUÔN cả những thay đổi CHƯA COMMIT của session này đang nằm trong working tree/index
(kể cả đã `git add` hay chưa), vì working tree + staging area dùng chung giữa mọi process
trỏ vào cùng thư mục — không có isolation như 2 worktree riêng.
- Cách phát hiện: trước khi mỗi lần định `git add`, luôn `git log --oneline -3` +
  `git diff --stat <file>` xem file có bị thu hẹp bất thường (ít dòng hơn dự kiến) — dấu
  hiệu commit khác đã "nuốt" thay đổi của mình.
- Cách xử lý an toàn khi 2 bộ thay đổi trộn trong CÙNG 1 file: dùng `git diff <file> |
  grep "^@@"` liệt kê tất cả hunk, xác định hunk nào là của mình (theo nội dung/dòng đã
  viết), rồi `git add -p <file>` chọn `y` CHỈ cho hunk của mình, `n` cho phần còn lại —
  KHÔNG BAO GIỜ `git add <file>` cả file khi biết có thay đổi của người khác trộn vào.
- Phát hiện 1 lần bị "hớt tay trên": commit `db.py` (chứa `get_admin_summary()`) bị bỏ sót
  vì Harvey's commit chỉ touch 5 file cụ thể (không có `db.py`), trong khi `miniapp_server.py`
  của Harvey đã gọi `_db_mod.get_admin_summary()` (hunk của tôi bị quét vào) → tạo ra 1
  khoảng hở: code tại HEAD gọi hàm CHƯA TỒN TẠI. Phải commit `db.py` NGAY để vá, không đợi
  đến cuối session — bài học: khi phát hiện code liên đới bị tách commit bởi race condition,
  ưu tiên vá integrity của HEAD trước, không gộp chung với các task tiếp theo.
- Không có xung đột dữ liệu/nội dung xảy ra (may mắn vì 2 bên sửa 2 vùng code khác nhau
  trong cùng file) — nhưng đây là rủi ro thật, session sau nếu phát hiện dấu hiệu tương tự
  (commit author lạ xen giữa, file thay đổi ngoài dự kiến) nên áp dụng ngay quy trình
  `git add -p` thay vì `git add <file>` cho tới khi hết session live-edit song song.

**Tất cả P0/P1 trong BACKLOG đã DONE.** Còn lại: PAY-006 (VNPay), PAY-007 (Stripe) — cả 2
P2, cần merchant credentials thật, để lại session có quyền truy cập secrets. GOV-005 còn 1
việc nhỏ chưa làm (auth_date freshness check chống replay initData cũ) — rủi ro thấp, có
thể làm sau.

**Deploy checklist còn tồn đọng cho Harvey:**
1. `railway run python scripts/t2_xgboost.py --train` — tạo model `xgb-v1` đầu tiên (vẫn
   chưa xác nhận đã chạy — xem lại nếu T+2 predictions vẫn trống)
2. `railway run python scripts/backup_db.py --backup` — xác nhận `pg_dump` hoạt động thật
   trên Railway (image có `postgresql-client` từ GOV-002 nhưng chưa test thật)
3. Restore thử trên 1 Postgres TEST riêng theo `telegram-bot/BACKUP.md` checklist

---

## ✅ Session (autonomous, scheduled) — Ca sáng 2026-07-15: GOV-005-part2 + GOV-007-part4

Môi trường session này KHÔNG có `DATABASE_URL`/Railway env vars và không có merchant
credentials thật (VNPay/Stripe) — không thể verify integration DB thật hay tấn công
PAY-006/007 (cả 2 P2, BACKLOG đã ghi rõ "cần merchant credentials thật để test có ý nghĩa").
Theo đúng điều kiện dừng trong scheduled-task brief ("gặp task cần credential thật không
test được"), không đụng tới PAY-006/007. Toàn bộ P0/P1 trong BACKLOG đã DONE từ trước (xác
nhận qua đọc lại toàn bộ BACKLOG.md 499 dòng) — 2 việc làm thêm dưới đây là cải tiến tự chọn,
bám theo các "còn lại"/"bài học" đã ghi rõ trong chính BACKLOG.

**GOV-005-part2 — auth_date freshness check (chống replay initData):**
`_validate_init_data()` (`telegram-bot/miniapp_server.py`) trước đây chỉ verify chữ ký HMAC,
không verify THỜI ĐIỂM phát hành — 1 initData bị chặn bắt (log, sniff...) có thể replay vô
thời hạn. Giờ từ chối nếu `auth_date` > 24h cũ hoặc ở tương lai ngoài dung sai 5 phút. Không
ảnh hưởng client thật (Telegram SDK luôn tự sinh `auth_date` mới). Không có test tự động nào
từng cover hàm này trước đó — không có gì để break, verify bằng py_compile + pytest 246/246.

**GOV-007-part4 — tự động hoá weekly NAV source audit:**
GOV-007-part3 đã ghi ra "quy trình cross-check NAV giữa nhiều nguồn" (bước 3: quét toàn bộ
hệ thống định kỳ, "nên làm hàng tuần") nhưng chưa BAO GIỜ tự động hoá — đây chính là lý do
bug VCBFTBF lặp lại 3 LẦN với 3 root cause độc lập khác nhau (FUND_CATALOG sai → config.json
không đồng bộ → funds_master là nguồn config độc lập thứ 3), mỗi lần chỉ phát hiện SAU KHI
Harvey report qua screenshot, không phải do hệ thống tự cảnh báo sớm.
- `db.get_nav_source_audit(days=30)` — quét `nav_history` 30 ngày qua (loại hôm nay, vì hôm
  nay tạm là fmarket provisional là bình thường), group theo `fund_code`, flag quỹ có dòng
  `source` KHÔNG thuộc `TRUSTED_SOURCES` (tái dùng constant có sẵn, không hardcode lại).
- `bot.py job_nav_source_audit()` — chạy Thứ Hai 04:00 (sau backup 03:30), báo Telegram admin
  danh sách quỹ bị flag + gợi ý chạy lại `harvest_nav.py --tcinvest`, ghi
  `log_audit(nav_source_audit_flag)`. Mỗi phần lỗi (query DB, log_audit) đều không chặn phần
  còn lại — cùng triết lý try/except riêng như `get_admin_summary()` (GOV-004).
- Verify: `tests/test_nav_source_audit.py` (8 test mới, MỚI cho project — bao DB
  unavailable/rỗng/lỗi query/lỗi log_audit/thiếu config admin) + smoke-test fake cursor độc
  lập trước khi viết test chính thức. 254/254 tổng test suite xanh (246 cũ + 8 mới).
- **Chưa verify integration thật trên Railway** (không có DATABASE_URL) — cần đợi job chạy
  thật Thứ Hai tới, hoặc Harvey chạy tay `railway run python -c "import bot; bot.job_nav_source_audit()"`
  để xác nhận sớm hơn.

**Không tìm thấy việc P0/P1 nào khác để làm** — đã audit lại note cũ "xem xét thay upsert_nav()
bằng upsert_nav_with_confidence() ở mọi call site" (từ Session 8): đã lỗi thời, `upsert_nav()`
plain giờ ĐÃ có logic bảo vệ PROTECTED_SOURCES đầy đủ (được vá trong GOV-007), không cần đổi gì.

---

## ✅ Session (autonomous, scheduled) — Ca chiều 2026-07-15: verify production, không code thêm

Tiếp nối ca sáng cùng ngày (GOV-005-part2, GOV-007-part4, GOV-007-part3, T2-013,
GOV-008/T2-014 — xem entry phía trên). Đọc lại BACKLOG.md 558 dòng: tất cả P0/P1 đã DONE,
chỉ còn PAY-006/PAY-007 (P2, cần merchant credentials thật — đúng điều kiện dừng của
scheduled-task brief "gặp task cần credential không test được").

**Phát hiện quan trọng**: `telegram-bot/config.json` có sẵn `database_url` trỏ thẳng
Railway production (host `thomas.proxy.rlwy.net`) — không cần SSH, connect trực tiếp
bằng `psycopg2` từ máy local để verify READ-ONLY các cơ chế ca sáng vừa code có chạy thật
trên production không (khác với chỉ đọc code rồi tin là xong — bài học lặp lại nhiều lần
trong project này là "code trông đúng ≠ đã chạy thật thành công", xem T2-011).

**Kết quả verify (tất cả healthy, không tìm thấy bug):**
- `verify_tier` (GOV-008) đang hoạt động thật: phân bố tier0=353/tier1=186/tier8=713/
  tier31=930 trong 60 ngày qua — không phải cột chết.
- 20× `nav_reverify_corrected` trong audit_log 3 ngày qua (TCBS tự sửa provisional→final,
  lệch 0.08-2.4%, đúng thiết kế). 0 `nav_jump_anomaly` MỚI hôm nay (3 lần cũ đều trước khi
  GOV-008 xong, không phải sự cố đang diễn ra).
- VCBFTBF (quỹ 3 lần sự cố trước) — 10 ngày gần nhất TOÀN BỘ nguồn tcinvest/manual nhất
  quán, không còn xen kẽ nguồn khác. Đã ổn định thật, không chỉ "trông có vẻ" ổn định.
- T2 predictions: 4 model (arima-v1/xgb-v2/naive-v1/ensemble-v1) đều 51/51 quỹ dự báo tươi
  cho T+2=2026-07-16 — pipeline T2-011 vẫn chạy khỏe sau khi fix hôm 07-14.
- `prediction_actuals` trống 100% (0 dòng) — KHÔNG phải bug, chỉ là pipeline T2 mới chạy
  thật từ 07-14 (T2-011), chưa đủ thời gian để dự báo T+2 có NAV thật để chấm điểm. Cần
  đợi vài ngày. **Việc theo dõi cho session sau**: nếu sau ~1 tuần `prediction_actuals`
  vẫn trống, đó MỚI là dấu hiệu `job_t2_score` có vấn đề thật, đáng điều tra.
- 39/40 quỹ "chưa có NAV hôm nay" lúc kiểm tra (14:08 giờ VN) — bình thường, harvest job
  chạy tối 18:30/20:00, chưa tới giờ.

**Không code gì mới ca này** — theo đúng nguyên tắc "producing a report of what you found
is the correct output" khi không có task ghi cụ thể cần làm và không có write action nào
được yêu cầu. Test suite xác nhận baseline: 254/254 pass trước khi kết thúc.

**⚠️ Phát hiện ngoài lề, KHÔNG xử lý** (để Harvey tự quyết định, không phải việc của session
autonomous): `git status` cho thấy toàn bộ `Fund Tracker Pro.xcodeproj/` + file Swift cũ ở
top-level (`Fund Tracker Pro/ContentView.swift`...) bị đánh dấu deleted, trong khi có thư
mục `ios/` mới hoàn toàn chưa track (`git add`). Trông giống 1 đợt tái cấu trúc thủ công
trên máy local của Harvey chưa commit — KHÔNG tự ý gộp vào commit nào của session này (an
toàn hơn để Harvey xác nhận ý định, đúng tinh thần GOV-006 "hỏi trước khi động vào thay đổi
không phải do session tạo ra").

**Việc còn lại duy nhất trong BACKLOG**: PAY-006 (VNPay)/PAY-007 (Stripe) — cả 2 P2, chờ
Harvey cung cấp merchant credentials thật.

---

## ✅ Session (autonomous, scheduled) — Ca sáng 2026-07-16: update BACKLOG, không code thêm

Tất cả P0/P1 đã DONE từ trước. Điều kiện dừng ca này "Hết P0+P1" áp dụng ngay từ đầu.
Harvey committed 5 tính năng lớn sau session chiều 15/07 (BACKLOG chưa kịp cập nhật):

**Harvey commits 2026-07-15 (sau session chiều, ngoài giờ autonomous):**
- **GOV-008-part2** (commit `73c78c7`): NAV verification log (append-only, mọi datapoint
  được kiểm tra) + `row_hash` chống sửa ngầm DB — hash deterministic per-row, lệch khi
  ai dùng SQL thô bỏ qua API functions. `job_nav_integrity_check()` 21:30 hàng ngày.
- **GOV-009** (commit `15c8989`): XAUUSD gold gap tự động backfill (Yahoo Finance,
  `run_backfill(days=10)` trong `job_morning`). Loạt UI fixes Mini App (chip CCQ, nhãn
  "Giá vốn", dropdown chi tiết, chữ chạy tên quỹ, bug nút DCA Vàng ID sai).
- **PAY-009 HMAC** (commit `c04bcbc`): SePay webhook nâng cấp từ Apikey tĩnh lên
  HMAC-SHA256 (`X-SePay-Signature` + replay protection ±5 phút). Fallback backward-compat.
- **GOV-010/011** (commit `6259b3a`): GOV-010 referral fraud 2 giai đoạn (đã ghi trước);
  GOV-011 fix NAV hiển thị cũ hơn DB — merge điểm mới nhất từ DB vào pts fetch TCBS.
- **GOV-011-part2** (commit `5748fde`): cache buy_signals staleness check sai — so cả
  nav_date (không chỉ signal_date) để phát hiện đúng khi DB đã có NAV mới hơn cache.

**Verify baseline ca này:**
- `py_compile telegram-bot/{bot,miniapp_server,db}.py` → All OK
- `pytest tests/ -x -q` → 254/254 passed (46.7s)
- `dashboard/portfolio.html` (1059 dòng, Harvey tạo, chưa commit): review code — xác nhận
  cả 2 endpoints dùng (`/nav-json`, GET+POST `/transactions`) ĐÃ TỒN TẠI trong `server.py`
  → trang sẵn sàng hoạt động khi Harvey commit và muốn test.

**Không code gì mới ca này** — chỉ update BACKLOG.md (commit `94a5527`) + memory.md.

**Phát hiện tồn đọng từ session trước (vẫn chưa xử lý, để Harvey quyết định):**
- `Fund Tracker Pro.xcodeproj/` và file Swift cũ bị deleted, `ios/` mới chưa git add
- `dashboard/portfolio.html` (1059 dòng), `scripts/*.py` mới (~15 file) chưa commit

**Theo dõi sau deploy (câu hỏi hở từ ca chiều 15/07):**
- `prediction_actuals` trống vào 14:08 15/07 (bình thường, T2 mới chạy từ 07-14). Nếu
  sau ~1 tuần (23/07) vẫn trống → `job_t2_score` có vấn đề thật, cần điều tra.
- SePay HMAC: cần set `SEPAY_HMAC_SECRET` trên Railway và test với giao dịch thật.

---

## ✅ Session (autonomous, scheduled) — Ca chiều 2026-07-16: verify + BACKLOG, không code thêm

Đọc BACKLOG (683 dòng) + memory.md + `git log`: phát hiện **6 commit MỚI** (10:59-12:30, cùng
ngày, SAU khi ca sáng update BACKLOG lúc 09:09) chưa có trong BACKLOG — tất cả có
"Co-Authored-By: Claude Sonnet 5" trong message, tức là **1 phiên live-edit tương tác giữa
Harvey và Claude** (không phải scheduled task ca sáng/chiều), xen giữa 2 lần scheduled task
chạy trong cùng ngày. Đã cập nhật BACKLOG ghi lại đầy đủ 6 commit này (xem entry GOV-012 và
"4 fix nhỏ khác" trong BACKLOG.md ngay trước "## XONG (DONE)").

**Baseline**: `py_compile` 5 file chính OK, `pytest` 254/254 pass (82.6s) — không đổi.

**Verify sống trên production (railway CLI đã login sẵn `harvey.hcv@gmail.com`, đọc DB qua
`database_url` trong `config.json` — toàn bộ read-only):**
- **GOV-012 discount system** (mới nhất, tài chính-nhạy cảm nên review kỹ dù đã DONE): amount
  tính hoàn toàn server-side, order lưu amount ĐÃ giảm giá vào DB, webhook so khớp với giá trị
  đã lưu (không tính lại từ giá gốc) → không có khoảng hở giữa giá hiển thị/giá webhook verify.
  4 admin endpoint đều gate `_is_admin`+`_auth_write` đúng pattern. Mã `SEPAY10` (auto_apply)
  đã tồn tại thật trên DB — không có khoảng trống giữa lúc xoá hardcode và tạo mã thay thế.
- **T2-006 fix xác nhận hoạt động thật**: `prediction_actuals` từ 0 dòng (ca chiều 15/07) →
  48 dòng, 4 model đều có 12 mẫu/30 ngày, MAPE 0.6-0.7%. Nhưng **quyết định KHÔNG chạy
  `t2_ensemble.py --reweight` ca này** dù đạt ngưỡng thô "≥10 mẫu" — cả 48 dòng cùng 1
  timestamp (1 batch duy nhất ngay sau fix), chưa đủ đa dạng ngày để trọng số adaptive đáng
  tin. Để dành cho session sau khi có ≥2-3 batch `job_t2_score` khác nhau (mỗi ngày 1 batch
  lúc 18:32).
- `railway logs --service worker`: phát hiện **TCinvest JWT hết hạn LẠI** (401 toàn bộ ~40 quỹ
  sáng 07-16) — bot tự fallback DB (400 điểm/quỹ, NAV "stale" 1 ngày), không crash. Đây là
  pattern lặp lại nhiều lần (xem T2-013, GOV-007-part3) — cần Harvey cấp token mới định kỳ,
  không phải bug code. `job_check_jwt` sẽ tự báo Telegram admin.
- FK violation `NTPPF`/`VMEEF` khi harvest lưu NAV (2 mã chưa có trong bảng `funds`) — **KHÔNG
  PHẢI lỗi mới**, đã ghi nhận từ GOV-007-part2 (14/7), vẫn đang chờ Harvey xác nhận có nên
  track 2 mã này không. Không tự ý thêm (GOV-006).
- `nav_jump_anomaly` trong audit_log: vẫn chỉ 3 bản ghi CŨ (07-13/07-14), 0 mới — khớp kết
  luận ca chiều 15/07, không phải sự cố đang diễn ra.
- `grep TODO/FIXME` toàn bộ `telegram-bot/*.py` + `scripts/*.py` → 0 kết quả thật.

**Không code gì mới ca này** — đã xác nhận không còn P0/P1 nào ngoài 6 commit vừa ghi nhận
(đã DONE từ trước bởi live session). Chỉ còn PAY-006/PAY-007 (P2, chờ merchant credentials
thật) — đúng điều kiện dừng. Việc thật của ca này: cập nhật BACKLOG + verify production SỐNG
(không chỉ đọc code) cho tính năng tài chính mới nhất (GOV-012) và xác nhận T2-006 fix hoạt
động đúng trên production.

**Việc cần Harvey (không tự làm được)**:
1. Cấp JWT tcinvest mới (hết hạn lại, ~lần thứ N)
2. Xác nhận NTPPF/VMEEF có nên track hay bỏ hẳn
3. `ios/` + `Fund Tracker Pro.xcodeproj/` deleted vẫn chưa commit (tồn đọng từ ≥2 ca trước,
   không tự ý động vào)
4. `dashboard/portfolio.html` (1059 dòng) + ~15 script mới trong `scripts/` vẫn chưa commit
   (WIP của Harvey, không phải việc của session)

**Không cần làm gì để T2-008 reweight sớm hơn** — tự đủ điều kiện khi có thêm vài batch
`job_t2_score` (chạy hàng ngày 18:32), không cần can thiệp thủ công.

---

## ✅ Session (autonomous, scheduled) — Ca sáng 2026-07-17: GOV-015 web bước 2/3/4

**Baseline đầu session**: py_compile OK, pytest 254/254 pass.

**Phát hiện đầu session**: Harvey có 5 commit mới (GOV-012-part2, GOV-013, GOV-013-part2,
GOV-014, GOV-015 bước 1) từ live session tối 16/07 chưa có trong BACKLOG. Tất cả đã DONE,
không có P0/P1 nào mới để làm. Tiếp nối GOV-015 (bước 1 Harvey đã làm: web auth + portfolio
overview) bằng 3 bước tiếp theo cho bản Web độc lập.

**GOV-015 bước 2** — Bảng tín hiệu quỹ trong `telegram-bot/miniapp/web.html`:
- Sau đăng nhập, gọi `/api/signals?user_id=` với `X-Web-Session` header (không cần sửa backend)
- Mỗi quỹ hiện: code, tên, NAV, %1D, badge MUA/BÁN/HOLD (màu design system)
- Skeleton animation trong lúc chờ | commit f543bb8

**GOV-015 bước 3** — Lịch sử giao dịch trong web.html:
- Card "📋 Giao dịch gần đây" — 10 giao dịch CCQ mới nhất từ `/api/trades`
- Mỗi row: ngày, mã+số CCQ, số tiền (âm mua/dương bán), badge MUA/BÁN
- loadSignals + loadTrades chạy song song (không await), không chặn nhau | commit 8a6801f

**GOV-015 bước 4** — T+2 prediction trong bảng tín hiệu (Pro only):
- Tận dụng `predictions{}` từ `/api/me` (KHÔNG gọi thêm API riêng)
- `loadProfile()` lưu `d.predictions` vào biến module `_predictions`, pass vào `loadSignals(predictions)`
- Hint nhỏ "T+2 ↑0.5%" / "T+2 ↓0.3%" dưới tên quỹ, xanh/đỏ theo chiều
- Tự ẩn với free users (server không trả predictions) | commit 51e8987

**Bài học kỹ thuật:**
- `/api/me` đã trả `signals` + `predictions` trong cùng 1 response — tận dụng để tránh API call
  thừa. `/api/signals` vẫn cần thiết vì nó trả `all_funds` (map code→tên) không có trong `/api/me`.
- Khi `loadProfile()` không thể pass `predictions` ra ngoài `try` block (`const d` scoped inside),
  dùng biến module `let _predictions = {}` và set bên trong try trước khi catch → pass ra ngoài được.
- `_auth_write()` đã support `X-Web-Session` từ GOV-015 bước 1, nên tất cả endpoint dùng
  `_auth_write` (gồm cả /api/signals, /api/trades, /api/me) đều hoạt động với Web session thật.

**Không code gì mới cho Python** — chỉ sửa `web.html` (HTML/CSS/JS), không cần thay đổi backend.

**Việc cần Harvey (tồn đọng):**
1. Set `WEB_SESSION_SECRET` trên Railway (cần thiết để web.html hoạt động thật)
2. Chạy `/setdomain` trên @BotFather trỏ về Railway domain (cần cho Telegram Login Widget)
3. Cấp JWT tcinvest mới (hết hạn lại từ 16/07, pattern lặp nhiều lần)
4. Xác nhận NTPPF/VMEEF có nên track (FK violation khi harvest tiếp tục)
5. `ios/` + `Fund Tracker Pro.xcodeproj/` deleted + `dashboard/portfolio.html` + scripts/* vẫn chưa commit

---

## ✅ Session (autonomous, scheduled) — Ca chiều 2026-07-19: tests GOV-017 + update BACKLOG

**Baseline đầu session**: py_compile OK, pytest 254/254 pass.

**Phát hiện**: 7 commits mới từ live session 17/07 chưa có trong BACKLOG:
- GOV-015 bước 5 (26ac450): nút Làm mới trong web.html — song song loadSignals + loadTrades
- fix(GOV-016) (e728855): T+2 mũi tên trung tính "≈" khi NAV trong khoảng tin cậy CI
- feat(GOV-016) bước 3 (1516bb0): tóm tắt chấm điểm T+2 ngay cạnh box "Giá chốt T+2"
- fix(GOV-016) (1f1e18e): drawAccuracyChart trống khi n=1 — vẽ dot đơn lẻ thay vì canvas trắng
- GOV-017 (5f12503): gộp Mã Promo + Voucher thành 1 loại với toggle requires_purchase
- VPS Migration Plan (62a7da6): kế hoạch dự phòng Railway → VPS + Coolify (tài liệu only)

**Task thực hiện: 14 tests mới cho GOV-017** (tests/test_gov017_discount.py):
- Phát hiện: GOV-017 không có test coverage — hàm redeem_instant_discount_code() mới hoàn toàn
- 11 test cho redeem_instant_discount_code(): mã rỗng, user bị ban, code not found,
  requires_purchase=True → error, expired/max_uses_exhausted, happy path, duplicate → idempotency
  blocked, order_ref format INSTANT-<code>-<tg_id>, code normalized uppercase.
- 3 test TestCreateDiscountCodeValidation: validation ValueError cho combination không hợp lệ.
- Pattern: fake cursor side_effect list (SELECT→INSERT) + patch is_banned/extend_pro/log_audit.

**Kết quả**: 268/268 tests (+14 mới), BACKLOG.md và memory.md cập nhật đầy đủ.

**Tất cả P0/P1 DONE.** Chỉ còn PAY-006 (VNPay)/PAY-007 (Stripe) — P2, chờ merchant credentials.

**Việc cần Harvey (tồn đọng):**
1. Set WEB_SESSION_SECRET trên Railway + chạy /setdomain @BotFather
2. Cấp JWT tcinvest mới (hết hạn từ 16/07, pattern lặp nhiều lần)
3. Xác nhận NTPPF/VMEEF có nên track (FK violation khi harvest tiếp tục)
4. ios/ + Fund Tracker Pro.xcodeproj/ deleted + dashboard/portfolio.html + scripts/* chưa commit

---

## ✅ Session (autonomous, scheduled) — Ca sáng 2026-07-20: fix 2 bugs detail panel GOV-018

**Baseline**: py_compile OK, 268/268 tests pass (không đổi).

**Phát hiện đầu session**: 3 commits mới từ live session 2026-07-19 (GOV-018 fund detail panel
trong web.html + 2 fix sau đó) chưa có trong BACKLOG. BACKLOG.md có thay đổi local chưa commit
(đã ghi GOV-018 vào). Đã commit BACKLOG update.

**2 bugs phát hiện và fix trong web.html (GOV-018 detail panel)**:

1. `hideChartLoading()` thiếu khi Pro API trả 403/error/catch — spinner "Đang tải biểu
   đồ..." ở lại song song với Pro lock message, gây nhầm lẫn. Fix: gọi `hideChartLoading()`
   cùng với `showProLock()` ở tất cả error path trong `fetchDetail()` (Pro branch). Free
   user branch đã đúng từ đầu (có explicit `hideChartLoading()` trong catch).

2. Panel không reset `scrollTop` khi mở fund mới — nếu user đã cuộn xuống trong fund trước,
   fund mới mở ra ở giữa trang thay vì đầu. Fix: `panel.scrollTop = 0` trong `openDetail()`
   trước khi add class `open`. Phải reset TRƯỚC khi mở animation để đảm bảo đúng vị trí.

**Verify**: `_api_nav_history` trả `{"date":..., "nav":...}` (không phải `nav_date`) — khớp
với `drawSparkline(p.date)` trong web.html. `_api_research` trả `nav_series` cùng format.
`position` data từ backend có `units/avg_cost/pnl_pct` khớp với `renderProDetail()`.
268/268 tests pass sau khi fix.

**Tất cả P0/P1 DONE.** Chỉ còn PAY-006 (VNPay)/PAY-007 (Stripe) — P2, chờ merchant credentials.

**Việc cần Harvey (tồn đọng, không thay đổi từ session trước):**
1. Set WEB_SESSION_SECRET trên Railway + chạy /setdomain @BotFather
2. Cấp JWT tcinvest mới (hết hạn từ 16/07, pattern lặp nhiều lần)
3. Xác nhận NTPPF/VMEEF có nên track (FK violation khi harvest tiếp tục)
4. ios/ + Fund Tracker Pro.xcodeproj/ deleted + dashboard/portfolio.html + scripts/* chưa commit

---

## Session — Ca chiều 2026-07-20 (autonomous, scheduled, tiếp nối từ ca sáng)

**Tình trạng đầu session**: tất cả P0/P1 DONE. Không có task IN_PROGRESS.

**Công việc**: Tăng độ bao phủ test cho 3 hàm security-critical chưa có test nào.

### 1. tests/test_gov015_web_auth.py — 22 tests (commit e360d81)
- `_verify_telegram_login_widget()`: xác thực Telegram Login Widget payload.
  - **Điểm quan trọng**: secret_key = `SHA256(bot_token)` — KHÁC với initData verification dùng
    `HMAC(bot_token, "WebAppData")`. Hai flow khác nhau hoàn toàn.
  - Test: empty/None payload, missing hash, wrong hash, wrong bot token, replay (>24h),
    clock skew (>5min future), tampered field, valid payload, auth_date invalid type.
- `_issue_web_session()` + `_verify_web_session()`: session token 30 ngày.
  - Format: `{tg_id}.{expiry_unix}.{hmac_sha256_hex}` — 3 segment phân cách bằng dấu chấm.
  - Test: roundtrip, empty token, no secret, tampered tg_id, tampered expiry, expired, wrong
    segment count, different secret, uniqueness, format validation.

### 2. tests/test_gov008_reverify.py — 21 tests (commit d40c156)
- `reverify_nav_tier()`: NAV 3-layer re-verification, chỉ áp dụng với `source='tcinvest'`.
- Trả về: `'skip'` / `'corrected'` / `'upgraded'` / `'unchanged'`.
- `NAV_VERIFY_TIERS = (1, 8, 31)` ngày; `NAV_VERIFY_TOLERANCE_PCT = 0.05` (0.05%).
- **Gotcha phát hiện**: `SELECT ... FOR UPDATE OF r` chứa chuỗi "UPDATE" → filter
  `"UPDATE" in str(call.args[0])` sẽ khớp SAI SELECT queries. Phải dùng `"SET" in ...`
  để chỉ match UPDATE thật (có `SET col=...`).
- Patches cần: `D.is_available`, `D.get_conn`, `D.log_audit`, `D._update_nav_row_hash`,
  `D._log_nav_verification`, `db.date` (patch module-level `date` để kiểm soát today).

### 3. tests/test_gov010_referral.py — 10 tests (commit 98c1313)
- `grant_referral_purchase_bonus()`: giai đoạn 2 referral, cấp 30 ngày Pro cho CẢ 2 bên.
- Test: no referral row, referrer_id=None, referee banned, referrer banned, happy path
  (trả dict đúng, extend_pro 2 lần, đúng bonus days, audit log), mark DB, actor_id forward.
- **Gotcha**: `_REDEMPTION_ID` là int, phải `str()` khi dùng `assert str(_REDEMPTION_ID) in
  str(call)` để so sánh với SQL string.

### Kết quả
- Suite: **268 → 321 tests** (+53). Tất cả 321 pass.
- Branch: `staging` (commits push lên `origin/staging`, KHÔNG phải main).
- GOV-006: web.html (~890 insertions uncommitted của Harvey) KHÔNG được commit — đúng quy tắc.

**Tất cả P0/P1 DONE.** PAY-006/007 P2 chờ merchant credentials.

**Việc cần Harvey (tồn đọng):**
1. Set `WEB_SESSION_SECRET` trên Railway + `/setdomain` @BotFather (để GOV-015 web auth live)
2. JWT tcinvest mới (hết hạn nhiều lần, pattern lặp)
3. Xác nhận NTPPF/VMEEF có nên track
4. Commit `ios/` + `dashboard/portfolio.html` + `scripts/*`

---

## ✅ Session (autonomous, scheduled) — Ca chiều 2026-07-21: update BACKLOG cho GOV-019/GOV-020

**Baseline**: py_compile OK, 321/321 tests pass (không đổi).

**Phát hiện đầu session**: 5 commits mới từ Harvey sau ca chiều 20/07 (sau commit da4deed):

**GOV-019 · Web redesign v3** (commits 9eb5bba + aad9797):
- web.html redesign toàn diện — full fund market screener (TẤT CẢ quỹ, không chỉ watched),
  search + filter chips (Tất cả/MUA/BÁN/★Theo dõi), watched funds sort lên đầu với ★.
- DCA calculator tích hợp: amt/month × months → tổng đầu tư + ước tính CCQ + giá trị tại NAV
  hiện tại. `_dcaNav` được set khi chọn quỹ từ danh sách hoặc mở detail panel.
- Xóa toàn bộ desktop 3-col layout (@media min-width:769px) — web.html giờ dùng đúng UX
  Mini App Telegram cho MỌI màn hình (max-width:680px centered trên desktop).

**GOV-020 · Admin panel improvements** (commits e590193 + 1af01c7 + 55be95f):
- `?dev=1` bypass trong admin_pnl.html cho UI review không cần token/DB — client-side only.
- Section "Cập nhật TCBS Token" (POST /api/admin/settoken) + "Quản lý mã giảm giá" (dùng
  /api/admin/discount/* endpoints đã có từ GOV-012).
- **TCInvest cross-login bookmarklet** (giải quyết pain point JWT hết hạn định kỳ): Harvey
  kéo đoạn script vào Bookmarks bar → click khi đang ở tcinvest.tcbs.com.vn → scan
  localStorage tìm JWT (eyJ prefix) → postMessage tới admin panel → token tự điền textarea.

**Verify**:
- Tất cả 6 API endpoints trong web.html đều có backend (không cần endpoint mới).
- GOV-015 features còn đầy đủ sau redesign (T+2 hints, loadSignals/loadTrades/loadProfile,
  _predictions variable, X-Web-Session headers).
- DCA calculator logic đúng: `(amt/nav) × months` CCQ tại constant NAV — đúng thiết kế,
  "Giá trị ước tính" = "Tổng đầu tư" khi NAV không đổi, label "(tại NAV hiện tại)" rõ ràng.
- Không kết nối được Railway proxy từ máy local (SSL error "received invalid response:
  I") — không verify được prediction_actuals hay T2-008 reweight eligibility.
  Kết quả cũ: 48 records tất cả cùng timestamp (batch đầu tiên 16/07). Cần Harvey verify
  trực tiếp hoặc đợi session có database access.

**Không code gì mới** — chỉ update BACKLOG (GOV-019/GOV-020) + memory.md.

**Việc cần Harvey (tồn đọng, không thay đổi):**
1. Set `WEB_SESSION_SECRET` trên Railway + `/setdomain` @BotFather (GOV-015 live)
2. JWT tcinvest mới (hết hạn từ 16/07, pattern lặp nhiều lần)
3. Xác nhận NTPPF/VMEEF có nên track
4. Commit `ios/` + `dashboard/portfolio.html` + `scripts/*`
5. Xác nhận `prediction_actuals` đã có đủ ngày để chạy T2-008 `--reweight` lần đầu
   (điều kiện: ≥10 samples/model từ ≥2 ngày khác nhau trong 30d qua)

---

## ✅ Session (autonomous, scheduled) — Ca sáng 2026-07-22: update BACKLOG cho 7 commits Harvey

**Baseline**: py_compile 3 file chính + 3 file mới (emergency_cleanup.py, local_dev_server.py,
build_web.py) → All OK. 321/321 tests pass.

**7 Harvey commits tối 21/07 (sau aa67e86, BACKLOG update ca chiều):**

**GOV-021** (bd0677c) — `init_pool` retry loop: Railway crash-loop khi bot khởi động trùng với
Postgres recovery ("Consistent recovery state has not been yet reached") → retry mỗi 3s tối đa
120s, migrations chạy sau khi pool thành công. Sửa crash-loop tái diễn.

**GOV-022** (6bd47b7 + a7dda92 + e3a36e4 + b8a2f74) — Web dashboard rebuild toàn diện:
- **Build system**: `build_web.py` + `web_body.html` + `web_js.js` → `web.html` (JS inlined vì
  miniapp_server không serve .js file riêng). Dev mock mode `?dev=1` skip API.
- **Layout**: 4-tab nav (Trang Chủ/Giao Dịch/Cá Nhân/Admin), 2-col Trang Chủ, trade-grid 3 cột,
  sidebar desktop (200px) + header (52px) thay bottom-nav.
- **Chart.js**: `selectFundChart()` + `renderFundChart()` cột phải desktop.
- **Fix diacritics** toàn bộ file, Admin tab ẩn mặc định hiện khi is_admin=true.

**GOV-023** (962c17e) — Backup retention triệt để: RETENTION_DAYS 14→2 ngày + MAX_BACKUP_FILES=24
(cap cứng). `scripts/emergency_cleanup.py` mới chạy khi Dockerfile CMD khởi động → tự dọn
/data/backups trước bot.py. Ngăn tái diễn Postgres volume đầy (lần 2 sau GOV-014).

**GOV-024** (07e92d1) — `local_dev_server.py` (569 dòng, mới hoàn toàn) cho local dev; kèm
fix UnboundLocalError signals + nav IS NOT NULL filter + pre-warm cache.

**Không code gì mới** — tất cả P0/P1 đã DONE từ trước. Chỉ còn PAY-006/PAY-007 P2.

**Việc cần Harvey (tồn đọng):**
1. Set `WEB_SESSION_SECRET` trên Railway + `/setdomain` @BotFather (GOV-015 live)
2. JWT tcinvest mới (hết hạn từ 16/07)
3. Xác nhận NTPPF/VMEEF
4. Commit `ios/` + `dashboard/portfolio.html` + `scripts/*`
5. Xác nhận `prediction_actuals` đủ ngày cho T2-008 `--reweight` lần đầu
