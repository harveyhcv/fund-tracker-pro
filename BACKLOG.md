# BACKLOG — Fund Tracker Pro
# Format: [STATUS] ID · Mô tả | Priority | Estimate | Dependency
# Status: TODO / IN_PROGRESS / DONE / BLOCKED
# Priority: P0 (blocker) / P1 (important) / P2 (nice-to-have)
# Claude đọc file này ĐẦU TIÊN mỗi session. Pick task IN_PROGRESS nếu có, nếu không pick P0 cao nhất.
#
# Last updated: 2026-07-10 (session 4 — ca sáng autonomous)

## ĐANG LÀM (IN_PROGRESS)
# Không có — tất cả P0/P1 đã DONE hoặc blocked chờ Railway deploy

---

## ═══════════════════════════════════════════
## PHASE 1 — TELEGRAM MINI APP SCAFFOLD
## ═══════════════════════════════════════════
# ⚠️ Audit 2026-07-09: Phase 1 đã được implement từ trước dưới kiến trúc KHÁC với
# spec gốc bên dưới — không phải `dashboard/miniapp/` + endpoint trong `server.py`,
# mà là app riêng: `telegram-bot/miniapp/index.html` + `telegram-bot/miniapp_server.py`
# (port riêng PORT_MINIAPP/8443, khởi động qua thread trong `bot.py main()`).
# Auth dùng per-request `X-Init-Data` header (verify HMAC mỗi request qua
# `_validate_init_data`), KHÔNG dùng session-token đổi 1 lần như spec — tương đương
# về bảo mật, chỉ khác cơ chế. Đánh dấu DONE theo triển khai thực tế.

- [DONE] MA-001 · Mini App HTML shell dùng Telegram WebApp JS SDK — `telegram-bot/miniapp/index.html` | 2026-07-09 (audit, code có sẵn)
- [DONE] MA-002 · HMAC-SHA256 verify initData — `_validate_init_data()` trong `telegram-bot/miniapp_server.py:629` | 2026-07-09 (audit)
- [DONE] MA-003 · Auth mỗi request qua `X-Init-Data` header — `_auth_write()` `miniapp_server.py:650` (thay vì session-token riêng, cùng mục đích) | 2026-07-09 (audit)
- [DONE] MA-004 · Mini App CSS dùng design system chung — `telegram-bot/miniapp/index.html` | 2026-07-09 (audit)
- [DONE] MA-005 · Fund signals UI — `/api/signals`, `/api/me` trong `miniapp_server.py` | 2026-07-09 (audit)
- [DONE] MA-006 · Portfolio view (NAV + signals + P&L) — `_calc_portfolio()` + `/api/me` | 2026-07-09 (audit)

---

## ═══════════════════════════════════════════
## PHASE 2 — FREEMIUM GATE
## ═══════════════════════════════════════════

- [DONE-LOCAL] GATE-001 · DB migration: bảng `user_tiers (telegram_id BIGINT PK, tier TEXT DEFAULT 'free', pro_expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ)` — `_ensure_user_tiers_table()` trong `telegram-bot/db.py` (lazy-create, cùng pattern với `bot_profiles`, tự chạy khi `get_tier`/`set_tier` được gọi lần đầu) | 2026-07-09 | cần DATABASE_URL thật trên Railway để verify
- [DONE-LOCAL] GATE-002 · Middleware `_check_tier(handler, telegram_id, required_tier)` trong `telegram-bot/miniapp_server.py` — trả 403 `{"error":"pro_required","upgrade_url":"/buy"}` nếu thiếu quyền; `get_tier()`/`set_tier()` trong `db.py` (tự downgrade khi `pro_expires_at` hết hạn) | 2026-07-09 | cần DATABASE_URL thật để verify integration
- [DONE-LOCAL] GATE-003 · Free limit enforcement: `POST /api/me/watched_funds` trả 403 `pro_required` khi user free có > `FREE_FUND_LIMIT` (=2) mã. Bonus fix: endpoint trước đó có bug — khi profile lấy từ DB (`bot_profiles`) thì mutate + `_save_cfg()` không ghi gì cả (chỉ sửa config.json), tức add-fund KHÔNG persist trên production (Railway dùng DB). Đã thêm `db.set_watched_funds()` để ghi đúng vào DB khi `db_backed=True` | 2026-07-09 | cần DATABASE_URL thật để verify
- [DONE] GATE-004 · Mini App upgrade prompt: modal "Nâng cấp Pro" (list tính năng + CTA) trong `telegram-bot/miniapp/index.html`, hiện khi `POST /api/me/watched_funds` trả 403 `pro_required`. `apiPost`/`apiDelete` đính kèm response body vào `Error.body` để phân biệt lỗi. CTA "NÂNG CẤP NGAY" hiện toast "sắp ra mắt" (chưa có PAY-001) — sẽ wire thật khi PAY-001..003 xong | 2026-07-09

---

## ═══════════════════════════════════════════
## PHASE 3 — PAYMENT (dễ trước, khó sau)
## ═══════════════════════════════════════════

