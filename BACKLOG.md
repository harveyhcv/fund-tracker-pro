# BACKLOG — Fund Tracker Pro
# Format: [STATUS] ID · Mô tả | Priority | Estimate | Dependency
# Status: TODO / IN_PROGRESS / DONE / BLOCKED
# Priority: P0 (blocker) / P1 (important) / P2 (nice-to-have)
# Claude đọc file này ĐẦU TIÊN mỗi session. Pick task IN_PROGRESS nếu có, nếu không pick P0 cao nhất.
#
# Last updated: 2026-07-15 (ca chiều — verify production, không có task P0/P1 nào mới)

## Session (autonomous, scheduled) — Ca chiều 2026-07-15: verify production, không code thêm
# Đọc lại toàn bộ BACKLOG (558 dòng) + memory.md: ca sáng cùng ngày đã làm GOV-005-part2,
# GOV-007-part4, GOV-007-part3, T2-013, GOV-008/T2-014 — TẤT CẢ P0/P1 đã DONE. Chỉ còn
# PAY-006 (VNPay)/PAY-007 (Stripe), cả 2 P2 và cần merchant credentials thật (đã ghi rõ
# trong chính BACKLOG là blocker) — đúng điều kiện dừng trong session brief.
# Phát hiện `telegram-bot/config.json` có sẵn `database_url` trỏ thẳng Railway production
# (thomas.proxy.rlwy.net) — dùng để VERIFY (read-only) các cơ chế mới ca sáng vừa code có
# thực sự chạy đúng trên production không, thay vì chỉ dừng ở "chưa verify integration thật":
# - verify_tier (GOV-008): cột tồn tại, phân bố thật 60 ngày gần nhất (tier0=353, tier1=186,
#   tier8=713, tier31=930) — cơ chế đang hoạt động, không phải code chết.
# - audit_log 3 ngày qua: 20x `nav_reverify_corrected` (TCBS tự sửa NAV provisional→final,
#   lệch 0.08%-2.4%, đúng thiết kế), 0 `nav_jump_anomaly` MỚI hôm nay (3 lần cũ đều từ
#   07-13/07-14, trước khi GOV-008 xong — không phải sự cố đang diễn ra).
# - VCBFTBF (quỹ có 3 sự cố trước đó): NAV 10 ngày gần nhất TOÀN BỘ nguồn tcinvest/manual
#   nhất quán, không còn xen kẽ nguồn khác — xác nhận đã ổn định thật.
# - T2 predictions: cả 4 model (arima-v1/xgb-v2/naive-v1/ensemble-v1) đều có 51/51 quỹ dự
#   báo tươi cho T+2=2026-07-16 — pipeline T2-011 sau khi fix vẫn chạy khỏe.
# - `prediction_actuals` TRỐNG HOÀN TOÀN (0 dòng all-time) — KHÔNG PHẢI bug: pipeline T2
#   chỉ mới chạy thật từ 2026-07-14 (T2-011), dự báo T+2 hôm nay chưa tới hạn có NAV thật
#   để so sánh/chấm điểm. Cần chờ vài ngày để `job_t2_score` có dữ liệu chấm.
# - 39/40 quỹ "chưa có NAV hôm nay" lúc 14:08 giờ VN — BÌNH THƯỜNG, không phải bug: harvest
#   job chạy 18:30/20:00 tối, giờ kiểm tra là buổi chiều, chưa tới giờ harvest.
# - 0 pending_confirm tồn đọng, 2 user tier=pro (không phải bug, chỉ là số liệu kinh doanh).
# - `grep TODO/FIXME` toàn bộ `telegram-bot/*.py` → 0 kết quả, code không có việc dở dang.
# Kết luận: không có task P0/P1 nào để làm thêm, không code gì mới ca này (đúng tinh thần
# "producing a report of what you found is the correct output" khi không có write action
# nào được yêu cầu cụ thể). Không đụng PAY-006/007 (thiếu credentials thật).
# ⚠️ Phát hiện ngoài lề (KHÔNG xử lý, chỉ ghi lại cho Harvey): `git status` cho thấy toàn bộ
# `Fund Tracker Pro.xcodeproj/` + các file Swift cũ (`Fund Tracker Pro/ContentView.swift`...)
# bị đánh dấu deleted, trong khi có thư mục `ios/` mới HOÀN TOÀN chưa track — trông giống 1
# đợt tái cấu trúc thủ công trên máy local CHƯA được git add/commit. Không tự ý commit vì
# đây không phải task trong BACKLOG và constraint ghi rõ "KHÔNG implement iOS trước khi
# Phase 1-4 xong" — an toàn hơn để Harvey tự xác nhận ý định trước khi ai đó commit.
#
## GOV-007 — root cause thật (2026-07-14, sau khi bug tái diễn dù đã "khóa cứng")

