# BACKLOG — Fund Tracker Pro
# Format: [STATUS] ID · Mô tả | Priority | Estimate | Dependency
# Status: TODO / IN_PROGRESS / DONE / BLOCKED
# Priority: P0 (blocker) / P1 (important) / P2 (nice-to-have)
# Claude đọc file này ĐẦU TIÊN mỗi session. Pick task IN_PROGRESS nếu có, nếu không pick P0 cao nhất.
#
# Last updated: 2026-07-12 (session 6 — QA toàn diện + v1.0 + promo/beta)

## ĐANG LÀM (IN_PROGRESS)
# Không có. v1.0 đã tag. Ưu tiên tiếp theo: GOV-001..006 (Phase 6a — quản trị dữ liệu
# chặt chẽ, Harvey yêu cầu trước khi bán) — GOV-001 (audit log) nên làm trước vì
# GOV-003/004 phụ thuộc vào nó. Còn PAY-006/PAY-007 (P2, cần merchant credentials thật).

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
- [DONE-LOCAL] T2-004 · ML model `scripts/t2_xgboost.py` — pooled XGBoost (Booster API, không cần scikit-learn) qua tất cả quỹ, `fund_code` label-encoded làm feature, target = %chg T+2 (ổn định hơn NAV tuyệt đối khi pool nhiều quỹ khác thang đo). Reuse `_build_features`/`_fetch_nav_series`/`_next_trading_date` từ `t2_arima.py`. `--train`: time-split 80/20 PER-FUND (giữ thứ tự thời gian, không shuffle — tránh look-ahead bias), early-stopping trên test MAPE, lưu model vào `scripts/models/xgb_t2.json` (gitignored, cần chạy `--train` 1 lần trên Railway sau deploy) + ghi `model_metrics`. `--predict`: load model, dự báo T+2 mọi quỹ ≥60 điểm NAV, sanity clip ±10% (khớp ARIMA), insert `nav_predictions` với `model_version='xgb-v1'` — được `db.score_predictions()`/job_t2_score hiện có chấm điểm tự động (không cần sửa gì, hàm score generic theo mọi model_version). Thêm `xgboost>=2.0.0` vào requirements.txt | 2026-07-10 | Smoke-tested bằng synthetic NAV series (762 rows, 3 quỹ giả) — feature pipeline + time-split + train/predict chạy đúng, không lỗi. Cần DATABASE_URL thật + chạy `--train` trên Railway để có model production trước khi `--predict` hoạt động
- [DONE-LOCAL] T2-005 · Ensemble `scripts/t2_ensemble.py` — đọc dự báo mới nhất `arima-v1` + `xgb-v1` cho cùng `predicted_for_date` (lệch ngày → skip quỹ đó, coi như 1 model chưa chạy), weighted average `W_ARIMA=0.3/W_XGB=0.7` (hardcode, T2-008 sẽ làm adaptive), ghi `nav_predictions` với `model_version='ensemble-v1'`. CI = `predicted_nav ± 1.5×rolling_std(error_pct, 30d)` qua `db.get_rolling_error_std()` (mới, ưu tiên per-fund ≥5 mẫu, fallback toàn cục, fallback cứng ±2% nếu ensemble-v1 chưa có lịch sử chấm điểm — đúng cho vài tuần đầu). Wire vào `bot.py`: `job_t2_predict()` (18:31) giờ chạy tuần tự ARIMA → XGBoost → Ensemble qua helper `_run_t2_script()` (mỗi script lỗi độc lập, không chặn 2 script còn lại); `job_t2_score` (18:32, không đổi — score generic theo mọi model_version) sẽ tự chấm điểm ensemble-v1 luôn | 2026-07-10 | Cần DATABASE_URL thật + cả model arima-v1/xgb-v1 đã chạy predict cùng ngày để verify end-to-end

### 5c. Self-improvement loop

