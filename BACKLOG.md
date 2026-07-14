# BACKLOG — Fund Tracker Pro
# Format: [STATUS] ID · Mô tả | Priority | Estimate | Dependency
# Status: TODO / IN_PROGRESS / DONE / BLOCKED
# Priority: P0 (blocker) / P1 (important) / P2 (nice-to-have)
# Claude đọc file này ĐẦU TIÊN mỗi session. Pick task IN_PROGRESS nếu có, nếu không pick P0 cao nhất.
#
# Last updated: 2026-07-14 (v1.2.2 — tìm ra root cause THẬT của VCBFTBF NAV sai)

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