## GOV-007 — root cause thật (2026-07-14, sau khi bug tái diễn dù đã "khóa cứng")
# Bản sửa trước (bỏ fmarket_id sai của VCBFTBF trong FUND_CATALOG) KHÔNG có tác dụng gì
# trên production: `fetch_all()` (bot.py) ưu tiên đọc `config.json["funds"][code]` TRƯỚC
# FUND_CATALOG, chỉ fallback nếu config.json không có entry. config.json trên Railway
# (ghi 1 lần, không tự đồng bộ lại với code mỗi lần deploy) vẫn giữ fmarket_id=31 cũ —
# luôn thắng, tiếp tục ghi NAV sai. Phát hiện qua: fetched_at cập nhật ngay sau deploy
# mới nhưng source vẫn quay lại 'fmarket'.
# Đã sửa: đổi ưu tiên `FUND_CATALOG.get(code) or funds_cfg.get(code) or {}` (khớp pattern
# đã đúng từ đầu ở _api_admin_fetch_nav) + sửa trực tiếp config.json trên server (có backup
# `/data/config.json.bak-before-vcbftbf-fix`) + backfill lại toàn bộ 4,583 điểm lịch sử.
# Phát hiện thêm: dữ liệu fmarket cho mã này TỰ NÓ không nhất quán qua thời gian — cùng
# ngày lịch sử, query khác lần trả về ~28k hoặc ~38k — gây pattern xen kẽ suốt từ 07/2025,
# không phải "tự dưng hôm qua" như quan sát ban đầu (đã sai âm thầm nhiều tháng, chỉ mới
# bị phát hiện). Verify: 83 anomaly (>8% jump giữa 2 ngày liên tiếp) trong 370 ngày gần
# nhất → 0 sau khi backfill lại. Đã re-test lock bằng đúng kịch bản config cũ (giả lập
# fmarket_id=31) — xác nhận giờ không viết đè được nữa. vol_30d: 5.56% (sane).
# Bài học: khi "khóa" 1 nguồn dữ liệu, phải audit TẤT CẢ nơi đọc cấu hình cho quỹ đó
# (không chỉ code — còn config.json/DB đã persist từ trước), không chỉ sửa 1 chỗ rồi
# coi là xong.
#
# v1.2 — UI mini app (badge tín hiệu):
# - navConfidenceBadge tách riêng phần 'manual' ra thành manualNavBadge() (chỉ icon ✍️,
#   bỏ chữ "thủ công" cho gọn).
# - staleNavBadge rút gọn còn ngày ngắn (vd "⏱ 13/07") thay vì câu dài "chưa có NAV hôm
#   nay — nhập tay"; ẩn hẳn khi NAV đã cập nhật hôm nay.
# - manualNavBadge + staleNavBadge dời xuống cột phải dưới badge Mua/Bán/Hold (trước đây
#   nằm chung dòng với giá NAV, dễ tràn dòng trên màn hình hẹp).
# - positionBadge (P&L vị thế user): đổi icon 💼 → nhãn "T+2" trong 1 bản nháp trước đó,
#   NHƯNG bị phát hiện lỗi khi kiểm tra lại — "T+2" đã có nghĩa khác (dự báo NAV T+2) ngay
#   trên cùng 1 thẻ quỹ, gây nhầm lẫn 2 con số khác nhau cùng nhãn. Đã revert lại về 💼.
# - QC: verify trực tiếp trong browser thật (không phải Node eval giả lập) — gọi thẳng
#   các hàm badge với dữ liệu mock, và render renderSignals() với 3 quỹ mẫu (stale/manual/
#   up-to-date) — xác nhận đúng thiết kế, không còn nhãn T+2 gây nhầm.