- [DONE] T2-006 · score_predictions() trong db.py + --score mode trong t2_arima.py, job_t2_score 18:32 | 2026-07-10
- [DONE-LOCAL] T2-007 · Weekly retrain — `scripts/t2_xgboost.py::_next_version(conn)` tìm `xgb-vN` lớn nhất trong `model_metrics` (LIKE 'xgb-v%'), trả `xgb-v{N+1}` (hoặc `xgb-v1` nếu chưa train lần nào); `cmd_train()` giờ dùng version động này thay vì hardcode, ghi vào `meta.json` + `model_metrics`. `cmd_predict()`/`cmd_status()` đọc `model_version` từ `meta.json` (không hardcode nữa) nên tự động dùng model mới nhất sau mỗi lần retrain. `bot.py`: `job_t2_retrain()` (mới) chạy `t2_xgboost.py --train` qua `_run_t2_script()`, schedule Chủ nhật 02:00 (timeout 900s — train chậm dần khi data lớn lên) | 2026-07-10 | Version-bump logic smoke-tested (fake cursor, 3 case: rỗng/v1/v1+v2+v3 → đúng v1/v2/v4). Cần DATABASE_URL thật để verify retrain thật trên Railway (chạy `railway run python scripts/t2_xgboost.py --train` để tạo model xgb-v1 đầu tiên trước khi cron Chủ nhật kích hoạt)
- [DONE-LOCAL] T2-008 · Adaptive ensemble weights — `scripts/t2_ensemble.py --reweight` tính `mape_arima`/`mape_xgb` 30 ngày qua (`_mape_last_days()`, cần ≥10 mẫu/model đã chấm điểm mới tin cậy, không thì giữ nguyên trọng số cũ), set `w_arima=mape_xgb/(mape_arima+mape_xgb)` và ngược lại (inverse-MAPE — model lỗi ít hơn được trọng số cao hơn), lưu `scripts/models/ensemble_weights.json` (gitignored). `cmd_predict()` giờ gọi `_load_weights()` thay vì hardcode W_ARIMA/W_XGB (fallback 0.3/0.7 tĩnh nếu chưa `--reweight` lần nào hoặc file lỗi). `--status` hiện thêm trọng số hiện tại. `bot.py`: `job_t2_reweight()` chạy `t2_ensemble.py --reweight`, schedule `every(30).days.at("03:00")` (verify `schedule` lib hỗ trợ cú pháp này — đã test `next_run` tính đúng) | 2026-07-10 | Smoke-tested: fallback khi chưa có file, math inverse-MAPE (MAPE 1%/3% → w=0.75/0.25, tổng=1.0), đọc/ghi file, fallback khi file corrupt — tất cả đúng. Cần DATABASE_URL thật + ≥30 ngày dữ liệu chấm điểm arima-v1/xgb-v1 để verify reweight thật trên Railway

### 5d. User-facing (Mini App)