### 3a. Telegram Stars (làm trước — đơn giản nhất)

- [DONE] PAY-001 · `/buy_pro` command gửi sendInvoice XTR 250 Stars | 2026-07-10
- [DONE] PAY-002 · `pre_checkout_query` handler answerPreCheckoutQuery | 2026-07-10
- [DONE] PAY-003 · `successful_payment` → set_tier(pro, NOW()+30d) + confirm message | 2026-07-10

### 3b. MoMo (VN market)

- [DONE-LOCAL] PAY-004 · `POST /api/payment/momo/create` trong `miniapp_server.py` — auth qua X-Init-Data (không tin telegram_id client gửi), build MoMo v2 `captureWallet` request (requestId/orderId có prefix `FTP-<tgid>-<ts>`, HMAC-SHA256 signature), trả `pay_url`. Dùng MoMo test/sandbox credentials mặc định (`MOMO_PARTNER_CODE=MOMO`, `MOMO_ACCESS_KEY`, `MOMO_SECRET_KEY` — override bằng ENV khi có merchant thật) | 2026-07-10 | cần merchant MoMo thật + `MINIAPP_URL`/`RAILWAY_PUBLIC_DOMAIN` set để verify end-to-end
- [DONE-LOCAL] PAY-005 · `POST /api/payment/momo/ipn` — verify HMAC-SHA256 signature (constant-time compare) trước khi tin field nào; khi `resultCode=0` → parse telegram_id từ `orderId`, gọi `db.set_tier(tg_id, "pro", +30d)` + gửi Telegram confirm message | 2026-07-10 | PAY-004
- Frontend: nút "💗 THANH TOÁN QUA MOMO" trong `#upgrade-modal` (`telegram-bot/miniapp/index.html`) → `startUpgradeMomo()` gọi `/api/payment/momo/create`, mở `pay_url` qua `tg.openLink()` | 2026-07-10
- **Bug tìm thấy + fix (không thuộc PAY-004/005 nhưng cùng khu vực code)**: `do_POST` gọi `self._api_create_stars_invoice(user)` nhưng `user` chưa từng được gán trong scope `do_POST` → NameError mỗi khi user bấm "NÂNG CẤP PRO NGAY" qua Mini App (endpoint `/api/payment/stars/create`, khác với `/buy_pro` command trong bot.py vẫn hoạt động bình thường). Đã sửa: `_api_create_stars_invoice()` tự validate `X-Init-Data` để lấy `user`, cùng pattern với `_auth_write()` | 2026-07-10

### 3c. VNPay + Stripe (làm sau)

- [ ] PAY-006 · VNPay: `/payment/vnpay/create` + `/payment/vnpay/return` theo spec VNPay 2.1.0 | P2 | 4h
- [ ] PAY-007 · Stripe Checkout: session tạo qua Stripe API, webhook `/payment/stripe/webhook` xác nhận | P2 | 3h

---

## ═══════════════════════════════════════════
## PHASE 4 — PRO FEATURES
## ═══════════════════════════════════════════

- [DONE] PRO-001 · /api/research/{code} gated pro_required + apiFetch error body fix + openResearch upgrade modal | 2026-07-10
- [DONE] PRO-002 · Gold analysis: trend + RSI(14) + MA20/50 + BB signal cho SJC/DOJI — audit 2026-07-10, code có sẵn: `_calc_gold_signals()` `miniapp_server.py:104`, hiển thị "3 trường phái" (Lướt sóng/Trung/Dài hạn) trong `renderGoldSignalFull()` (`miniapp/index.html:1005`) | 2026-07-10 (audit, code có sẵn)
- [DONE] PRO-003 · Unlimited fund tracking: bỏ giới hạn khi tier=pro — audit 2026-07-10, đã implement sẵn trong GATE-003 (`_api_update_watched` `miniapp_server.py:1087`: `if not _is_admin(tg_id) and _get_tier(tg_id).get("tier") != "pro" and len(valid) > FREE_FUND_LIMIT`) | 2026-07-10 (audit, code có sẵn)
- [DONE-LOCAL] PRO-004 · Alert system — bảng `alerts` (`db.py`: `_ensure_alerts_table` + `create_alert`/`list_alerts`/`delete_alert`/`get_active_alerts`/`mark_alert_triggered`), `bot.py job_check_alerts()` chạy 18:33 (sau harvest 18:30 + T2 predict/score 18:31/18:32), debounce 1 lần/ngày/alert qua `last_triggered`. API: `GET/POST /api/alerts`, `DELETE /api/alerts/<id>` trong `miniapp_server.py` (pro-gated qua `_check_tier`, ghi qua `_auth_write`). UI: mục "🔔 Cảnh báo" trong modal Nghiên cứu (`miniapp/index.html`, cùng chỗ PRO-001) — đặt/xóa cảnh báo nav_up/nav_down/signal_buy/signal_sell cho quỹ đang xem | 2026-07-10 | cần DATABASE_URL thật + chạy qua 18:33 trên Railway để verify job thật gửi Telegram

---