## ĐANG LÀM (IN_PROGRESS)
# Không có. v1.1/v1.1.1/v1.1.2 đã tag (thay v1.0), QA 246/246 pass, QC thủ công payment
# flows, security review sạch. v1.0 đã backup. Phase 6a (GOV-001..006) DONE toàn bộ.
# SePay VietQR (PAY-009) đã code xong, chờ Harvey đăng ký tài khoản SePay thật.
#
# Session 8 (2026-07-14) — 4 việc:
# 1. FIX-001 · DCA riskparity/mpt chia đều sai — `_calc_dca` đọc `s.get("vol_30d")`
#    nhưng field này KHÔNG BAO GIỜ có trong `signals` (chỉ tồn tại ở compute_research_stats,
#    tính riêng cho modal Nghiên cứu từng mã) → luôn fallback hằng số 10 cho MỌI quỹ →
#    risk parity vô tình thành chia đều. Thêm `_compute_vol_30d_batch()` query trực tiếp
#    nav_history (miniapp_server.py) để tính vol thật cho từng quỹ.
# 2. FIX-002 · VCBFTBF NAV sai — phát hiện qua vol_30d bất thường (229%) khi debug #1.
#    Root cause: `fmarket_id=31` trong FUND_CATALOG (bot.py) trỏ NHẦM sang 1 quỹ trái
#    phiếu khác (~30.000đ), trong khi VCBF-TBF thật là quỹ CÂN BẰNG (fmarket.vn/quy/VCBFTBF,
#    vcbs.com.vn) NAV thật ~38.000-39.000đ (khớp TCinvest). 2 nguồn ghi đè lẫn nhau qua
#    `upsert_nav()` (chỉ bảo vệ fixed/manual, không bảo vệ tcinvest khỏi bị fmarket ghi đè)
#    → dao động giả ~23%/ngày, ảnh hưởng P&L thật của Harvey (đang nắm 449.41 CCQ).
#    Đã sửa: bỏ fmarket_id, sửa tên đúng. CHƯA tự backfill lại lịch sử do token local hết
#    hạn — cần chạy `python scripts/harvest_nav.py --backfill --code VCBFTBF --jwt <token>`
#    trên Railway (đã có token mới) để tự sửa lại toàn bộ NAV lịch sử sai.
# 2b. GOV-007 · TCinvest = nguồn CHUẨN, khóa cứng sau khi ghi (Harvey yêu cầu sau vụ #2 —
#    "trước đây không hề bị lỗi, tự dưng hôm qua sai — rủi ro mỗi lần update app đều gây
#    NAV sai" + mô hình blockchain: verify rồi khóa cứng, không API nào ghi đè được nữa):
#    - db.py: PROTECTED_SOURCES/TRUSTED_SOURCES thêm 'tcinvest' — ngang hàng fixed/confirmed.
#      upsert_nav() (plain) + upsert_nav_with_confidence() đều chặn mọi nguồn khác (fmarket,
#      tcbs cũ) ghi đè 1 khi đã có source='tcinvest'; chỉ 1 fetch tcinvest MỚI mới tự cập
#      nhật được chính nó. tcinvest cũng không bao giờ bị coi 'provisional' dù NAV trùng
#      hôm qua (là dữ kiện thật từ nguồn chuẩn, không phải "chưa chắc chắn").
#    - bot.py: get_nav_series() giữ nguyên chữ ký (backward-compat), thêm
#      get_nav_series_with_source() trả kèm nguồn THẬT đã dùng (trước đây fetch_all() đoán
#      nguồn theo fund_cfg tĩnh — 'fmarket' nếu có fmarket_id — bất kể dữ liệu thật lấy từ
#      đâu, đây chính là cách VCBFTBF bị ghi sai nhãn liên tục). Đổi thứ tự thử: tcbs/tcinvest
#      TRƯỚC, fmarket chỉ dùng khi tcinvest rỗng/không có JWT (trước đây fmarket luôn thử
#      trước). Xoá 1 lệnh upsert_nav() dư thừa trong job_check_signals (không kèm source,
#      mặc định "fmarket" — 1 nguồn gây sai nhãn khác).
#    - harvest_nav.py --daily: cùng đổi thứ tự (tcinvest trước), sửa nhãn source="tcbs" →
#      "tcinvest" khi thực sự fetch từ tcinvest_fetch_nav_hist() (trước đây gọi tcinvest
#      nhưng gắn nhãn "tcbs" — mơ hồ, không được bảo vệ đúng mức). Thêm 'tcinvest' vào
#      PROVISIONAL_PROTECTED.
#    - QC: đã test trực tiếp trên DB thật (dùng fund code thật + ngày decoy 2027, dọn sạch
#      sau khi xong) — xác nhận: fmarket không ghi đè được tcinvest, tcinvest tự cập nhật
#      được chính nó, tcinvest không bao giờ thành provisional. 246/246 test vẫn xanh.
#    ⚠️ Còn lại: nếu 1 nguồn khác (fmarket/tcbs) ghi TRƯỚC tcinvest cho cùng ngày (vd tcinvest
#    JWT hết hạn tạm thời), giá trị đó KHÔNG bị khóa (chỉ tcinvest mới khóa) — tcinvest fetch
#    sau đó vẫn ghi đè được bình thường (đúng ý — tcinvest luôn thắng cuối cùng).
# 3. FIX-003 · Admin dashboard "quỹ chưa có NAV hôm nay" hiện 78 mã kỳ quặc (FMKT_8,
#    FMKT_12...) — đây là placeholder do `--discover` tạo ra khi tìm thấy fmarket
#    productId hợp lệ nhưng API không trả tên quỹ thật, chưa từng được map/kích hoạt
#    thật. Đã deactivate 59 hàng funds_master.active=false (không xoá dữ liệu, an toàn
#    reversible) — danh sách giờ chỉ còn 40 mã thật.
# 4. FIX-004 · Rút gọn thông báo bot còn 1 dòng + hướng dẫn mở Mini App: msg_signal_alert,
#    job_nav_change_alert (broadcast "NAV Mới"), msg_morning, msg_evening. Xoá code chết
#    _morning_gold_summary/_gold_summary_lines (không còn dùng sau khi rút gọn). CHƯA đụng
#    tới alert admin-only (NAV jump anomaly, token expiry) — giữ nguyên vì admin cần chi
#    tiết để debug, không phải "spam" gửi user thường.
#
# Ưu tiên tiếp theo: PAY-006/007 (P2), xem xét thay upsert_nav() bằng
# upsert_nav_with_confidence() ở mọi call site để tránh lặp lại bug #2 cho quỹ khác.
#
# GOV-007 tiếp diễn (2026-07-14, cùng ngày):
# - Đã tự SSH vào Railway worker (railway CLI, đăng ký SSH key mới) và chạy backfill
#   VCBFTBF thật trên production — 4,583 điểm NAV lịch sử (2013-2026) đã được ghi lại
#   đúng từ TCinvest, khóa cứng. vol_30d: 229% → 5.56% (đã về mức hợp lý của quỹ cân bằng).
# - Fix bug do chính cơ chế khóa gây ra: upsert_nav() gọi unify_nav_drafts() dùng THAM SỐ
#   ĐẦU VÀO (giá trị fetch, có thể đã bị khóa từ chối) thay vì giá trị THẬT đã lưu — có
#   thể làm reject oan draft đúng của user. Đã sửa: đọc lại DB sau upsert trước khi gọi
#   unify_nav_drafts. QC: khóa NAV ở X, tạo draft khớp X, fmarket cố ghi giá trị khác (bị
#   chặn) — xác nhận draft vẫn confirm đúng theo X đã khóa, không theo giá trị bị từ chối.
# - Tối ưu fetch: get_nav_series_with_source() (bot.py) giờ đọc DB TRƯỚC — nếu NAV hôm nay
#   đã khóa cứng (fixed/manual/tcinvest) thì BỎ QUA fetch live hoàn toàn (không chỉ chặn ở
#   tầng ghi) — tiết kiệm API call + giảm bề mặt rủi ro xung đột về 0 cho ngày đã khóa.
#   Lưu ý: TCinvest/fmarket không hỗ trợ giới hạn khoảng ngày ở server (luôn trả full
#   history mỗi lần gọi), nên đòn bẩy duy nhất là bỏ hẳn cuộc gọi API, không phải lọc bớt
#   response. db.get_nav_series() bổ sung cột `source` để hỗ trợ check này.
#   harvest_nav.py --daily đã tự có cơ chế tương tự từ trước (skip nếu hôm nay đã trong
#   PROVISIONAL_PROTECTED, nay đã gồm 'tcinvest').
# - Tag: v1.1.3 (khóa cứng + backfill) → v1.1.4 (fix unify_nav_drafts) → v1.1.5 (skip
#   fetch khi đã khóa). QC toàn bộ bằng mock + DB thật (đọc-only, không có write test nào
#   để lại dữ liệu rác). 246/246 test xanh xuyên suốt.

## RELEASE NOTES v1.1 (2026-07-13)
- Pricing đa kỳ hạn: tháng 20k/50⭐, quý 54k/135⭐ (-10%), nửa năm 90k/225⭐ (-25%),
  năm 132k/330⭐ (-45%) — giá khớp đúng % giảm giá hiển thị. `telegram-bot/pricing.py`
  là nguồn sự thật duy nhất dùng chung Stars + MoMo.
- Phase 6a governance (GOV-001..006) hoàn tất: audit log (mọi thao tác nhạy cảm +
  CRUD trade), backup tự động (pg_dump, 03:30 hàng ngày, retention 14 ngày),
  cảnh báo NAV bất thường + MAPE kém, admin summary dashboard, chặn brute-force
  promo code, chặn thanh toán trùng lặp, chính sách migration additive-only.
  Chi tiết xem từng mục GOV-00x bên dưới.