- [DONE] T2-009 · fund-row hiện T+2 pred (↑/↓X%) từ /api/me predictions{}, chỉ Pro | 2026-07-10
- [DONE-LOCAL] T2-010 · Accuracy dashboard — thay vì tab riêng (nav bar đã 6 icon, chật cho mobile), gộp vào modal "Nghiên cứu" hiện có (cùng chỗ PRO-001/PRO-004) làm section mới "🎯 Độ chính xác dự báo T+2": bảng MAPE 7d/30d/all-time × 3 model (arima-v1/xgb-v1/ensemble-v1) + canvas overlay dự báo-vs-thực-tế (60 điểm gần nhất, tái dùng style `drawChart`). Backend: `db.get_accuracy_summary(fund_code)` (SQL `FILTER (WHERE logged_at >= NOW()-INTERVAL)` cho 3 window, ép `Decimal→float` vì `ROUND(...)::numeric` không JSON-serializable), `db.get_accuracy_history(fund_code, model_version=None, limit=60)` (không truyền model → ưu tiên ensemble>xgb>arima nếu trùng ngày, cast `predicted_for_date::text` vì cùng lý do Decimal/date). API: `GET /api/t2/accuracy/<code>?user_id=&model=` (pro-gated qua `_check_tier`) trong `miniapp_server.py`. Bonus fix: `_t2Html()` từng hardcode nhãn "(dự báo ARIMA)" dù giờ có thể hiện ensemble/xgb prediction (get_predictions lấy bản ghi mới nhất, không phân biệt model) — sửa thành nhãn động theo `pred.model_version` (`_t2ModelLabel()`) | 2026-07-10 | Verify: `preview_start miniapp` (static server, tạo `.claude/launch.json` ở `P:\NGCG\Vibe Coding\` vì browser tool tìm launch.json ở working-dir cha, không phải project root) + `preview_eval` gọi `renderResearch()` với payload giả + mock `apiFetch('/api/t2/accuracy/...')` — bảng MAPE, canvas chart (686×240 sau resize mobile viewport), và nhãn "dự báo Ensemble" đều render đúng qua `preview_snapshot`, không console error. Cần DATABASE_URL thật + dữ liệu chấm điểm thực để verify API backend end-to-end

---

## ═══════════════════════════════════════════
## PHASE 6 — v1.0 PACKAGING + GOVERNANCE
## ═══════════════════════════════════════════

- [DONE] BILL-001 · Fix bug cộng dồn Pro: `set_tier(now+30)` reset mất số ngày Pro còn lại khi
  gia hạn sớm — thêm `db.extend_pro()` cộng dồn từ hạn hiện tại, áp dụng cho cả Stars
  (`_handle_successful_payment`) và MoMo IPN | 2026-07-12
- [DONE] PROMO-001 · Bảng `promo_codes`/`promo_redemptions` — mã admin tạo (trial 30-90 ngày,
  giới hạn lượt) + mã referral cá nhân (không giới hạn lượt, +30 ngày cho cả 2 bên), UNIQUE
  (code, telegram_id) chặn dùng lại. API: `/api/promo/redeem`, `/api/referral/mine`,
  `/api/admin/promo/{list,create,deactivate}`. UI: ô nhập mã + mã giới thiệu cá nhân trong modal
  Nâng cấp Pro, card quản lý mã trong tab Admin | 2026-07-12 | Test end-to-end trên DB thật
  (tạo/dùng/trùng/hết lượt/referral/tự dùng mã mình — pass hết, dữ liệu test đã dọn)
- [DONE] BETA-001 · Lệnh `/beta` (chỉ admin) — mở Mini App với tài khoản test cô lập
  (telegram_id âm qua `_effective_tg_id`/`_qs_tg_id`/`_data_tg_id`), NAV/tín hiệu/giá vàng/dự
  báo T+2 vẫn dùng chung dữ liệu thật. Banner vàng "BETA MODE" luôn hiện khi active.
  `_api_nav_draft` CỐ TÌNH không remap (NAV là nguồn chung, không cho test data lọt vào) | 2026-07-12
  | Verify qua browser + log server: portfolio test rỗng (0đ), tín hiệu vẫn đúng NAV thật
- [DONE] REL-001 · Tag `v1.0` — Stars là phương thức thanh toán chính thức, nút MoMo tạm ẩn
  ("sắp ra mắt") cho đến khi có merchant thật | 2026-07-12

### 6a. Quản trị dữ liệu chặt chẽ (theo yêu cầu — CHƯA LÀM, cần session riêng)
# Harvey yêu cầu: không bao giờ xoá/đổi dữ liệu tài khoản/NAV/dự đoán khi sửa code, bảo mật
# nhiều lớp (có PII), đạt chuẩn để "bán được". 4 hạng mục cụ thể đã chọn:

- [DONE] GOV-001 · Audit log — bảng `audit_log(actor_id, action, target_table, target_id,
  before_state, after_state, note, created_at)` append-only, `db.log_audit()`/`get_audit_log()`.
  Hook vào extend_pro/set_tier/redeem_promo_code/create_promo_code/update_promo_code/
  (de)activate_promo_code/resolve_nav_confirm/trade CRUD (CCQ + vàng: add/edit/delete)
  | 2026-07-13 | Còn thiếu: UI xem log cho admin (phần dashboard của GOV-004)
- [ ] GOV-002 · Backup tự động định kỳ — Railway cron/script `pg_dump` hàng ngày lên object
  storage (S3-compatible hoặc Railway volume), retention policy rõ ràng, quy trình restore đã
  test thử ít nhất 1 lần | P0 | ~3h (phụ thuộc chọn nơi lưu backup)
- [ ] GOV-003 · Cảnh báo bất thường tự động — rule-based: NAV nhảy >X%/phiên, MAPE dự báo vượt
  ngưỡng N ngày liên tiếp, thanh toán trùng lặp (cùng charge_id/orderId xử lý 2 lần), redeem
  promo bất thường (nhiều mã cùng 1 phút) → Telegram admin | P1 | ~4h (giờ có audit_log làm nguồn)
- [DONE-PARTIAL] GOV-004 · `GET /api/admin/audit` (admin-only, `_auth_write` + `_is_admin`,
  dùng `db.get_audit_log()` có sẵn từ GOV-001) + card "Audit log gần đây" trong tab Admin
  Mini App (`telegram-bot/miniapp/index.html`) hiện 50 dòng gần nhất (action/actor/target/note).
  Verify qua browser preview với mock apiFetch — render đúng, không console error | 2026-07-13
  | Còn thiếu phần dashboard tổng hợp: số user theo tier, MAPE model, quỹ NAV lỗi/thiếu, giao
  dịch thanh toán gần đây — để lại cho session sau (cần nhiều endpoint mới hơn, task lớn hơn ước tính ban đầu)
- [DONE] GOV-005 · Security hardening — đã tìm và vá 2 lỗ hổng NGHIÊM TRỌNG (2026-07-13):
  (1) MỌI API đọc (GET: /api/me, /api/signals, /api/trades, /api/research/<code>,
  /api/admin/nav/pending, /api/admin/promo/list...) không verify X-Init-Data, chỉ trust query
  param user_id — bất kỳ ai biết telegram_id của user khác đều đọc được toàn bộ dữ liệu riêng
  tư của họ (CONFIRMED khai thác được, đã test). (2) `_auth_write()` có bypass "telegram_id
  gửi lên == admin_id thì cho qua không cần initData" — client tự khai telegram_id nên AI CŨNG
  giả danh admin để GHI dữ liệu (settoken, promo/create, fetch-nav, fixportfolio, import-nav)
  mà không cần bằng chứng Telegram nào — CONFIRMED nghiêm trọng hơn #1. Fix: apiFetch() gửi
  X-Init-Data, mọi GET/POST private data bắt buộc _auth_write() xác thực chữ ký HMAC thật;
  bỏ bypass string-match, thay bằng secret ADMIN_API_KEY (ENV) cho script nội bộ
  (scripts/import_tcbs_xlsx.py). Verify bằng 12 test tự viết giả lập chữ ký Telegram thật,
  chạy trực tiếp lên DB Railway | 2026-07-13 | Còn lại: auth_date freshness check (chống
  replay initData cũ) chưa làm — mức độ rủi ro thấp hơn, có thể làm sau
- [DONE] GOV-006 · Chính sách "không xoá/đổi dữ liệu khi deploy" — viết thành quy tắc migration
  trong `CLAUDE.md` (section "🔐 CHÍNH SÁCH DỮ LIỆU"): mọi ALTER TABLE phải additive, script sửa
  dữ liệu hàng loạt phải dry-run mặc định, audit_log append-only, PROTECTED_SOURCES cho NAV,
  luôn hỏi Harvey trước khi xoá dữ liệu không phải do session tạo ra | 2026-07-13

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