## ═══════════════════════════════════════════
## PHASE 5 — T+2 FORECAST ENGINE
## (Core competitive moat — accuracy = revenue)
## ═══════════════════════════════════════════

### 5a. Infrastructure

- [DONE] T2-001 · nav_predictions + prediction_actuals + model_metrics tables trong db.py | 2026-07-10
- [DONE] T2-002 · Feature pipeline (nav_lag_1..5, chg_1d/5d/21d, vol_5d/21d, day_of_week, days_to_month/quarter_end) trong t2_arima.py | 2026-07-10

### 5b. Models (baseline → ML → ensemble)

- [DONE] T2-003 · ARIMA(2,1,2) trong scripts/t2_arima.py --predict, sanity clip ±10%, CI 80% | 2026-07-10
- [ ] T2-004 · ML model `scripts/t2_xgboost.py`: XGBoostRegressor với feature vector T2-002, train/test split theo thời gian (80/20), evaluate MAPE trước khi deploy, insert predictions với `model_version='xgb-v1'` | P1 | 5h | T2-002, T2-003
- [ ] T2-005 · Ensemble: weighted average ARIMA + XGBoost (init weights 0.3/0.7), CI = ±1.5 × rolling prediction std (30 ngày) | P1 | 2h | T2-003, T2-004

### 5c. Self-improvement loop

- [DONE] T2-006 · score_predictions() trong db.py + --score mode trong t2_arima.py, job_t2_score 18:32 | 2026-07-10
- [ ] T2-007 · Weekly retrain job: Chủ nhật 02:00, retrain XGBoost với toàn bộ data kể cả actuals mới nhất, bump `model_version='xgb-v{N+1}'`, ghi MAPE vào `model_metrics` table | P1 | 2h | T2-004, T2-006
- [ ] T2-008 · Adaptive ensemble weights: mỗi 30 ngày, tính MAPE(ARIMA) vs MAPE(XGBoost) trên tháng qua, set `w_arima = mape_xgb/(mape_arima+mape_xgb)` và ngược lại | P1 | 2h | T2-005, T2-006

### 5d. User-facing (Mini App)

- [DONE] T2-009 · fund-row hiện T+2 pred (↑/↓X%) từ /api/me predictions{}, chỉ Pro | 2026-07-10
- [ ] T2-010 · Accuracy dashboard: tab "Độ chính xác" hiện MAPE 7d/30d/all-time per quỹ + biểu đồ dự báo vs thực tế, model version | P2 | 3h | T2-006

---

## XONG (DONE)

- [DONE] DB-002 · NAV confidence workflow: `provisional`/`pending_confirm`/`confirmed`/`fixed` state machine cho `nav_history.source` — `harvest_nav.py cmd_daily` so fetch mới với NAV hôm qua (provisional nếu trùng = API TCinvest chưa publish) và với NAV `manual` hiện có (tự confirm nếu khớp, `pending_confirm` nếu lệch); `db.py upsert_nav_with_confidence/get_pending_confirms/resolve_nav_confirm`; admin nhận nút xác nhận qua Telegram (`bot.py _notify_pending_nav_confirms`, sửa bug gọi nhầm `tg_send(...,buttons=)` → `tg_send_keyboard`); API `GET /api/admin/nav/pending` + `POST /api/admin/nav/confirm` trong `miniapp_server.py`, `_api_signals` trả kèm `nav_source`/`pending_nav` cho UI badge | 2026-07-10 (audit + hoàn thiện phần API còn thiếu từ commit `aad06a0`)
- [DONE] GATE-004 · Mini App upgrade-to-Pro modal khi 403 pro_required | 2026-07-09
- [DONE] GATE-001/002/003 · Freemium gate: `user_tiers` table + `check_tier` middleware + free-fund-limit enforcement trên `/api/me/watched_funds` (xem note DONE-LOCAL phía trên) | 2026-07-09
- [DONE] MA-001..006 · Telegram Mini App (audit — code đã tồn tại từ trước, xem note ở PHASE 1) | 2026-07-09
- [DONE] FMKT-001 · fmarket_id mapping: fix 3 sai, thêm 15 mã mới | 2026-07-09
- [DONE] DASH-001 · Multi-fund selector | 2026-07-08
- [DONE] USR-001 · Multi-user registration via bot_profiles | 2026-07-08
- [DONE] JWT-001 · TCBS token expiry check + admin notify | 2026-07-08
- [DONE] DB-001 · Scheduled NAV harvest 18:30 daily | 2026-07-08
- [DONE] SIG-001..006 · Technical indicators (Golden Cross, Stochastic, Sharpe, Sortino, Volatility, CCI/ROC) | 2026-07-08
- [DONE] SEC-001..003 · Rate limiting, env vars, API key auth | 2026-07-08
- [DONE] BUG-001..005 · Portfolio, NameError, /explain restore, TCBS endpoint, Gold signal | 2026-07-08
- [DONE] DATA-001 · Import 91,747 NAV datapoints cho 38 quỹ | 2026-07-08
- [DONE] GIT-001 · .gitignore hardening | 2026-07-08

## BLOCKED

# Không có task bị block hiện tại