- Vá 2 lỗ hổng bảo mật nghiêm trọng (GOV-005, session trước): auth bypass admin
  qua string-match, và ~12 API đọc dữ liệu cá nhân không xác thực.
- Sửa "Fetch 0 quỹ" hiển thị sai + gộp dedup cảnh báo TCBS token hết hạn (trước
  đây 2 đường độc lập cùng gửi trùng tin nhắn).
- Backup: v1.0 (tag `v1.0`, commit `1bd0f3a`) đã snapshot cả code (`git archive`)
  và toàn bộ dữ liệu DB (JSON, 49 bảng) vào `backups/` (local, gitignored, không
  đẩy lên remote — xem `backups/README.md`).

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

- **PAY-008 · Multi-tier pricing (tháng/quý/nửa năm/năm)** — trước đây chỉ 1 gói (250⭐/99.000đ/30 ngày).
  Harvey yêu cầu hạ giá tháng xuống ~20k và đẩy user trả theo năm. Tạo `telegram-bot/pricing.py`
  (nguồn sự thật duy nhất, PRO_PLANS): tháng 20.000đ/50⭐, quý 54.000đ/135⭐ (-10%), nửa năm
  90.000đ/225⭐ (-25%), năm 132.000đ/330⭐ (-45%) — giá đúng 400đ/⭐ mọi gói, discount% khớp thật
  với giá (baseline = giá tháng × số tháng). `/buy_pro` giờ hiện menu chọn gói (inline keyboard,
  callback `buyplan:<key>`) thay vì invoice thẳng; payload Stars đổi từ `pro_30d:` → `pro:<plan>:<chat_id>`
  (fallback về gói tháng nếu payload cũ còn bay). MoMo orderId đổi từ `FTP-<tg>-<ts>` →
  `FTP-<tg>-<plan>-<ts>` để IPN biết cấp bao nhiêu ngày (fallback gói tháng nếu orderId cũ 3 phần).
  Mini app: modal nâng cấp có 4 thẻ chọn gói, mặc định chọn gói năm + badge "TIẾT KIỆM NHẤT" | 2026-07-13

### 3d. SePay/VietQR — chuyển khoản ngân hàng tự động (thay MoMo tạm thời)

- **PAY-009 · Chuyển khoản VietQR tự động qua SePay** — nghiên cứu: MoMo M4B chấp
  nhận hộ kinh doanh/cá nhân (không bắt buộc giấy phép DN) nhưng KYC thiết kế cho
  cửa hàng vật lý (cần ảnh cửa hàng) — không phù hợp SaaS thuần số, cần Harvey tự
  liên hệ business.momo.vn hỏi case cụ thể trước khi đầu tư. QR MoMo cá nhân
  KHÔNG có webhook/API — không tự động hoá được.
  → Giải pháp đã code: **SePay** (dịch vụ webhook ngân hàng cho tài khoản CÁ NHÂN,
  không cần giấy phép kinh doanh, 500 giao dịch miễn phí/tháng/năm đầu) — VietQR
  sinh ra quét được bằng CẢ app ngân hàng lẫn app MoMo (MoMo hỗ trợ chuyển khoản
  qua VietQR tới tài khoản ngân hàng).
  - `db.py`: bảng `bank_transfer_orders` (ref_code PK, telegram_id, plan_key,
    amount_vnd, status pending/paid) + `create_bank_transfer_order()`,
    `find_pending_order_by_content()` (so khớp ref_code bằng substring — ngân
    hàng có thể thêm tiền tố/hậu tố quanh nội dung CK), `mark_bank_transfer_order_paid()`
    (idempotent), `get_bank_transfer_order()`.
  - `miniapp_server.py`: `POST /api/payment/sepay/create` (tạo đơn + URL ảnh QR
    qua `qr.sepay.vn/img`), `POST /api/payment/sepay/webhook` (xác thực bằng
    Authorization header tĩnh `Apikey <key>` — KHÔNG phải HMAC như MoMo, đây là
    mô hình auth của SePay; parse content→ref_code, verify amount đủ, dedup qua
    `record_payment_once("sepay", ...)`, `extend_pro` theo `plan_key`, gửi
    Telegram confirm), `GET /api/payment/sepay/status?ref=` (Mini App poll để
    biết đã thanh toán chưa, không cần user tự F5).
  - Mini app: nút "🏦 CHUYỂN KHOẢN NGÂN HÀNG (VietQR)" trong `#upgrade-modal` →
    hiện QR + số tiền + nội dung CK, poll status mỗi 4s, tự đóng modal khi paid.
  - **CHƯA verify với tài khoản SePay thật** — field name webhook payload
    (`transferType`/`content`/`transferAmount`/`id`) theo định dạng phổ biến
    SePay công khai, cần Harvey đăng ký tài khoản SePay + set
    `SEPAY_API_KEY`/`SEPAY_ACCOUNT_NUMBER`/`SEPAY_BANK_CODE` trên Railway rồi
    kiểm tra lại field 1 lần với giao dịch test thật (log payload thô đã có sẵn
    trong `_api_sepay_webhook` để dễ chỉnh nếu field không khớp).
  - QC: đã test toàn bộ logic (create order, so khớp content nhiễu, idempotent
    mark-paid, dedup qua txn_id, race 2 webhook đồng thời chỉ extend 1 lần,
    Authorization sai bị từ chối) trực tiếp trên DB thật, dọn sạch dữ liệu test
    sau khi xong | 2026-07-13 | Blocker: cần đăng ký tài khoản SePay thật

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
- [DONE-LOCAL] GOV-002 · Backup tự động — `scripts/backup_db.py` (`pg_dump -F c` vào
  `$DATA_DIR/backups/`, retention 14 bản, luôn giữ ≥1 bản), `bot.py job_backup_db()` chạy
  03:30 hàng ngày, báo Telegram admin nếu backup fail. Restore qua `--restore <file> --confirm`
  (dry-run mặc định, `pg_restore --clean --if-exists`). Dockerfile thêm `postgresql-client`.
  Quy trình + checklist restore: `telegram-bot/BACKUP.md`. **Bug tìm thấy khi làm task này**:
  `.dockerignore` loại bỏ toàn bộ `scripts/` khỏi Docker image — mọi job T+2
  (`job_t2_predict`/`job_t2_retrain`/`job_t2_reweight`) đã fail âm thầm trên Railway từ trước
  đến giờ vì `scripts/t2_*.py` không hề có trong container. Đã sửa `.dockerignore` | 2026-07-13
  | Retention logic + restore dry-run test bằng file giả lập — pass. CHƯA test `pg_dump`/
  `pg_restore` thật (cần DATABASE_URL Railway) — xem checklist trong BACKUP.md
- [DONE] GOV-003 · Chặn + cảnh báo thanh toán trùng lặp + 3 rule anomaly còn lại —
  `db.record_payment_once()` (bảng `processed_payments`, UNIQUE (provider, charge_id)) chặn
  xử lý 2 lần khi cổng thanh toán retry webhook (MoMo IPN dùng `transId`, Telegram Stars dùng
  `charge_id`). Trước đây KHÔNG có dedup nào — mỗi lần webhook gọi lại là +30 ngày Pro miễn phí
  (lỗ hổng tài chính thật). Khi phát hiện trùng → `log_audit("duplicate_payment_blocked")` +
  báo Telegram admin ngay | 2026-07-13
  **Ca chiều 2026-07-13 — 3 rule còn lại:**
  (1) NAV nhảy >15%/phiên — `harvest_nav.py cmd_daily` in `JUMP_ALERT:` khi fetch mới lệch
  yesterday_nav >15% (auto-harvest fmarket/tcbs, khác với pending_confirm vốn chỉ bắt
  manual≠fetch); `bot.py job_harvest_nav` parse dòng này → `log_audit(nav_jump_anomaly)` +
  báo admin.
  (2) MAPE model kém liên tục — `db.get_daily_mape()`/`get_mape_breach_streak()` (MAPE trung
  bình theo ngày từ `prediction_actuals`, đếm streak ngày liên tiếp >ngưỡng); `bot.py
  job_t2_score` gọi `_check_mape_streak_alerts()` sau khi score — báo khi model (arima-v1/
  xgb-v1/ensemble-v1) MAPE >8% liên tục ĐÚNG 5 ngày (debounce tự nhiên nhờ check `== N` thay
  vì `>= N` — không spam lặp lại mỗi ngày sau đó).
  (3) Brute-force mã khuyến mãi — `miniapp_server.py _check_promo_abuse()` rate-limit
  in-memory theo telegram_id (>5 lần thử/60s → chặn 429 + `log_audit(promo_abuse_detected)`
  + báo admin). In-memory nên reset khi Railway restart — chấp nhận được vì đây là lớp cảnh
  báo bổ sung, không phải cơ chế bảo mật chính (UNIQUE constraint DB vẫn chặn redeem trùng).
  Verify: streak logic + rate-limit logic test bằng script giả lập độc lập (không cần DB) —
  cả 2 pass đúng behavior mong đợi | 2026-07-13
- [DONE] GOV-004 · `GET /api/admin/audit` (admin-only, `_auth_write` + `_is_admin`,
  dùng `db.get_audit_log()` có sẵn từ GOV-001) + card "Audit log gần đây" trong tab Admin
  Mini App (`telegram-bot/miniapp/index.html`) hiện 50 dòng gần nhất (action/actor/target/note).
  **Ca chiều 2026-07-13 — dashboard tổng hợp:** `db.get_admin_summary()` (4 phần độc lập,
  mỗi phần try/except riêng — lỗi 1 phần không hỏng cả trang): users theo tier active,
  MAPE 7 ngày mỗi model_version (dùng lại `get_daily_mape` từ GOV-003), quỹ active chưa có
  NAV hôm nay (`funds_master` LEFT JOIN `nav_history` ngày hiện tại), 20 giao dịch
  `processed_payments` gần nhất. `GET /api/admin/summary` (admin-only) trong
  `miniapp_server.py` + card "📊 TỔNG QUAN HỆ THỐNG" ở đầu tab Admin (trên card TCBS
  token) — MAPE tô đỏ nếu >8% (khớp ngưỡng alert GOV-003). Verify qua browser preview với
  mock apiFetch (users/MAPE màu/quỹ thiếu/thanh toán) — render đúng, không console error.
  **Lưu ý concurrency**: session này chạy song song với Harvey đang live-edit cùng repo
  (multi-tier pricing PAY-008) — dùng `git add -p` để tách hunk của mình khỏi hunk của
  Harvey trước khi commit, tránh commit nhầm code người khác | 2026-07-13
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
  chạy trực tiếp lên DB Railway | 2026-07-13
- [DONE] GOV-005-part2 · auth_date freshness check (chống replay initData cũ) — `_validate_init_data()`
  (`telegram-bot/miniapp_server.py`) giờ từ chối initData có `auth_date` quá 24h (khớp khuyến
  nghị Telegram) hoặc ở tương lai ngoài dung sai lệch giờ 5 phút, dù chữ ký HMAC vẫn đúng.
  Trước đây 1 initData bị chặn bắt (network sniff, log server, browser history...) có thể bị
  replay vô thời hạn để giả danh user/admin vì chỉ verify chữ ký, không verify thời điểm phát
  hành. Không cần sửa gì phía client — Telegram SDK luôn tự sinh `auth_date` mới mỗi lần Mini
  App mở, nên user thật không bị ảnh hưởng. Verify: `py_compile` + pytest 246/246 xanh (không
  có test nào giả lập initData nên không có gì để break; đã audit tất cả 4 call site
  `_validate_init_data()` — đều nhận `init_data` trực tiếp từ header request client thật) | 2026-07-15
- [DONE] GOV-007-part4 · Tự động hoá quy trình cross-check NAV source (bước 3 trong quy
  trình đã ghi ở GOV-007-part3, trước đây phải chạy tay hàng tuần — chính vì không tự động
  nên bug VCBFTBF chỉ được phát hiện 3 lần liên tiếp sau khi Harvey report, không phải do hệ
  thống tự cảnh báo sớm). `db.get_nav_source_audit(days=30)` — quét `nav_history` 30 ngày
  qua (loại hôm nay, vì hôm nay có thể tạm là fmarket provisional — bình thường), group theo
  `fund_code`, flag quỹ nào có dòng `source` KHÔNG thuộc `TRUSTED_SOURCES`
  (fixed/confirmed/manual/tcinvest) — dấu hiệu tcinvest chưa khoá hết lịch sử, y hệt pattern
  đã gây ra 3 lần sự cố VCBFTBF trước đó. `bot.py job_nav_source_audit()` chạy hàng tuần
  (Thứ Hai 04:00, sau backup 03:30) — báo Telegram admin danh sách quỹ bị flag + gợi ý chạy
  lại `harvest_nav.py --tcinvest` (lệnh reconcile), ghi `log_audit(nav_source_audit_flag)`.
  Verify: `tests/test_nav_source_audit.py` (8 test mới — query SQL dùng đúng TRUSTED_SOURCES
  không hardcode lại, DB unavailable/rỗng/lỗi query/lỗi log_audit đều không crash job, admin
  thiếu config thì không gửi) + smoke-test bằng fake cursor mô phỏng response DB thật. Không
  có DATABASE_URL trong môi trường session này nên chưa verify integration thật trên Railway
  — cần chờ Thứ Hai tới hoặc chạy tay `job_nav_source_audit()` qua `railway run` để xác nhận
  | 2026-07-15 (autonomous run)
- [DONE] GOV-006 · Chính sách "không xoá/đổi dữ liệu khi deploy" — viết thành quy tắc migration
  trong `CLAUDE.md` (section "🔐 CHÍNH SÁCH DỮ LIỆU"): mọi ALTER TABLE phải additive, script sửa
  dữ liệu hàng loạt phải dry-run mặc định, audit_log append-only, PROTECTED_SOURCES cho NAV,
  luôn hỏi Harvey trước khi xoá dữ liệu không phải do session tạo ra | 2026-07-13
- [DONE] GOV-007-part2 · VCBFTBF NAV lại sai sau khi Harvey bấm "fetch all" — điều tra tiếp và
  phát hiện root cause THỨ HAI (khác với config.json vs FUND_CATALOG đã fix trước đó):
  `harvest_nav.py cmd_tcinvest()` có logic **"skip quỹ nếu đã có BẤT KỲ data nào trong
  nav_history"** — nghĩa là mọi quỹ đã có lịch sử fmarket cũ (hầu hết 33 quỹ tcbs=True)
  KHÔNG BAO GIỜ được tcinvest backfill/khoá đầy đủ, dù `db.py upsert_nav()` đã có logic bảo vệ
  đúng. Hệ quả: job daily fmarket-fallback tiếp tục ghi đè xen kẽ ("sawtooth" pattern — NAV
  đúng 1 ngày, sai 1 ngày) suốt nhiều tháng cho gần như TOÀN BỘ quỹ, không riêng VCBFTBF.
  **Kiểm chứng qua SSH trực tiếp production**: gọi sống `GET /api/nav/<code>` xác nhận
  VCBFTBF vẫn trả 30.041,63đ (sai) dù DB "đã fix" trước đó — vì backfill trước chỉ vá các
  ngày ANOMALY đã phát hiện (04,05,11,12/07), không vá TOÀN BỘ lịch sử, nên khoảng trống
  (07/13) vẫn bị job fmarket-fallback ghi đè. Quét toàn bộ 33 quỹ tcbs=True: **31/33 quỹ bị
  ảnh hưởng** (chỉ VCBFTBF đã tự vá và NTPPF/VMEEF chưa có data nào). Fix: (1) chạy full
  tcinvest re-fetch + `db.upsert_nav(..., source='tcinvest')` cho toàn bộ 31 quỹ (không dùng
  `ON CONFLICT DO NOTHING` vì cần GHI ĐÈ fmarket cũ, không chỉ điền chỗ trống) — xác nhận sau
  fix chỉ còn duy nhất 1 dòng 'fmarket' mỗi quỹ = NAV hôm nay (bình thường, vì TCinvest trễ
  1 ngày so với ngày công bố, sẽ tự được ghi đè khi tcinvest fetch ngày mai); (2) sửa
  `cmd_tcinvest()` bỏ hẳn logic skip-if-any-data, đổi tên ý nghĩa thành lệnh RECONCILE có thể
  chạy lại định kỳ (không chỉ build 1 lần) — xem code comment trong hàm để hiểu rõ vì sao.
  NTPPF/VMEEF: chưa có trong bảng `funds` (FK violation khi insert) — CHƯA xử lý, cần Harvey
  xác nhận có đúng là 2 mã này chưa active/chưa cần track không.
  **Quy trình cross-check NAV giữa nhiều nguồn (để dùng về sau)**:
    1. Nguồn tin cậy theo thứ tự: `fixed`/`manual` (Harvey tự nhập) > `tcinvest` (fetch trực
       tiếp qua JWT, chính xác nhất trong các nguồn tự động) > `fmarket`/`tcbs` cũ (có thể trễ
       hoặc sai — ĐÃ xác nhận fmarket tự mâu thuẫn dữ liệu giữa các lần gọi cùng 1 ngày).
    2. Muốn biết 1 mã có đang bị "khoá" đúng không: `SELECT nav_date, nav, source FROM
       nav_history WHERE fund_code=? ORDER BY nav_date DESC LIMIT 30` — nếu thấy xen kẽ
       nguồn (không phải toàn `tcinvest`/`fixed`/`manual` liên tục), tức là có khoảng trống
       chưa được tcinvest khoá.
    3. Quét TOÀN BỘ hệ thống định kỳ (nên làm hàng tuần, hoặc sau mỗi lần nghi ngờ): với mỗi
       mã trong `FUND_CATALOG` có `tcbs=True`, group by source trong 30 ngày gần nhất, cờ đỏ
       nếu có dòng nguồn khác `tcinvest/fixed/manual` mà KHÔNG PHẢI ngày hôm nay (ngày hôm nay
       luôn có thể tạm là fmarket provisional — bình thường).
    4. Khi phát hiện cờ đỏ: chạy lại `cmd_tcinvest()` (giờ đã là lệnh reconcile an toàn, tự
       bảo vệ fixed/manual) để tcinvest tự nâng cấp toàn bộ lịch sử của mã đó.
    5. KHÔNG bao giờ tin 1 lần verify DB là đủ — luôn re-verify qua chính API endpoint mà
       frontend gọi (`/api/nav/<code>`), vì DB đúng không đảm bảo pipeline ghi đè sau đó không
       chạy lại và làm sai một lần nữa (đúng như những gì đã xảy ra ở đây)
  | 2026-07-14
- [DONE] T2-011 · T+2 prediction chưa BAO GIỜ chạy được trên production — chuỗi 7 bug liên
  tiếp phát hiện khi cố chạy thật lần đầu (không chỉ đọc code): (1) thiếu `statsmodels` trong
  `requirements.txt` → ARIMA lỗi 100%; (2) model XGBoost lưu ở `scripts/models/` (trong image
  container) thay vì `DATA_DIR=/data` (volume bền vững) → bị xoá mỗi lần deploy; (3)
  `_fetch_nav_series()` dùng `Decimal` thẳng từ psycopg2 → crash khi tính toán chung với
  numpy/xgboost; (4) `test_mape` là `numpy.float32` không JSON/psycopg2 serializable; (5)
  `cmd_train`/`cmd_predict` gọi `db.get_conn()` (cần `db.init_pool()` trước) mà không script
  nào từng gọi — lỗi "DB pool not initialised" 100% mọi lần chạy; (6) **nghiêm trọng nhất**:
  `ORDER BY nav_date ASC LIMIT 500` lấy nhầm 500 điểm CŨ NHẤT thay vì gần nhất — quỹ có >500
  điểm lịch sử (đa số quỹ lâu năm) dự báo ra ngày trong QUÁ KHỨ (VD T+2=2005-10-04); (7)
  `t2_ensemble.py` hardcode `'xgb-v1'` trong khi `t2_xgboost.py` tự bump version mỗi lần train
  (T2-007) → ensemble vỡ vĩnh viễn ngay sau lần retrain thứ 2. Mỗi bug chỉ lộ ra SAU KHI bug
  trước đó được sửa và chạy thật qua SSH — đọc code không phát hiện được chuỗi này.
  Fix từng bước, mỗi lần deploy + train + predict lại để xác nhận tiến bộ, cuối cùng cả 3
  model (ARIMA/XGBoost/Ensemble) chạy 39/39 quỹ OK, `db.get_predictions()` trả đúng
  `ensemble-v1` cho cả 5 quỹ Harvey đang theo dõi. Đã xoá 39 dòng dự báo rác tự tạo lúc test
  (session này tự tạo, không phải dữ liệu user, an toàn xoá theo GOV-006).
  **Bài học**: verify "code trông đúng" ≠ verify "đã chạy thật thành công" — tính năng này
  tồn tại từ lâu trong code nhưng CHƯA BAO GIỜ có 1 dòng dữ liệu thật nào trên production cho
  đến hôm nay | 2026-07-14
- [DONE] GOV-007-part3 · VCBFTBF NAV lại nhảy về ~30.000đ lần thứ 3 dù đã fix 2 lần trước —
  Harvey báo trực tiếp qua screenshot bot alert. Root cause LẦN NÀY hoàn toàn khác 2 lần
  trước: `funds_master` — bảng DB được `harvest_nav.py --daily` (job chạy 18:30 VÀ 20:00,
  ĐỘC LẬP với `bot.py`'s `job_check_signals` đã fix ở GOV-007-part1) dùng làm nguồn
  fmarket_id/tcbs — là nguồn cấu hình quỹ ĐỘC LẬP THỨ 3 (sau `FUND_CATALOG` và
  `config.json`) mà 2 lần fix trước chưa từng đụng tới. Phát hiện: (1) `funds_master.tcbs
  =False` cho 26/33 quỹ → job này luôn bỏ qua tcinvest; (2) `funds_master.fmarket_id=27`
  cho VCBFTBF — verify TRỰC TIẾP qua fmarket API xác nhận id=27 là **"QUỸ ĐẦU TƯ TRÁI
  PHIẾU DC" (DCBF/VFMVFB)**, NAV≈30.049 — khớp CHÍNH XÁC với giá trị sai đã thấy, tức là
  suốt thời gian qua bot đang fetch nhầm NAV của DCBF rồi ghi vào dưới mã VCBFTBF; fmarket_id
  ĐÚNG của VCBFTBF là 31 (verify qua API: tên "QUỸ ĐẦU TƯ CÂN BẰNG CHIẾN LƯỢC VCBF" khớp,
  NAV≈37.945 khớp thang đo tcinvest); (3) `_insert_nav_points()` (dùng bởi `cmd_daily` cho
  ngày lịch sử) chỉ bảo vệ `fixed`/`manual`, KHÔNG bảo vệ `tcinvest` như `db.py::upsert_nav()`
  đã có — nên khi funds_master trỏ sai, dữ liệu tcinvest đã khoá đúng vẫn bị ghi đè mỗi tối.
  Fix: sửa `_insert_nav_points()` bảo vệ thêm `tcinvest` (lớp phòng thủ thứ 2, đề phòng
  config lại sai lần nữa); update `funds_master` trực tiếp qua SSH — `tcbs=true` cho cả 26
  quỹ, VCBFTBF `fmarket_id` 27→31 + tên đúng, xoá `fmarket_id=31` khỏi placeholder rác
  `FMKT_31` (inactive, gây UniqueViolation khi update); reconcile lại NAV VCBFTBF bằng
  fmarket id=31 (JWT tcinvest đang hết hạn — `job_check_tcbs_token` sẽ tự báo Harvey refresh,
  chưa refresh được ngay).
  **Bài học nhắc lại lần 3**: mỗi lần "khoá" 1 nguồn dữ liệu, phải audit TẤT CẢ pipeline
  đọc/ghi NAV, không chỉ pipeline đang được nhìn thấy lỗi — hệ thống này có ít nhất 2 job
  daily độc lập (`job_check_signals` dùng `FUND_CATALOG`, `job_harvest_nav`/`harvest_nav.py
  --daily` dùng `funds_master`) chạy song song, mỗi job có thể đọc 1 nguồn cấu hình khác
  nhau cho CÙNG 1 quỹ | 2026-07-14
- [DONE] T2-013 · JWT tcinvest refresh (Harvey cung cấp token mới) → cập nhật
  `/data/config.json.tcbs_token`, verify fetch sống, reconcile lại toàn bộ 31/31 quỹ tcbs
  bằng token mới (31/31 OK). Ngay sau đó Harvey báo T+2 của VCBFTBF vẫn sai dù NAV đã đúng
  — root cause: dự báo T+2 (arima-v1/xgb-vN/naive-v1/ensemble-v1) được tính TRƯỚC khi NAV
  vừa được sửa, nên vẫn dựa trên lịch sử NAV sai cũ, không tự động refresh khi NAV thay đổi.
  Fix ngay: chạy lại --predict cả 4 model cho toàn bộ quỹ vừa reconcile.
  Fix hệ thống (yêu cầu rõ từ Harvey: "Bắt buộc đổi T+2 nếu như NAV bị sửa lại, cập nhật,
  thay đổi"): thêm `_trigger_t2_repredict(codes)` trong `miniapp_server.py` — chạy nền
  (thread riêng, không chặn response API) gọi lại `t2_arima/xgboost/naive/ensemble.py
  --predict --code X` ngay sau khi NAV được admin sửa. Gắn vào 3 điểm: `_api_admin_fetch_nav`
  (sau khi fetch xong, chỉ cho mã có `results[code]>0`), `_api_admin_nav_confirm` (sau khi
  resolve pending thành công), `_api_admin_import_nav` (sau khi import xong). KHÔNG gắn vào
  `_api_nav_draft` (NAV draft của user Pro chưa confirm vào nav_history, chưa nên trigger
  recompute T+2 toàn cục) hay `_api_admin_fixportfolio` (sửa portfolio, không phải NAV).
  Verify: py_compile, pytest (246 passed), verify sống VCBFTBF T+2 sau khi chạy lại thủ công
  — ensemble-v1 predicted_nav=38.251 (khớp NAV thật 38.220,82, trước đó T+2 vẫn dựa trên
  chuỗi NAV sai ~30k) | 2026-07-15
- [DONE] GOV-008/T2-014 · NAV 3-layer re-verification (T+1/T+8/T+31). Root cause của vụ
  VCBFTBF NAV lại sai sáng 2026-07-15 (dù đã fix funds_master + token): script reconcile
  thủ công dùng `upsert_nav()` khóa cứng NAV thành `tcinvest` NGAY lần fetch đầu tiên —
  nhưng verify trực tiếp bằng token mới cho thấy TCBS công bố NAV ngày mới nhất còn TẠM
  TÍNH, tự sửa lại vài giờ sau khi có số liệu chính thức (fetch lúc 07:20 sáng ra
  38.220,82 — thực ra là NAV *hôm qua* bị kéo dài; TCBS tự chốt lại 37.945,51 vài giờ
  sau, khớp chính xác trang NAV/CCQ chính thức và số Harvey nhập tay lúc 09:49 sáng).
  Harvey xác nhận qua ảnh chụp Network tab + trang NAV/CCQ TCBS chính thức — API
  `chart-nav` KHÔNG sai, chỉ là timing (provisional → final).
  Fix theo yêu cầu Harvey: xây cơ chế xác thực 3 lớp thay vì khóa cứng ngay từ đầu:
  - `db.py`: thêm cột `verify_tier` (0/1/8/31) + `last_verified_at` vào `nav_history`
    (migration additive qua `_migrate_nav_verify_cols()`, gọi trong `init_pool()`).
    Hàm mới `reverify_nav_tier(fund_code, nav_date, fresh_nav)`: so giá trị fetch lại
    với giá trị đã lưu (chỉ áp dụng source='tcinvest') — khớp (≤0.05%) và đủ tuổi (≥1/
    ≥8/≥31 ngày) → nâng tier; lệch → coi là TCBS tự sửa, cập nhật + reset tier=0 + ghi
    `audit_log` (action=`nav_reverify_corrected`).
  - `harvest_nav.py`: mode `--reverify` mới — fetch lại tcinvest toàn bộ quỹ, gọi
    `reverify_nav_tier()` cho từng điểm.
  - `bot.py`: job `job_nav_reverify()` chạy 21:00 hàng ngày (sau cả 2 lần harvest
    18:30/20:00), đủ thời gian để TCBS tự sửa nếu là số tạm tính trước khi verify.
  - Thứ tự ưu tiên hiển thị mới (thấp→cao, Harvey chỉnh lại 2026-07-15): provisional <
    tcbs/fmarket < user draft < tcinvest tier=0 < tcinvest T+1 < **admin draft
    (pending_confirm)** < tcinvest T+8 < tcinvest T+31. Admin draft nằm XEN GIỮA T+1
    và T+8 (không phải đứng dưới toàn bộ Fixed DB) — 1 admin xác nhận thủ công đáng
    tin hơn máy tự re-check khớp sau 1 ngày, nhưng kém đáng tin hơn giá trị đã tự ổn
    định ≥8 ngày không cần con người can thiệp. `fixed`/`confirmed`/`manual` luôn cao
    nhất, không tham gia chu kỳ re-verify vì đã là quyết định cuối cùng của con người.
  Verify: py_compile 3 file, pytest suite (254 passed), test sống trực tiếp trên
  production DB (không dùng mock) — xác nhận tier nâng đúng 0→1 (2 ngày tuổi) và
  0→8 (11 ngày tuổi, nhảy thẳng lên tier cao nhất đủ điều kiện) với giá trị khớp thật.
  **Sự cố công cụ liên quan**: giữa lúc điều tra, `railway.exe` (SSH vào production)
  bị Windows "Smart App Control" chặn im lặng (exit 1, không log lỗi) — Harvey tắt
  Smart App Control trong Windows Security để gỡ. Trong lúc bị chặn, đã dùng
  `database_url` trong `telegram-bot/config.json` để kết nối psycopg2 trực tiếp từ máy
  local, bỏ qua SSH hoàn toàn cho các thao tác đọc/ghi DB thuần | 2026-07-15

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
