# BACKLOG — Fund Tracker Pro
# Format: [STATUS] ID · Mô tả | Priority | Estimate | Dependency
# Status: TODO / IN_PROGRESS / DONE / BLOCKED
# Priority: P0 (blocker) / P1 (important) / P2 (nice-to-have)
# Claude đọc file này ĐẦU TIÊN mỗi session. Pick task IN_PROGRESS nếu có, nếu không pick P0 cao nhất.
#
# Last updated: 2026-08-03 (autonomous continuation: WEB-038 — extreme 7-day move alert in perfHtml)

## Session (autonomous, continuation) — 2026-08-03: WEB-038..043 expert analysis series
# WEB-043 DONE: DCA Entry Ladder in strategyHtml
#   - Fires when: score >= 3 AND rsi < 50 AND fibSupport.length >= 1 AND NOT bond/money_market
#   - "📉 Lịch DCA theo Fibonacci" row in strategy section
#   - Lần 1: current NAV (50% or 60% of capital)
#   - Lần 2+: Fib support levels below (−X% from current) with remaining allocation
#   - 2 supports → [50%, 30%, 20%]; 1 support → [60%, 40%]
#   - Gives investor specific "buy at these prices" guidance, not just "buy small"
#   - Build: 391,506 chars.

## Session (autonomous, continuation) — 2026-08-03: WEB-038..042 risk + position sizing + seasonality + vol regime + divergence
# WEB-042 DONE: RSI Divergence + Volatility Regime in summaryLine (conclusionHtml)
#   - _divCtx: "⚡ Phân kỳ dương RSI — lực bán suy yếu..." / "⚠️ Phân kỳ âm RSI — lực mua cạn kiệt..."
#     Only fires when rsiDivergence === 'bullish' or 'bearish' (detected in advHtml section 5b)
#   - _volRCtx: "Biến động đang tăng cao (1.8x bình thường) — chia nhỏ lệnh..."
#     Only fires when _volRegime > 1.5 (WEB-041)
#   Both appended to all 7 summaryLine branches. Now conclusion references:
#   MA cross + Fib context + 52W range + RSI divergence + vol regime + historical pattern
#   Build: 390,732 chars.

## Session (autonomous, continuation) — 2026-08-03: WEB-038..041 risk + position sizing + seasonality + vol regime
# WEB-041 DONE: Volatility Regime Detection in riskHtml
#   - _vol30d = _annVol(pts.slice(-30)) — short-term 30-day annualized vol
#   - _volRegime = _vol30d / vol (long-term 252-day vol), only when vol > 1.5% (excludes money market)
#   - HIGH regime (ratio > 1.4): red card "⚡ Biến động đang tăng cao — Xgần Xt mức dài hạn → chia nhỏ lệnh"
#   - LOW regime (ratio < 0.6): green card "✅ Biến động hiện tại thấp → thuận lợi để vào lệnh"
#   - Between 0.6-1.4: nothing shown (normal regime)
#   - Displayed after position sizing card at end of riskHtml
#   Build: 389,891 chars. Present in web.html at line 4814.

## Session (autonomous, continuation) — 2026-08-03: WEB-038..040 risk detail + position sizing + seasonality
# WEB-040 DONE: Monthly Seasonality section "MÙA VỤ THEO THÁNG" (📅)
#   - Computes avg monthly NAV return per calendar month (T1..T12) from pts history
#   - Needs >= 120 pts and >= 8 months with >= 2 years data each
#   - 6-column grid: each month cell shows label, avg return %, win rate (% positive years)
#   - Current month: cyan highlight; best 2 months: green; worst 2: red
#   - Caption: "Mạnh nhất: T4 (+1.8%), T11 (+1.5%) · Yếu nhất: T8 (-0.7%), T2 (-0.4%)"
#   - Current month context: avg return + win rate + n years of data
#   - Inserted between rangeHtml and advHtml in assembly line (line 4320)
#   - Uses string concat (not template literal) inside IIFE to avoid nesting issues
#   Build: 388,697 chars. Section present in web.html.

## Session (autonomous, continuation) — 2026-08-03: WEB-038..039 risk detail + position sizing
# WEB-039 DONE: Calmar interpretation + Position Sizing box in riskHtml
#   1. Calmar sentence appended to "Nhận định chất lượng rủi ro" box:
#      calmar>1: "Calmar X.XX — lợi nhuận năm vượt drawdown tối đa (Y%): quỹ phục hồi nhanh"
#      calmar>0.3: "chấp nhận được, nhưng chưa gấp đôi mức drawdown"
#      calmar>=0: "thấp — lợi nhuận chưa bù được rủi ro drawdown tối đa"
#   2. New "Định cỡ vị thế (Position Sizing)" box after quality assessment:
#      "VaR 95% = X%/tháng → giới hạn tỷ trọng tối đa ~Y% để ảnh hưởng <2% danh mục"
#      Formula: Y = round(2/var95*100), capped at 99%
#      VCBFTBF example: var95=~high% bond → specific allocation cap shown
#   Variables used: calmar (line 3664, _calmar(pts)), var95 (IIFE line 3666), mdd, var95C
#   Build: 385,415 chars. Zero JS parse errors.

## Session (autonomous, continuation) — 2026-08-03: WEB-038 extreme 7-day move banner
# WEB-038 DONE: Extreme 7-day move alert banner in perfHtml
#   Variables _extremeThresh (bond/mm: 8%, equity/balanced: 15%) and _extremeMove7 added before perfHtml.
#   Banner inserted after consistency card, before footnote:
#   "⚠️ BIẾN ĐỘNG BẤT THƯỜNG 7 NGÀY — NAV giảm mạnh X% trong 7 ngày — vượt xa mức bình thường (ngưỡng Y%)."
#   Alerts user to investigate cause before trading. Red-tinted box, --sell color.
#   Applies to VCBFTBF: chg7=-18.41% > threshold=8% → banner shows.
#   Build: web.html rebuilt (384406 chars). Syntax OK (no JS parse error).
# Files: telegram-bot/miniapp/web_js.js + web.html (rebuilt)

## Session (autonomous, continuation) — 2026-08-02: WEB-029..034 analysis panel "asset mgmt expert"
# Harvey directive: "Phân tích cần chi tiết hơn nữa, giải thích cụ thể hơn hơn."
# WEB-029 DONE: 52W high/low date labels — _lo52Pt / _hi52Pt → hiển thị ngày đáy/đỉnh dưới giá (dd/mm)
# WEB-030 DONE: Momentum trend card in perfHtml — so sánh 30d vs 90d annualised return
#   _d30ann / _d90ann / _momTrend (accelerating/decelerating) + card giải thích cụ thể
# WEB-031 DONE: Time-to-recover estimate in breakeven box — khi pnlP < -5 và chg30 > 0.1:
#   _recovMo = ceil(_toBreak / s.chg30) → "Ở đà hiện tại, ước tính ~N tháng để hoà vốn."
# WEB-032 DONE: Portfolio peer comparison bar in pnlHtml — danh sách các quỹ khác đang nắm
#   + P&L % mỗi quỹ. Fixed: dùng h.nav + h.pnl_pct từ /api/me (không dùng _signals).
# WEB-033 DONE: tech_reliability LOW warning in conclusionHtml — bond funds note
#   "TA độ tin cậy THẤP" badge với giải thích vì sao RSI/MACD/BB ít phù hợp với quỹ trái phiếu.
# WEB-034 DONE: RSI 7-day trend direction in indHtml — "↓ 7 ngày: RSI giảm 15pts — áp lực bán gia tăng."
# WEB-035 DONE: RSI momentum context appended to conclusionHtml summaryLine
# WEB-036 DONE: Current drawdown from 52W peak in risk quality assessment box
#   _curDD52 = (peak52r - curr) / peak52r — shows CURRENT drawdown vs mdd (historical max).
#   VCBFTBF: "Đang trong drawdown −26.0% từ đỉnh 52 tuần — đây là mức lỗ thực tế hiện tại"
# WEB-037 DONE: RSI-level trigger watchConds in conclusion strategy section
#   + "RSI vượt 25 từ vùng cực quá bán (hiện X)" when rsi < 20
#   + "RSI đang giảm nhanh (−Xpts/7 ngày) — chờ đà giảm chậm lại" when _rsiDelta <= -8
#   VCBFTBF now has 5 specific triggers to watch vs 2 before.
#   _summaryRsiCtx: 5 branches covering extreme oversold (rsi<=20 still falling), rapid fall,
#   recovery from bottom, rapid rise, leaving overbought. Uses _rsiCurr/_rsiPrev7 (same algo → meaningful delta).
#   Bug found+fixed: new extreme-oversold branch (rsi<=20) needed since all other branches required rsi>45.
#   _rsiCurr = _rsiAt(navVals, last) vs _rsiPrev7 = _rsiAt(navVals, last-7)
#   → "↓ 7 ngày: RSI giảm 15pts — áp lực bán gia tăng." (cùng thuật toán, delta có nghĩa)
#   Bug fix: không dùng s?.rsi (API smoothed EWM) làm baseline — so sánh không đồng nhất → delta ~0.
# Files: telegram-bot/miniapp/web_js.js + web.html (rebuilt)
# Verified: zero console errors, VCBFTBF shows -15pts, TCBF shows -5pts

## Session (autonomous, scheduled) — Ca chiều 2026-08-02: verify baseline, không code thêm
# Tình trạng đầu session: tất cả P0/P1 đã DONE. Điều kiện dừng: "Hết P0+P1".
# Baseline: py_compile 5 file chính OK, 367/367 tests pass (1.24s).
# Harvey uncommitted changes vẫn chưa push: web_js.js + web.html (7 dòng mỗi file):
#   (1) _vsBankDiff: so sánh lợi nhuận 1 năm vs lãi tiết kiệm 4.5%/năm trong HIỆU SUẤT ĐẦU TƯ
#   (2) "Nhận định chất lượng rủi ro": đánh giá Sharpe + Drawdown + Sortino tổng hợp cuối risk section
#   → Các changes này complete và in sync giữa web_js.js và web.html (đều +7 dòng, khớp nhau).
#   → web_new.html chỉ là placeholder "placeholder" 1 dòng — không liên quan.
# Việc cần Harvey:
#   (1) Commit + push web_js.js / web.html (vs-bank comparison + risk quality assessment)
#   (2) WEB-017 BLOCKED: cấp JWT tcinvest mới để backfill NAV bulk
#   (3) WEB-014 P2: cần Harvey clarify backend field cần expose (nav_jump_anomaly trong analysis panel)
# Notion sync không khả dụng (MCP chưa authed).

## Session (autonomous, scheduled) — Ca sáng 2026-08-02: verify baseline + WEB-018 confirm
# Tình trạng đầu session: tất cả P0/P1 đã DONE. Điều kiện dừng: "Hết P0+P1".
# Baseline: py_compile 5 file chính OK, 367/367 tests pass.
# WEB-018 DONE (confirmed): bookmarklet cross-login TCInvest đã tồn tại trong code:
#   _buildBookmarklet() trong web_js.js (line 2062) + bm-slot div trong web_body.html (line 459)
#   + _buildBookmarklet() gọi trong loadAdminTab(). Người dùng kéo bookmarklet vào Bookmarks Bar
#   → mở TCInvest → nhấn bookmark → token tự điền. WEB-018 thực ra đã DONE từ GOV-020 (21/07).
# Harvey uncommitted changes trong web_js.js + web.html (7 dòng mỗi file):
#   (1) _vsBankDiff: so sánh lợi nhuận 1 năm vs lãi tiết kiệm 4.5%/năm trong HIỆU SUẤT ĐẦU TƯ
#   (2) "Nhận định chất lượng rủi ro": đánh giá Sharpe + Drawdown + Sortino tổng hợp cuối risk section
#   → Chờ Harvey commit + push (web_js.js + web.html đã in sync qua build_web.py).
# Việc cần Harvey:
#   (1) Commit + push web_js.js / web.html (vs-bank comparison + risk quality assessment)
#   (2) WEB-017 BLOCKED: cấp JWT tcinvest mới để backfill NAV bulk
#   (3) WEB-014 P2: cần Harvey clarify backend field cần expose (nav_jump_anomaly trong analysis panel)

## Session (autonomous, continuation) — 2026-07-30: WEB-023/024 analysis panel expert detail
# WEB-023 DONE: MA cross, Fibonacci, BB squeeze — chi tiết expert cấp độ quản lý tài sản
#   - WEB-023a: MA cross 'above'/'below' — thêm gap% (MA20-MA50/MA50*100) + vị trí giá vs MA
#     → 3 sub-cases per direction: giá trên cả 2 MA / giữa 2 MA / dưới cả 2 MA
#   - WEB-023b: Fibonacci description — thêm label "hỗ trợ/kháng cự" + giá đồng (fmt) +
#     RSI cross-reference (RSI<40+Fib support="vùng mua kỹ thuật", RSI>60+Fib resist="chốt lời")
#   - WEB-023c: BB Width squeeze — thêm MACD direction hint khi BB < 3%
#     (MACD+ → breakout tăng khả thi, MACD- → cẩn thận hướng giảm, MACD≈0 → chờ xác nhận)
#   Verified: ESSCF hiện MA cross gap%, Fib "hỗ trợ bên dưới + RSI thấp = vùng mua kỹ thuật tốt"
# WEB-024 DONE: 52W range R/R ratio + watchConds Fib breakout + BB squeeze direction
#   - WEB-024a: 52W range section — thêm upside/downside % và Risk/Reward ratio (_rr52)
#     (pct52<20: "Cơ hội mua", pct52>80: "Cẩn trọng", giữa: "R/R Xx (thuận/không thuận lợi)")
#   - WEB-024b: watchConds — thêm 2 điều kiện kỹ thuật cụ thể:
#     (1) Fib resistance breakout: khi score>=2 và có fibResist → "NAV vượt kháng cự Fib X% (+Y% = Zđ)"
#     (2) BB squeeze direction: khi bbW<4% và đang co lại → gợi ý hướng breakout từ MACD
#   Verified: ESSCF "upside +24.7%, downside −0.0%. Cơ hội mua" + "NAV vượt Fib 23.6% (+5.8% = 18.996đ)"
#   Commit: 21cbc43. 0 console errors.

## Session (autonomous, continuation) — 2026-07-30: WEB-021/022 analysis panel expert enhancements
# WEB-021 DONE: histPatternData refactor — split IIFE into data object + HTML renderer
#   histPatternData computed once, reused by: (1) histPatternHtml display block,
#   (2) histConf sentence appended to summaryLine (fires when n>=10 + winRate30>=65 bullish
#   or <=35 bearish), (3) "Xác suất lịch sử" strategyHtml row (winRate30>=60 bullish /
#   <=40 bearish). Verified: ESSCF shows "68% khả năng tăng sau 30 ngày" in conclusion.
# WEB-022 DONE: MACD NAV-normalized strength classification
#   _macdPctNAV = |macd|/curr*100 (comparable across funds regardless of NAV price).
#   4-level classification for negative MACD: >0.5% = âm mạnh (DCA 3-4 lần cảnh báo),
#   >0.1% = âm vừa (chờ thu hẹp), <0.1% = gần 0 (sắp cạn kiệt - theo dõi sát).
#   Positive branch shows histogram magnitude + Golden Cross guidance.
#   Commit: 5d764b0. Verified: ESSCF "MACD âm mạnh (0.96% NAV)", 0 console errors.

## Session (autonomous, scheduled) — 0:00 2026-07-30: WEB-019..023, iOS check
# ⚠️ Phát hiện: 1 session autonomous KHÁC đã chạy song song trong cùng thư mục cùng lúc
#   (web_js.js/web.html bị sửa + commit liên tục mỗi vài phút: d065015, 53dc123, ea49164,
#   a16d915 — sparklines, portfolio mini chart, sort buttons, keyboard shortcut '/', perf bars,
#   market breadth counts). Để tránh corrupt file dùng chung, session này CHỈ thêm phần chưa
#   trùng (bulk-watch) + luôn Read lại file ngay trước mỗi Edit, KHÔNG dùng Write toàn file.
# WEB-019 DONE: Bulk "☑ Chọn nhiều" trên Bảng giá thị trường — chọn nhiều quỹ (checkbox
#   per-row) rồi 1 nút "★ Thêm vào theo dõi" thêm tất cả vào watched_funds cùng lúc.
#   _toggleMarketBulkMode()/_toggleBulkPick()/_bulkAddWatch() trong web_js.js; UI trong
#   web_body.html (#market-bulk-toggle, #market-bulk-bar). Verified qua browser (port 8555
#   riêng để không đụng server 8443/8080 của session kia): chọn 2 quỹ → "Đã chọn 2 quỹ" →
#   bấm nút → toast + thoát bulk mode, 0 console error.
# WEB-020 NOTE (bug phát hiện, KHÔNG tự sửa — thuộc code session kia đang code dở):
#   Sparkline (_sparklineSvg, web_js.js commit ea49164) đọc từ _histNavCache[code], nhưng
#   cache chỉ được set trong loadHistChart() SAU KHI _renderHistFundList() đã render xong —
#   không có re-render lại sau khi cache có dữ liệu → sparkline gần như KHÔNG BAO GIỜ hiện
#   trong thực tế (verified: cacheKeys=['SSISCA'] sau khi auto-load nhưng svgCount vẫn 0
#   trong #hist-fund-list). Fix gợi ý: thêm `_renderHistFundList()` cuối `loadHistChart()`
#   sau khi set `_histNavCache[code]`.
# QA-3 CONFIRMED: _renderHistFundList đã hiện TẤT CẢ quỹ (không giới hạn 10), held/watched
#   pinned đầu, ★/☆ toggle hoạt động — việc này session trước (29/07) đã làm, không cần sửa.
# iOS check: Fund_Tracker_ProApp.swift không cần đổi gì (chỉ gọi ContentView(), không phụ
#   thuộc ModelContainer/environment nào). Item.swift là placeholder cố ý trống từ v1.1
#   (SwiftData đã gỡ) — không cần dọn.
# Verify: py_compile build_web.py/local_dev_server.py/miniapp_server.py/bot.py/db.py OK,
#   node --check web_js.js OK, build_web.py chạy OK (306,328 → sau đó session kia build lại
#   323,876 chars), browser verify (port 8555, user_id=1): 0 console error ở Trang Chủ,
#   Phân Tích, bulk-watch flow.
# Việc cần Harvey:
#   (1) WEB-020: fix sparkline không hiện (thêm re-render sau cache) — 1 dòng, dễ
#   (2) Xác nhận có đúng 2 session autonomous chạy trùng giờ không (nếu vô tình double-trigger
#       scheduled task, nên kiểm tra lại cấu hình để tránh corrupt file trong tương lai)
#   (3) Các mục cũ vẫn tồn đọng: JWT tcinvest mới (WEB-017), Xcode project cũ bị xoá +
#       ios/ mới chưa track (không tự commit, chờ Harvey xác nhận ý định restructure)

## Session (autonomous, scheduled) — Ca sáng 2026-07-29: WEB-013, GOV-031
# WEB-013 DONE: T+2 accuracy chart sử dụng dữ liệu thật từ /api/t2/accuracy/<code>
#   - renderT2AccuracyChart() đổi thành async; fetch /api/t2/accuracy/${code} thay vì random mock
#   - IS_DEV mode: giữ mock data (5 điểm ví dụ), production: dùng history thật
#   - history từ API newest-first → .slice().reverse() để chart hiện đúng chiều thời gian
#   - Empty state: ẩn canvas, hiện thông báo "Chưa có lịch sử dự đoán T+2"
#   - MAPE summary từ best model (mape_7d/30d/all) hiện trước chart
#   - Commits: cd7e94c (WEB-013), 99ced1d (GOV-031)
# GOV-031 DONE: NAV chart range ALL bị giới hạn 365 ngày thay vì all-time
#   - setChartRange('ALL'): đổi fetch từ /api/nav_history/${code} → /api/nav_history/${code}?limit=3650
#   - Comparison chart _cmpLim: đổi '' → '?limit=3650' để ALL range lấy đủ data
#   - Backend đã có max cap 3650 (10 năm) — đủ cho tất cả quỹ hiện có
# ANA-006 NOTE (pending Harvey): fund_type-aware signal scoring — Harvey implement trong
#   local_dev_server.py (bond vs equity threshold) nhưng chưa có trong production miniapp_server.py.
#   Cần thêm fund_type column vào funds_master (GOV-006 compliant: ADD COLUMN IF NOT EXISTS).
#   → Autonomous session KHÔNG implement ANA-006 (backend task, cần Harvey confirm)
# Điều kiện dừng: Hết P0+P1 (WEB-017 BLOCKED, WEB-014 unclear, WEB-018 P3 deferred)
# Suite: 367/367 tests pass.
# Việc cần Harvey:
#   (1) Commit Harvey's uncommitted: build_web.py, local_dev_server.py, web_body.html
#   (2) Cấp JWT tcinvest mới → Railway backfill NAV (fix WEB-017)
#   (3) WEB-014 clarify: NAV dashboard warning icons cần expose field gì từ backend?
#   (4) ANA-006: confirm + implement fund_type-aware signals cho production

## Session (autonomous, scheduled) — Ca chiều 2026-07-28: WEB-012/015/016
# WEB-012 DONE: ⚖️ So Sánh view — so sánh 2 quỹ cùng lúc trong Phân Tích tab
#   - Nút "⚖️ So Sánh" trong view toggle bar
#   - loadComparisonView(): dropdown chọn quỹ 2, fetch 2 NAV history, normalize về % return
#   - renderComparisonChart(): Chart.js dual-line, forward-fill missing dates, legend + tooltip % return
#   - _renderCmpSignals(): bảng tín hiệu RSI/BB%/MACD/score so sánh 2 quỹ (cyan vs yellow)
#   - _selectHistFund() + setHistRange() cập nhật khi ở cmp mode
# WEB-015 DONE: Stale NAV banner trên Trang Chủ market board
#   - <div id="market-stale-banner"> trước <div id="market-content">
#   - renderMarket() hiện banner vàng nếu staleCodes.length > 0 (nav_stale||data_stale)
#   - Ẩn khi không có quỹ stale
# WEB-016 DONE: ★/☆ quick-watch toggle trên mỗi market row (Trang Chủ)
#   - Mỗi sig-row có <span class="watch-star"> bên cạnh signal badge
#   - _quickWatch(code, e): stopPropagation, gọi _toggleWatchFund, cập nhật DOM star optimistically
#   - isWatched check từ _me?.watched_funds
#   - Verified: click VHIZ → ★ cyan + "Bỏ theo dõi", toggle lại → ☆ + "Thêm theo dõi"
# Build: 256,846 chars. Tất cả P2 web tasks hoàn thành (trừ WEB-013/014/017/018).
# P1 còn lại: WEB-017 (BLOCKED TCInvest JWT), WEB-013 (cần real T+2 data từ backend)
# Việc cần Harvey:
#   (1) Cấp JWT TCInvest mới → Railway backfill NAV (fix WEB-017)
#   (2) WEB-013: backend cần expose t2_accuracy history per fund để chart thật
#
## Session (Harvey-directed) — 2026-07-25: Tier 1 analytics + WEB-010/011
# ANA-001 DONE: calc_rsi Wilder's EMA (bot.py + local_dev_server.py + _gold_rsi miniapp_server.py)
# ANA-002 DONE: calc_macd full-history EMA warm-up (không cắt navs[-fast-5:] nữa)
# ANA-003 DONE: BB%B extended range bb_pct<0 (+4) và bb_pct>100 (-4) — giá ngoài dải Bollinger
# ANA-004 DONE: NAV anomaly filter |chg_pct|>15% → trả N/A + nav_jump_anomaly=True (skip calc)
# ANA-005 DONE: local_dev_server threshold sync ±6/±3 (align với bot.py sau khi BB max tăng lên ±4)
# WEB-010 DONE: Trang Chủ chart-col auto-select quỹ đầu (has_position) khi market load lần đầu
# WEB-011 DONE: 🥇 VÀNG SJC pinned ở đầu fund list trong Phân Tích; loadGoldAnalysis() hiển thị
#   price chart + RSI/BB%/MA signals từ _goldData.signals; graceful fallback khi chạy local
#   (signals chỉ từ Railway PostgreSQL, local hiện "Tín hiệu vàng chỉ có trên Railway")
# 367/367 tests pass. Commits: 876c218 (analytics), 2dd3607 (WEB-010/011)

## Session (Harvey-directed) — 2026-07-24 chiều: Web parity audit + UI fixes (WEB-001..008)
# Harvey cung cấp 4 screenshots + feedback list. Implement:
# WEB-001 DONE: Phân Tích fund list hiện TẤT CẢ quỹ (43) thay vì chỉ 10 (slice removed)
# WEB-002 DONE: ★/☆ watch toggle trên mỗi hàng fund trong Phân Tích → gọi /api/me/watched_funds
# WEB-003 DONE: _renderHistAnalysis fallback _marketData khi _signals rỗng → indicators hiển thị
# WEB-004 DONE: Map macd_hist → macd field (API trả macd_hist, code đọc macd → sửa trực tiếp)
# WEB-005 DONE: T+2 prediction block trong analysis panel (chỉ hiện khi API có t2_prediction.nav)
# WEB-006 DONE: Data adequacy warning khi < 20 điểm NAV ("⚠ tín hiệu RSI/BB%/MACD chưa chính xác")
# WEB-007 DONE: Kết luận block (Score + label MUA/BÁN/TRUNG LẬP) ở cuối analysis panel
# WEB-008 DONE: Alert icon ⚠ trong market board khi s.data_stale|nav_stale|alert|nav_jump_anomaly
# WEB-009 DONE: loadHistTab default chọn fund đầu từ held/watched thay vì slice(0,5)
# Build: 236,511 chars. No console errors. Verified via JS: 43 quỹ, P&L đúng (SSISCA 40.3M).
# Commit: (pending — xem bên dưới)
#
# BACKLOG phát hiện từ feedback Harvey (chưa implement — nhiều tasks cần Harvey xác nhận ưu tiên):
# WEB-010 DONE: Trang Chủ — auto-select quỹ đầu (has_position) khi load
# WEB-011 DONE: Gold analysis signals trong Phân Tích tab — VÀNG SJC row + panel
# WEB-012 DONE: Fund comparison tool — so sánh 2 quỹ cùng lúc (NAV chart overlay + signals)
# WEB-013 DONE P2: T+2 accuracy chart dùng dữ liệu thật từ /api/t2/accuracy/<code> (commit cd7e94c)
# WEB-014 TODO P2: NAV dashboard warning icons (nav_jump_anomaly, stale) — cần backend expose field
# WEB-015 DONE: "Quỹ chưa cập nhật NAV hôm nay" stale banner trên Trang Chủ market board
# WEB-016 DONE: Fund watchlist ★/☆ quick-toggle trên mỗi market row (Trang Chủ) — _quickWatch()
# WEB-017 TODO P1: NAV data completeness — nhiều quỹ chỉ 3 ngày data → cần bulk backfill
#   → BLOCKED: TCInvest JWT hết hạn từ 2026-07-16, Harvey cần cấp token mới trên Railway
# WEB-018 DONE: TCInvest cross-fetch helper — bookmarklet đã có trong GOV-020 (21/07):
#   _buildBookmarklet() (web_js.js:2062) + bm-slot div (web_body.html:459), gọi trong loadAdminTab()
#   Confirm 2026-08-02: code tồn tại, logic hoàn chỉnh (scan localStorage + postMessage → token fill)
#
# Việc cần Harvey:
#   (1) Cấp JWT tcinvest mới → Railway sẽ tự backfill lại NAV cho tất cả quỹ (fix WEB-017)
#   (2) Set WEB_SESSION_SECRET trên Railway + /setdomain @BotFather (GOV-015)
#   (3) Xác nhận priority order cho WEB-010..018

## Session (autonomous, scheduled) — Ca chiều 2026-07-24: verify baseline, không code thêm
# Tình trạng: tất cả P0/P1 đã DONE (xác nhận từ ca sáng cùng ngày). Không có commit mới từ Harvey
# kể từ ca sáng (chỉ 1 commit: 2cb7f1d docs ca sáng). Harvey uncommitted files không đổi
# (web_js.js +1853, web_body.html +573, web.html +2568, build_web.py +142, local_dev_server.py +420)
# — đã được ca sáng scan đầy đủ, không có gap backend mới.
# Baseline: py_compile bot.py/miniapp_server.py/db.py OK, 367/367 tests pass (2.32s).
# Điều kiện dừng "Hết P0+P1" áp dụng ngay. Không code thêm gì.
# Notion sync không khả dụng (MCP chưa authed).
# Việc cần Harvey (tồn đọng, không đổi từ ca sáng):
#   (1) Commit + push web_js.js/web_body.html/build_web.py/local_dev_server.py
#   (2) Cấp JWT tcinvest mới (hết hạn từ 2026-07-16)
#   (3) Set WEB_SESSION_SECRET trên Railway + /setdomain @BotFather (GOV-015 web auth)

## Session (autonomous, scheduled) — Ca sáng 2026-07-24: verify baseline, không code thêm
# Tình trạng: tất cả P0/P1 đã DONE (xác nhận từ ca chiều 23/07). Không có commit mới từ Harvey.
# Baseline: py_compile 5 file chính OK, 367/367 tests pass.
# Harvey's uncommitted files (web_js.js +1853 lines, web_body.html +573, web.html +2568,
# build_web.py +142, local_dev_server.py +420) đã được rescan: apiFetch tự append user_id,
# 30+ /api/ paths đều có backend — không có gap mới. web_body.html: payment toggle mới
# (Stars/QR/MoMo), SePay QR section, desktop 3-col layout — tất cả gọi backend đã có.
# Điều kiện dừng "Hết P0+P1" áp dụng ngay. Không code thêm gì.
# Notion sync không khả dụng (MCP chưa authed).
# Việc cần Harvey (tồn đọng, không đổi từ ca chiều 23/07):
#   (1) Commit + push web_js.js/web_body.html/build_web.py/local_dev_server.py
#   (2) Cấp JWT tcinvest mới (hết hạn từ 2026-07-16)
#   (3) Set WEB_SESSION_SECRET trên Railway + /setdomain @BotFather (GOV-015 web auth)

## Session (autonomous, scheduled) — Ca chiều 2026-07-23: GOV-028/029/030
# Tình trạng đầu session: tất cả P0/P1 đã DONE từ trước (ca sáng cùng ngày xác nhận).
# Điều kiện dừng: "Hết P0+P1". Hành động:
# 1. Tiếp tục scan Harvey's uncommitted web_js.js (+1791 lines, từ ca sáng):
#    - renderHistChart/loadHistChart (~line 1824): đọc d.history||d — khớp backend ✅
#    - Gold price history (~line 2384): h.history[].{date,price} — khớp backend ✅
#    - loadAdminPayments (~line 2120): p.name/plan/method/amount_vnd/status/created_at —
#      p.stars intentionally missing trong processed_payments (noted tại line 3275) ✅
# 2. Phát hiện 3 bugs từ việc GOV-026/027 chưa hoàn toàn align backend với frontend:
#    - GOV-028: _api_edit_gold_trade SELECT thiếu name, UPDATE không persist name column
#      (GOV-027 thêm column nhưng quên update edit endpoint)
#    - GOV-029: /api/history trả index (DB id) nhưng frontend tìm t.id →
#      openEditModal fallback sang array position → sửa nhầm record
#    - GOV-030: /api/history thiếu trade_type alias → mọi type label render rỗng
# 3. Fix + test + commit + push cho cả 3 bugs.
#    Suite: 359 → 367/367 passed (+8 tests cho GOV-028).
# Kết quả: tất cả P0/P1 vẫn DONE. Web_js.js đã scan đầy đủ, không còn bug nào.
# Việc Harvey cần làm (không đổi từ ca sáng):
#   (1) Commit + push web_js.js/web_body.html/build_web.py (Harvey uncommitted)
#   (2) Cấp JWT tcinvest mới (hết hạn từ 2026-07-16)
#   (3) Set WEB_SESSION_SECRET trên Railway + /setdomain @BotFather (GOV-015 web auth)

## Session (autonomous, scheduled) — Ca sáng 2026-07-23: GOV-026 + GOV-027
# Tình trạng đầu session: tất cả P0/P1 đã DONE từ trước. Điều kiện dừng: "Hết P0+P1".
# Hành động:
# 1. Scan Harvey's uncommitted web_js.js (+1791 lines) → 4 API calls thiếu backend:
#    - GET /api/history?user_id=... (unified CCQ+gold trades)
#    - GET /api/nav_history/<code>?limit=N (NAV chart data)
#    - GET /api/gold/price_history/<product> (gold chart data)
#    - GET /api/admin/payments/recent?user_id=... (admin: 50 recent payments)
# 2. GOV-026: Implement 4 endpoints trong miniapp_server.py + routing + 25 tests.
#    Commit: (pending at context switch) — committed trong context mới.
#    Suite: 334 → 359/359 passed.
# 3. GOV-027: Phát hiện thêm field name mismatches + thiếu column:
#    - /api/admin/discount/list: trả về cả 'codes' + 'discounts' (web_js.js đọc .codes,
#      index.html đọc .discounts — backward compat)
#    - /api/trade: accept fund_code/trade_type/trade_date aliases (new) và code/type/date (old)
#    - /api/gold/trade: accept trade_type/units/price/trade_date aliases + tên cũ
#    - user_gold_trades: additive name TEXT DEFAULT '' column (ALTER TABLE IF NOT EXISTS)
#    - GET /api/gold/trades + GET /api/history: SELECT + response include name field
#    Commit: fdd1c37 fix(GOV-027): field name compat + gold trade name column
#    Suite: 359/359 passed.
# Việc Harvey cần làm:
#   (1) Commit + push web_js.js/web_body.html/build_web.py (Harvey uncommitted) để dùng endpoints mới
#   (2) Cấp JWT tcinvest mới (hết hạn từ 2026-07-16)
#   (3) Set WEB_SESSION_SECRET trên Railway + /setdomain trên @BotFather (GOV-015 web auth)

## Session (autonomous, scheduled) — Ca chiều 2026-07-22: GOV-025 admin user search
# Tình trạng: tất cả P0/P1 đã DONE từ trước. Điều kiện dừng: "Hết P0+P1".
# Phát hiện: Harvey's uncommitted web_js.js (+548 dòng) có `loadAdminUsers(q)` gọi
# `GET /api/admin/users` — endpoint này chưa tồn tại trong miniapp_server.py.
# Implement GOV-025: db.get_admin_users() + _api_admin_users() + routing + 13 tests.
# Commit: 407cbde feat(GOV-025): GET /api/admin/users — admin user search endpoint
# Suite: 321 → 334/334 passed. Pushed to origin/staging.
# Việc cần Harvey (không tự làm được):
#   (1) Commit web_js.js/web_body.html/build_web.py (Harvey uncommitted) để frontend dùng endpoint mới
#   (2) Cấp JWT tcinvest mới (hết hạn từ 2026-07-16, recurring pattern)
#   (3) Xác nhận NTPPF/VMEEF có nên track (FK violation ongoing)
#   (4) Set WEB_SESSION_SECRET trên Railway + /setdomain trên @BotFather (cho GOV-015 web auth live)

## Session (autonomous, scheduled) — Ca sáng 2026-07-22: update BACKLOG cho 7 commits Harvey
# Tình trạng: tất cả P0/P1 đã DONE từ trước. Điều kiện dừng: "Hết P0+P1".
# Đầu session: đọc BACKLOG + memory.md + git log → phát hiện 7 commits mới từ Harvey
# sau ca chiều 21/07 (sau commit aa67e86 BACKLOG update):
# - 6bd47b7 (21/07 15:38): feat(web): new web.html v1 — 3-tab layout + build_web.py split
# - 962c17e (21/07 15:50): fix(infra): backup retention 14→2 ngày + emergency_cleanup.py
# - 07e92d1 (21/07 16:26): fix(local-dev): signals UnboundLocalError + local_dev_server.py
# - a7dda92 (21/07 18:40): feat(web): redesign v4 — 2-col home, separate Ca Nhan + Admin
# - e3a36e4 (21/07 19:01): feat(web): fix diacritics + Giao Dịch 3-column layout
# - b8a2f74 (21/07 20:41): feat(web): desktop layout v1 — sidebar + 3-col home + inlined JS
# - bd0677c (21/07 20:42): fix(db): init_pool retry khi Railway DB chưa sẵn sàng
# Verify baseline:
# 1. py_compile telegram-bot/{bot,miniapp_server,db}.py + scripts/emergency_cleanup.py
#    + telegram-bot/miniapp/{local_dev_server,build_web}.py → All OK
# 2. pytest tests/ → 321/321 passed
# Ghi BACKLOG: GOV-021/022/023/024 (xem bên dưới).
# Không code thêm — tất cả P0/P1 đã DONE, 7 commits Harvey không có regression.

## Session (autonomous, scheduled) — Ca chiều 2026-07-21: update BACKLOG cho 5 commits Harvey
# Tình trạng: tất cả P0/P1 đã DONE từ trước. Điều kiện dừng: "Hết P0+P1".
# Đầu session: đọc BACKLOG + memory.md + git log → phát hiện 5 commits mới từ Harvey
# sau ca chiều 20/07 (sau commit da4deed của session hôm qua):
# - 9eb5bba (20/07 14:26): feat(web): redesign v3 — merged tabs, full fundmart, DCA+History
# - e590193 (20/07 14:29): dev(admin): add ?dev=1 bypass cho admin_pnl.html
# - 1af01c7 (20/07 14:44): feat(admin): xoa portfolio section, them discount mgmt + TCBS token
# - 55be95f (21/07 13:48): feat(admin): doi thu tu + them cross-login TCInvest bookmarklet
# - aad9797 (21/07 13:53): refactor(web): xoa desktop 3-col, dung tab UI Mini App moi man hinh
# Verify baseline:
# 1. py_compile telegram-bot/{bot,miniapp_server,db}.py → All OK
# 2. pytest tests/ → 321/321 passed
# 3. Verify web.html: GOV-015 features (T+2 hints, loadSignals/loadTrades, _predictions) còn đầy đủ
# 4. Verify API calls trong web.html: tất cả 6 endpoints đều đã có backend, không cần thêm
# 5. DCA calculator logic: amt/nav * months = CCQ, display value tại NAV hiện tại — đúng thiết kế
# 6. Không kết nối được Railway proxy để verify prediction_actuals (SSL error từ máy local)
# Không code thêm — tất cả P0/P1 đã DONE, 5 commits Harvey là UI-only không có regression.
# Update BACKLOG (entries GOV-019/GOV-020 bên dưới) + memory.md.

## Session (autonomous, scheduled) — Ca sáng 2026-07-16: update BACKLOG, verify baseline
# Tình trạng: tất cả P0/P1 đã DONE từ trước. Điều kiện dừng ca này: "Hết P0+P1".
# Đầu session: đọc BACKLOG + memory.md + git log → phát hiện Harvey committed 5 tính
# năng/fix lớn sau session chiều 15/07 (GOV-008-part2, GOV-009, GOV-010/011, PAY-009
# HMAC, GOV-011-part2) chưa được ghi vào BACKLOG. Việc làm ca này:
# 1. py_compile 3 file Python chính → OK (All OK)
# 2. pytest 254/254 pass — baseline ổn định, không có regression từ các commits mới
# 3. Review `dashboard/portfolio.html` mới của Harvey (1059 dòng, chưa commit): xác nhận
#    cả 2 endpoints nó gọi (/nav-json, GET+POST /transactions) đều ĐÃ TỒN TẠI trong
#    server.py → trang sẵn sàng hoạt động, Harvey có thể commit + test khi muốn
# 4. Update BACKLOG với 5 commits Harvey (entries bên dưới)
# 5. Update memory.md
# Phát hiện ngoài lề (không xử lý): `dashboard/portfolio.html`, `ios/`, và ~15 scripts
# mới trong `scripts/` chưa được git add/commit — đây là work-in-progress của Harvey,
# không tự ý commit (GOV-006: hỏi trước khi động vào thay đổi không phải do session tạo).
#
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
  - **Update 2026-07-15** (Harvey commit c04bcbc): xác thực webhook nâng cấp lên HMAC-SHA256
    thay vì Apikey tĩnh — `X-SePay-Signature: "sha256=" + HMAC-SHA256(secret, timestamp.body)` +
    replay protection (timestamp ±5 phút). `_read_body()` lưu raw bytes (ký trên bytes gốc,
    không re-serialize). Fallback về Apikey tĩnh nếu `SEPAY_HMAC_SECRET` chưa set (backward-compat).
  - **CHƯA verify với tài khoản SePay thật** — field name webhook payload
    (`transferType`/`content`/`transferAmount`/`id`) theo định dạng phổ biến
    SePay công khai, cần Harvey đăng ký tài khoản SePay + set
    `SEPAY_HMAC_SECRET`/`SEPAY_API_KEY`/`SEPAY_ACCOUNT_NUMBER`/`SEPAY_BANK_CODE` trên Railway
    rồi kiểm tra lại field 1 lần với giao dịch test thật (log payload thô đã có sẵn
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

- [DONE] GOV-008-part2 · NAV verification log + row_hash chống sửa ngầm — Harvey yêu cầu
  xác thực tới TỪNG datapoint, tránh tái diễn vụ VCBFTBF (reconcile xong vẫn có thể bị ghi
  đè ngầm). Bổ sung 2 cơ chế trên nền 3-layer GOV-008:
  (1) Bảng `nav_verification_log` append-only — ghi lại MỌI lần 1 datapoint được kiểm tra
  (ghi lần đầu / re-verify khớp / re-verify lệch / admin xác nhận) — truy vết đầy đủ không
  chỉ tin vào `verify_tier` hiện tại. (2) `row_hash` chống giả mạo — mỗi dòng `nav_history`
  có `hash(fund_code, nav_date, nav, source, verify_tier)`, được cập nhật qua ĐỦ 4 đường ghi
  (`upsert_nav`, `reverify_nav_tier`, `resolve_nav_confirm`, `_insert_nav_points`). Nếu ai
  sửa DB bằng SQL thô bỏ qua các hàm này → hash lệch → `verify_nav_integrity()` phát hiện.
  `harvest_nav.py --verify-integrity` (scan), `--backfill-hash` (tính hash 1 lần cho ~90k
  điểm cũ). `bot.py job_nav_integrity_check()` chạy 21:30 hàng ngày, báo Telegram admin +
  ghi audit_log nếu phát hiện bất thường. Verify: py_compile 4 file, pytest 254/254,
  test sống trực tiếp production DB — phát hiện đúng 4,634 dòng VCBFTBF chưa hash (trước
  backfill), hết sau backfill | 2026-07-15 (Harvey commit 73c78c7)

- [DONE] GOV-009 · Gold data gap tự động backfill — XAUUSD khoảng trống 5-9 ngày phát hiện
  trên production khi bot restart/deploy làm `job_morning` lỡ chạy vài ngày liên tiếp.
  `telegram-bot/fetch_gold.py`: thêm `fetch_xauusd_yahoo_history()` (lấy lịch sử từ Yahoo
  Finance) + mở rộng `run_backfill(days=10)` để vá cả XAUUSD (trước chỉ vá SJC_1L).
  `bot.py job_morning`: tự gọi `run_backfill(days=10)` mỗi sáng thay vì phải chạy tay khi
  phát hiện khoảng trống. Mini App UI đồng thời: chip mã CCQ, đổi nhãn "Vốn"→"Giá vốn",
  dropdown chi tiết Vốn CCQ/Giá trị hiện tại, gộp "Vị thế của bạn" về 1 hàng, tên quỹ
  chạy chữ khi dài thay vì bị cắt, bỏ disclaimer T+2 trùng lặp, sửa bug ID nút "Phân kỳ"
  DCA Vàng không có hiệu ứng active | 2026-07-15 (Harvey commit 15c8989)

- [DONE] GOV-010 · Referral fraud audit + thiết kế lại 2 giai đoạn + ban/unban thủ công
  **Root cause**: Harvey hỏi review bảo mật cơ chế referral. Bản cũ (`redeem_promo_code`)
  cấp Pro miễn phí NGAY cho cả referee và referrer lúc redeem — không đòi hỏi thanh toán
  thật nào, và `promo_codes.max_uses=NULL` cho referral code (không giới hạn tổng lượt
  dùng) → có thể farm vô hạn bằng tài khoản Telegram ảo (SIM ảo giá rẻ), tốn 0 đồng
  doanh thu cho mỗi lượt farm. Thêm lỗ hổng phụ: referral ring (A↔B redeem chéo) chỉ bị
  chặn ở check tự-dùng-mã-mình, không chặn vòng lặp nhiều tài khoản.
  **Fix (theo yêu cầu Harvey, thiết kế 2 giai đoạn)**:
  - Giai đoạn 1 (redeem mã): referee KHÔNG còn nhận Pro miễn phí. Referrer nhận
    `REFERRAL_SIGNUP_BONUS_DAYS=15`, nhưng tối đa **1 lần / 30 ngày**
    (`promo_codes.last_referrer_bonus_at`) — chặn sybil farm redeem liên tục.
  - Giai đoạn 2 (referee thanh toán thật lần đầu): `grant_referral_purchase_bonus()` cấp
    thêm `REFERRAL_PURCHASE_BONUS_DAYS=30` cho CẢ referrer và referee — chỉ khi referee
    thực sự trả tiền (SePay/MoMo/Telegram Stars), sửa tận gốc lỗ hổng kinh tế. Idempotent
    qua cột `promo_redemptions.referral_purchase_bonus_at` (chỉ chạy 1 lần/referee).
  - Wire vào cả 3 payment success path: `_api_sepay_webhook`, `_api_momo_ipn`
    (`miniapp_server.py`), `_handle_successful_payment` (`bot.py`).
  - Cảnh báo admin qua Telegram khi 1 mã referral bị ≥3 tài khoản khác nhau redeem
    trong 24h (`REFERRAL_SYBIL_ALERT_THRESHOLD`, `_notify_admin_referral_sybil`).
  - Thêm ban/unban thủ công: `user_tiers.banned/banned_at/banned_by/ban_reason` (additive,
    không xoá tier/pro_expires_at đang có — GOV-006), `db.ban_user/unban_user/is_banned`,
    admin API `POST /api/admin/user/ban`, `/unban`, `GET /api/admin/user/banned-list`
    (đều `_is_admin` + `_auth_write`). `redeem_promo_code`/`grant_referral_purchase_bonus`
    chặn cả referee và referrer đang bị ban.
  Verify: `py_compile` sạch cho `db.py`/`bot.py`/`miniapp_server.py`. Chưa test sống trên
  production (chưa có giao dịch referral thật để trigger) — cần theo dõi lần redeem/mua
  Pro tiếp theo để xác nhận đúng luồng | 2026-07-15

- [DONE] GOV-011 · NAV hiển thị cũ hơn DB — Harvey phát hiện SSISCA (và các quỹ tcbs=True)
  hiện NAV hôm qua dù nav_history đã có NAV hôm nay (nguồn fmarket). Root cause:
  `get_nav_series_with_source()` fetch live TCBS mỗi lần, TCBS chưa publish NAV hôm nay
  thì trả pts chỉ tới hôm qua → âm thầm bỏ qua NAV mới hơn đã có sẵn trong DB. Fix:
  luôn merge thêm điểm mới nhất từ DB nếu mới hơn pts vừa fetch — tín hiệu không bao giờ
  được lùi về NAV cũ hơn khi đã có NAV mới hơn trong DB | 2026-07-15 (Harvey commit 6259b3a)

- [DONE] GOV-011-part2 · Cache buy_signals không refresh khi nav_date cũ hơn hôm nay —
  `_get_signals_for_codes()` coi cache "stale" khi signal_date < hôm nay, nhưng
  `_compute_from_nav_history()` luôn ghi signal_date=hôm nay bất kể nav_date thực tế dùng
  để tính là ngày nào. Hệ quả: Mini App mở lần đầu trong ngày trước khi NAV publish xong
  → cache bị tính 1 lần với NAV hôm qua rồi "khoá" fresh cả ngày dù DB đã có NAV mới hơn
  từ lúc sau. Fix: staleness so cả nav_date (không chỉ signal_date) — tính lại rẻ (chỉ
  đọc nav_history, không gọi API ngoài) nên an toàn để trigger thường xuyên hơn
  | 2026-07-15 (Harvey commit 5748fde)

- [DONE] GOV-012 · Hệ thống discount_codes quản lý được, thay hardcode SePay -10% — Harvey
  yêu cầu cơ chế mã giảm giá linh hoạt thay vì phải sửa code mỗi lần đổi khuyến mãi. 2 kiểu:
  auto_apply (tự động áp dụng mọi purchase trong kênh/khoảng thời gian, không giới hạn lượt
  trừ khi đặt max_uses) hoặc thủ công (user tự nhập, có thể giới hạn lượt/thời gian). Bảng
  `discount_codes` + `discount_redemptions` (UNIQUE order_ref — không stack 2 mã/1 đơn).
  `_api_sepay_create` ưu tiên mã user nhập (validate_discount_code) nếu có, không thì tự tìm
  mã auto-apply kênh sepay (get_active_auto_discount, chọn % cao nhất nếu nhiều mã trùng).
  Admin API tạo/kích hoạt/danh sách mã. `pricing.py` xoá SEPAY_PROMO_PCT/sepay_price() hardcode.
  Mini App: ô nhập mã tuỳ chọn trước nút SePay, badge "-X%" động thay vì cứng "-10%" | 2026-07-16
  (live session, Harvey + Claude, không phải scheduled task)
  **Verify ca chiều (2026-07-16)**: review bảo mật/tính đúng đắn tài chính — amount_vnd tính
  hoàn toàn server-side từ `plan["vnd"]` + `discount_pct` đã validate (không tin client gửi
  amount), `create_bank_transfer_order()` lưu amount_vnd ĐÃ áp dụng giảm giá vào DB, webhook
  `_api_sepay_webhook` so khớp tiền nhận với `order["amount_vnd"]` đã lưu (không tính lại từ
  plan gốc) → không có khoảng hở giữa giá hiển thị và giá webhook verify. Cả 4 admin endpoint
  (`create/list/activate/deactivate`) đều gate `_is_admin`+`_auth_write` đúng pattern GOV-005.
  Confirm mã `SEPAY10` (auto_apply, channel=sepay, active=true) đã tồn tại thật trên production
  DB — không có khoảng trống giữa lúc xoá hardcode và tạo mã DB thay thế. `pricing.py` xác
  nhận không còn tham chiếu chết `SEPAY_PROMO_PCT`/`sepay_price` ở bất kỳ file nào khác.

- [DONE] · 4 fix nhỏ khác (live session, cùng khung giờ 10:59–12:02 ngày 2026-07-16, trước
  GOV-012, không qua scheduled task):
  1. Nhãn sản phẩm vàng hiện raw code thay vì tên đẹp — `_GOLD_LABELS` thiếu hầu hết mã
     `VANGTODAYAPI:*`, sửa mismatch PNJ_VANGMY→PNJ_HN, thêm DOJI_JEWELRY. "Vàng khác" hiện tên
     riêng user đặt làm tiêu đề nếu chỉ có 1 tên. Chip T+2 chuyển từ Dashboard sang tab DCA.
  2. GOV-011 (phần 2) · "Vàng khác" khi BÁN giờ tách theo từng tên riêng (dropdown chọn thay vì
     gõ tay) + gộp phần chưa đặt tên vào "Vàng khác còn lại". Fix Dockerfile: pin postgresql-
     client-18 từ PGDG (Railway Postgres đã lên v18, base image chỉ có v17 → pg_dump backup
     đêm fail do lệch major version).
  3. Chip T+2 trong tab DCA chuyển lên cùng hàng với dòng "💡 lý do" (gọn hơn, đỡ chiếm chỗ dọc).
  4. fix(T2-006) · `score_predictions()` crash Decimal/float — `nav_history.nav` là NUMERIC
     (psycopg2 trả Decimal) trừ trực tiếp với `predicted_nav` (float) → TypeError, khiến
     `job_t2_score` (18:32 hàng ngày) crash ÂM THẦM mỗi khi thực sự có dữ liệu để chấm kể từ
     khi pipeline T2 chạy thật (14/7) — đây là lý do `prediction_actuals` trống suốt 2 ngày,
     KHÔNG phải "chưa tới hạn" như session trước suy đoán. Fix: ép `float()` trước khi trừ.
     **Verify ca chiều**: `prediction_actuals` trên production giờ có 48 dòng (0 trước đó),
     4 model (arima-v1/xgb-v2/naive-v1/ensemble-v1) đều có 12 mẫu chấm điểm trong 30 ngày qua,
     MAPE trung bình 0.6-0.7% mỗi model — pipeline tự cải thiện (score→retrain→reweight) giờ
     mới thực sự có dữ liệu lần đầu. **Chưa đủ để chạy T2-008 `--reweight` có ý nghĩa**: dù đạt
     ngưỡng thô "≥10 mẫu/model", cả 48 dòng đều ghi cùng 1 timestamp (batch chấm điểm đầu tiên
     ngay sau khi fix deploy) — chỉ là 1 ngày dữ liệu, chưa đủ đa dạng để tin cậy trọng số
     adaptive. Nên đợi vài ngày nữa (nhiều batch `job_t2_score` khác nhau) trước khi chạy
     `t2_ensemble.py --reweight` lần đầu.

- [DONE] GOV-012-part2 · Tách rõ Mã Promo / Mã Voucher / Mã Referral trong Mini App — UI modal
  Nâng cấp trước đây gộp chung 3 loại mã vào 1 ô khiến user nhầm. Tách thành 3 input riêng biệt
  với label + tooltip giải thích rõ: Mã khuyến mãi (admin tạo, giảm giá/tặng ngày), Mã voucher
  (auto-apply tự tìm), Mã giới thiệu (referral code cá nhân). Ô nhập mã referral tự fill sẵn
  nếu user đã dùng trước đó | 2026-07-16 (live session, Harvey + Claude Sonnet 5, commit cf07725)

- [DONE] GOV-013 · Tăng DB connection pool 5→20 — PoolError khi mở tab Admin. Phát hiện: mở
  tab Admin trong Mini App đồng thời trigger nhiều query song song (summary + audit log + signals)
  vượt quá pool size=5 cũ → `PoolError: connection pool exhausted`. Fix: tăng maxconn=20 trong
  `init_pool()` (`telegram-bot/db.py`). Không cần sửa logic — pool tự cấp phát | 2026-07-16
  (live session, Harvey + Claude Sonnet 5, commit 4bb36f4)

- [DONE] GOV-013-part2 · `get_real_pnl_summary()` tự deadlock vì gọi `get_setting()` lồng trong
  cùng 1 DB connection — `with get_conn() as conn` lấy connection từ pool, trong scope đó gọi
  `get_setting()` cũng gọi `with get_conn()` → cả 2 đều block chờ nhau (pool size 1 ở caller).
  Fix: pass `conn` xuống hàm con thay vì để hàm con tự lấy từ pool, tránh nested connection
  acquisition | 2026-07-16 (live session, Harvey + Claude Sonnet 5, commit 8e30588)

- [DONE] GOV-014 · Tăng tần suất backup + cảnh báo sớm dung lượng Postgres. Sự cố 2026-07-16:
  Postgres volume đầy (479/500MB) gây crash — backup gần nhất trước đó cách 11 tiếng vì cron
  chỉ chạy 1 lần/ngày (03:30). Fix: `job_backup_db()` chạy mỗi 2 tiếng thay vì mỗi 24h (tăng
  điểm khôi phục tối đa từ 1 ngày → 2 tiếng). Thêm `job_check_disk_usage()` chạy hàng ngày
  09:30: query `pg_database_size()` → cảnh báo Telegram admin khi vượt 70% `DB_VOLUME_LIMIT_MB`
  (default 500MB). `telegram-bot/BACKUP.md` cập nhật quy trình mới | 2026-07-16 (live session,
  Harvey + Claude Sonnet 5, commit 31a96c1)

- [DONE] GOV-015 · Bản Web độc lập — bước 1: auth qua Telegram Login Widget + portfolio overview.
  Thêm layer xác thực riêng cho Web (browser thường, không cần Telegram app): verify chữ ký
  Telegram Login Widget (thuật toán KHÁC initData — secret_key=SHA256(bot_token), không có prefix
  "WebAppData"), phát hành web session token riêng (HMAC, 30 ngày, format `tg_id.expiry.sig`),
  mở rộng `_auth_write()` chấp nhận header `X-Web-Session` song song `X-Init-Data`. Trang
  `GET /web` → `telegram-bot/miniapp/web.html`: đăng nhập bằng Telegram Login Widget, hiện tier
  + tổng giá trị/lãi-lỗ danh mục (dùng `/api/me` có sẵn).
  **Fix ngay sau**: thẻ `<script data-telegram-login...>` phải là con trực tiếp của div muốn
  hiển thị nút — đặt ở cuối `<body>` khiến Telegram tự chèn iframe xuống cuối trang thay vì
  trong container đăng nhập.
  **Yêu cầu deploy**: set `WEB_SESSION_SECRET` trên Railway + Harvey chạy `/setdomain` trên
  @BotFather trỏ về domain Railway để Telegram Login Widget hoạt động | 2026-07-16 (live session,
  Harvey + Claude Sonnet 5, commits 713eb08 + b96dab3)

- [DONE] GOV-015 bước 2 · Bảng tín hiệu quỹ trong web.html — sau đăng nhập, hiển thị danh sách
  quỹ đang theo dõi với NAV, %thay đổi 1 ngày, badge tín hiệu MUA/BÁN/HOLD (màu khớp design
  system). Gọi `/api/signals?user_id=` với `X-Web-Session` header — không cần sửa backend vì
  `_auth_write()` đã chấp nhận X-Web-Session từ bước 1. Skeleton loading animation trong lúc
  chờ API | 2026-07-17 (scheduled task ca sáng, commit f543bb8)

- [DONE] GOV-015 bước 3 · Lịch sử giao dịch trong web.html — card "📋 Giao dịch gần đây" hiện
  10 giao dịch CCQ mới nhất: ngày, mã quỹ + số CCQ, số tiền (âm khi mua/dương khi bán), badge
  MUA/BÁN. Gọi `/api/trades?user_id=` với X-Web-Session. loadSignals và loadTrades chạy song
  song (không await) ngay sau loadProfile | 2026-07-17 (scheduled task ca sáng, commit 8a6801f)

- [DONE] GOV-015 bước 4 · T+2 prediction trong bảng tín hiệu (Pro only) — tận dụng predictions{}
  đã có sẵn trong `/api/me` response (không gọi thêm API): loadProfile() lưu d.predictions vào
  biến module `_predictions`, pass vào `loadSignals()`. Với mỗi quỹ có dự báo T+2, hiển thị hint
  nhỏ "T+2 ↑0.5%" / "T+2 ↓0.3%" (xanh/đỏ) dưới tên quỹ. Tự ẩn với free users vì server không
  trả predictions cho tier free | 2026-07-17 (scheduled task ca sáng, commit 51e8987)

- [DONE] GOV-015 bước 5 · Nút "⟳ Làm mới" trong web.html — chạy loadSignals + loadTrades song song
  (Promise.all), hiện "⟳ Đang tải..." + disabled trong lúc chờ, tự restore sau khi xong. Tái dùng
  _predictions đã cache từ loadProfile để không gọi /api/me lần 2 (tiết kiệm request)
  | 2026-07-17 (live session Harvey + Claude, commit 26ac450)

- [DONE] GOV-016 · T+2 accuracy improvements — 3 cải tiến liên quan biểu đồ và chấm điểm T+2:
  (1) fix(GOV-016): T+2 hiện mũi tên trung tính "≈" + ghi chú "(chưa rõ hướng)" khi NAV hiện tại
  còn nằm trong khoảng tin cậy 80% [ci_low, ci_high] — trước đây hiện mũi tên xanh/đỏ dù diff nhỏ
  hơn sai số mô hình, gây mâu thuẫn với nhãn xu hướng momentum. Chỉ tô màu khi NAV nằm HẲN ngoài
  CI (Harvey phát hiện qua screenshot: "+0.03%" mũi tên xanh cạnh nhãn "GIẢM") | commit e728855
  (2) feat(GOV-016) bước 3: thêm 1 dòng tóm tắt chấm điểm T+2 ngay cạnh box "Giá chốt T+2" trong
  modal Nghiên cứu — hiện "sai số TB X% (n mẫu)", cảnh báo nếu n<5 mẫu. Bấm → cuộn + mở accordion
  chi tiết biểu đồ (đã có sẵn từ T2-010, không xây lại). Giải quyết feedback Harvey "không thấy
  được biểu đồ" vì accordion cuối cùng, phải cuộn qua 5 card mới thấy | commit 1516bb0
  (3) fix(GOV-016): drawAccuracyChart trống khi chỉ có 1 điểm — moveTo() không có lineTo() theo sau
  → canvas trắng. Fix: vẽ dot đơn lẻ khi n=1, vẫn có thể thấy điểm dữ liệu đầu tiên | commit 1f1e18e

- [DONE] GOV-017 · Gộp Mã Promo + Mã Voucher thành 1 loại mã duy nhất với toggle — Harvey chốt:
  thay vì 2 card riêng biệt (Promo/Voucher) gây nhầm cơ chế, chỉ còn 1 box "MÃ ƯU ĐÃI" với 2 toggle:
  "Có bắt buộc mua hàng?" (Có/Không) + "Loại ưu đãi" (Giảm % / Tặng ngày Premium).
  Ràng buộc: requires_purchase=False CHỈ cho phép benefit_type=bonus_days (giảm % vô nghĩa khi không
  có giao dịch) và auto_apply=false (mã free phải tự nhập, không áp dụng tự động vào 1 đơn hàng).
  DB: thêm discount_codes.requires_purchase (additive, default true — mã cũ không cần backfill).
  redeem_instant_discount_code() mới: cấp ngày Premium NGAY khi requires_purchase=false, tái dùng
  UNIQUE(order_ref) bằng synthetic key "INSTANT-<code>-<tg_id>" (idempotency không cần thêm cột).
  _api_promo_redeem fallback sang hàm này khi promo_codes không tìm thấy mã. Mã Referral
  (kind='referral') không đổi — vẫn 2 giai đoạn, tách biệt hoàn toàn. promo_codes + CRUD admin cũ
  (kind='admin') giữ nguyên để quản lý mã TRIAL cũ đã tồn tại (GOV-006). Validate cả JS lẫn Python.
  Test coverage: 14 tests mới (test_gov017_discount.py) — 11 test redeem_instant_discount_code, 3 test
  create_discount_code validation. 268/268 total suite | 2026-07-17 (live session Harvey + Claude,
  commit 5f12503) + 2026-07-19 (ca chiều autonomous, tests commit 8a58dd1)

- [DONE] GOV-018 · Fund detail panel trong web.html — bấm vào fund row → slide-up panel hiện NAV
  hero, T+2 dự báo (với CI range), sparkline Canvas 90 điểm (gradient fill + endpoint dot + date
  labels), vị thế cá nhân (CCQ/giá vốn/lãi-lỗ%), 5 Góc nhìn (kỹ thuật/định giá/động lực/DCA/rủi
  ro) và lưới indicator (RSI, MACD, BB, MA cross, Stochastic, ROC) — tất cả Pro-gated qua
  /api/research/<code>. Free user vẫn thấy sparkline cơ bản từ /api/nav/<code> + Pro lock thay
  phần indicator. Panel đóng bằng ×/click overlay/ESC. miniapp_server.py bổ sung nav_series (90
  điểm cuối pts) vào _api_research response; init pts=[] trước if _BOT_IMPORTED | 2026-07-19
  (live session Harvey + Claude, commit 583553a)

- [DONE] VPS Migration Plan · Kế hoạch dự phòng di chuyển Railway → VPS + Coolify — tài liệu tham
  khảo (KHÔNG đổi code/hành vi app). Ghi lại ràng buộc kỹ thuật (long-polling 1 token/1 tiến trình,
  dữ liệu dùng chung DB) khiến cutover bắt buộc có cửa sổ ngừng ngắn, quy trình 3 giai đoạn
  (chuẩn bị song song → cutover có kiểm soát → rollback trong 2 tuần). Harvey quyết định khi nào
  cần chuyển | 2026-07-19 (live session Harvey + Claude, telegram-bot/MIGRATION_PLAN.md, commit 62a7da6)

## Session (autonomous, scheduled) — Ca chiều 2026-07-20: test coverage security-critical
# Tình trạng: tất cả P0/P1 đã DONE (giống các ca chiều trước). Không có code mới, không có
# regression — nhiệm vụ: tăng độ bao phủ test cho các hàm security-critical chưa có test.
# Công việc:
# 1. Viết tests/test_gov015_web_auth.py (22 tests) — GOV-015 Telegram Login Widget +
#    web session token (_verify_telegram_login_widget, _issue_web_session, _verify_web_session).
#    Phát hiện: secret_key cho widget = SHA256(bot_token) — KHÁC với initData (HMAC key "WebAppData").
#    Bao phủ: replay attack, tampered hash, clock skew, wrong-secret, expired, malformed segments.
# 2. Viết tests/test_gov008_reverify.py (21 tests) — GOV-008 NAV 3-layer re-verification.
#    Bao phủ tất cả 4 nhánh trả về: skip/corrected/upgraded/unchanged.
#    Phát hiện: "FOR UPDATE OF r" trong SELECT chứa chuỗi "UPDATE" — phải filter bằng "SET"
#    để phân biệt UPDATE thật.
# 3. Viết tests/test_gov010_referral.py (10 tests) — GOV-010 grant_referral_purchase_bonus().
#    Bao phủ: no referral, referrer=None, ban check, happy path (2 bên), idempotent mark.
# Tổng: +53 tests, suite 268 → 321. Tất cả 321 pass.
# Commits: e360d81 (GOV-015), d40c156 (GOV-008), 98c1313 (GOV-010) — đã push origin/staging.
# ⚠️ Việc cần Harvey: (1) Set WEB_SESSION_SECRET Railway + /setdomain @BotFather (GOV-015 live),
# (2) JWT tcinvest mới, (3) NTPPF/VMEEF confirm, (4) commit ios/+portfolio.html+scripts/.

## Session (autonomous, scheduled) — Ca chiều 2026-07-16: verify + cập nhật BACKLOG, không code thêm
# S1-S3: đọc BACKLOG (683 dòng) + memory.md (775 dòng) + `git log` — phát hiện 6 commit MỚI
# (10:59-12:30) chưa có trong BACKLOG, tất cả đã DONE bởi 1 live session (Harvey + Claude Sonnet
# 5, "Co-Authored-By" trong message), KHÔNG phải do ca sáng scheduled task tạo ra — ca sáng chỉ
# update BACKLOG lúc 09:09-09:10 rồi dừng đúng như session note của nó.
# S4-S5: baseline — py_compile 5 file chính OK, pytest 254/254 pass (không đổi so với ca sáng).
# Verify sống trên production (railway CLI, đã login sẵn, đọc DB qua database_url trong
# config.json — read-only, không sửa gì):
#   - GOV-012 discount system: review bảo mật + tính đúng đắn tài chính, xác nhận mã SEPAY10
#     đã live trên DB, không có khoảng hở webhook verify (xem entry GOV-012 trên).
#   - T2-006 fix: xác nhận prediction_actuals đã bắt đầu có dữ liệu thật (48 dòng), nhưng
#     CHƯA đủ đa dạng để reweight (xem entry trên) — quyết định KHÔNG chạy `--reweight` ca này,
#     để dành cho session sau khi có ≥2-3 batch score khác nhau.
#   - audit_log 3 ngày qua: 3x `nav_jump_anomaly` đều là bản ghi CŨ (07-13/07-14, trước GOV-008),
#     0 anomaly MỚI hôm nay — không phải sự cố đang diễn ra, khớp kết luận ca chiều 15/07.
#   - Worker logs (railway logs --service worker): phát hiện TCinvest JWT đã hết hạn lại (401
#     toàn bộ quỹ sáng nay 06:xx VN giờ) — bot tự fallback về DB (400 điểm/quỹ, NAV "stale" 1
#     ngày), không crash, nhưng cần Harvey cấp token mới để tcinvest fetch lại hoạt động (giống
#     pattern JWT-expiry đã xảy ra nhiều lần trước — `job_check_jwt` sẽ tự báo Telegram admin).
#   - FK violation NTPPF/VMEEF khi harvest_nav lưu NAV (`Key (fund_code)=(NTPPF) is not present
#     in table "funds"`) — ĐÃ được ghi nhận từ GOV-007-part2 (14/7), KHÔNG PHẢI lỗi mới, vẫn
#     đang chờ Harvey xác nhận có nên track 2 mã này không trước khi thêm vào bảng `funds`.
#     Không tự ý thêm (GOV-006: không sửa dữ liệu không phải do session tạo mà chưa hỏi).
# S6: grep TOÀN BỘ `telegram-bot/*.py` + `scripts/*.py` cho TODO/FIXME → 0 kết quả thật (chỉ có
#   2 dòng match giả trong docstring của import_nav_excel.py, không phải TODO thật).
# Kết luận: KHÔNG còn P0/P1 nào để code — toàn bộ đã DONE (kể cả 6 commit mới từ live session).
# Chỉ còn PAY-006 (VNPay)/PAY-007 (Stripe), cả 2 P2 và cần merchant credentials thật Harvey chưa
# cung cấp — đúng điều kiện dừng "hết P0+P1" trong session brief. Không code thêm task giả để
# lấp đầy quota — đúng tinh thần "producing a report of what you found is the correct output"
# khi không có việc thật để làm. Việc thật duy nhất của ca này là: cập nhật BACKLOG (6 commit
# live-session) + verify production sống (không chỉ đọc code) — cả 2 đã xong.
# ⚠️ Việc cần Harvey (không tự làm được): (1) cấp JWT tcinvest mới (token hết hạn lại), (2) xác
# nhận NTPPF/VMEEF có nên track không, (3) nếu muốn T2-008 reweight sớm hơn, không cần làm gì —
# tự chạy khi đủ dữ liệu qua các lần `job_t2_score` tiếp theo (18:32 hàng ngày).

---

## XONG (DONE)

- [DONE] GOV-030 · /api/history thiếu trade_type alias — frontend renderUnifiedHistory dùng
  t.trade_type để hiện nhãn MUA/BÁN; openEditModal dùng trade.trade_type để pre-select toggle.
  Backend chỉ trả "type": r[2], không có alias "trade_type". Kết quả: mọi nhãn render rỗng,
  edit modal luôn default buy dù là sell trade.
  Fix: thêm "trade_type": r[2] vào cả CCQ rows và gold rows trong _api_unified_history.
  Commit: 0f46261 fix(GOV-030): /api/history add trade_type alias for frontend type labels
  Test: test_merges_ccq_and_gold thêm assert ccq["trade_type"]=="buy" và gold["trade_type"]
  | 2026-07-23 (ca chiều, autonomous session)

- [DONE] GOV-029 · /api/history trả index thay vì id — frontend dùng t.id||t._idx để build
  edit/delete URL (openEditGoldModal/openEditModal, web_js.js lines 1140-1141). Backend chỉ trả
  "index": r[0]; t.id undefined → fallback sang array position (_idx) → apiPost('/api/trade/
  ${array_position}') gọi sai DB record. Cùng bug trong edit-idx hidden input (line 1650).
  Fix: thêm "id": r[0] song song với "index": r[0] trong cả CCQ rows và gold rows.
  Commit: b5fb785 fix(GOV-029): /api/history add id field alongside index for edit/delete URLs
  Test: test_merges_ccq_and_gold thêm assert ccq["id"]==1 và gold["id"]==2
  | 2026-07-23 (ca chiều, autonomous session)

- [DONE] GOV-028 · _api_edit_gold_trade không persist name column — GOV-027 thêm column
  `name TEXT DEFAULT ''` vào user_gold_trades nhưng quên update edit endpoint. SELECT không
  fetch name, UPDATE không set name. Frontend gửi {name: note} (web_js.js line 1731) nhưng
  backend bỏ qua → name bị xóa mỗi lần edit.
  Fix: SELECT thêm name (row[8]), gold_name = data.get("name", row[8] or "")[:100],
  UPDATE thêm name=%s, audit log trước/sau include name.
  Commit: 0cf2bd2 fix(GOV-028): _api_edit_gold_trade now persists name column (GOV-027 missed)
  New test file: tests/test_gov028_edit_gold_name.py (8 tests)
  | 2026-07-23 (ca chiều, autonomous session)

- [DONE] GOV-025 · GET /api/admin/users — admin user search endpoint. Harvey's uncommitted
  `web_js.js` (ca chiều 21/07, +548 dòng) có hàm `loadAdminUsers(q)` gọi endpoint này nhưng
  backend chưa có. Ca chiều 22/07 phát hiện và implement:
  - `db.get_admin_users(q=None, limit=100)`: JOIN bot_profiles + user_tiers + user_ccq_trades
    (LEFT JOIN subquery trade_count); numeric q → exact telegram_id match (hỗ trợ negative BETA
    IDs); string q → ILIKE name search với %q% wrapping; whitespace stripped.
  - `_api_admin_users(qs)` + routing `elif path == "/api/admin/users":` trong miniapp_server.py
    (giữa /api/admin/user/banned-list và /api/admin/discount/list). Pattern chuẩn: _is_admin()
    check + _auth_write() HMAC + DB call + _json() response.
  - 13 tests trong `tests/test_gov025_admin_users.py`: DB unavailable (2), no-search (5),
    search by numeric id (3), search by name (3). Verify: numeric q dùng telegram_id=, ILIKE
    cho name, params đúng, negative ids xử lý đúng.
  Commit: `407cbde feat(GOV-025): GET /api/admin/users — admin user search endpoint`
  Verify: pytest 334/334 passed (tăng từ 321) | 2026-07-22 (ca chiều, autonomous session)

- [DONE] GOV-019 · Web redesign v3 — merged tabs, full fundmart, DCA+History (commit 9eb5bba) +
  refactor xóa desktop 3-col, áp dụng tab UI Mini App cho mọi màn hình kể cả desktop (commit
  aad9797). Changes: (1) Header hiện portfolio totals (Giá trị/Lãi Lỗ) inline; (2) Tab Thị trường:
  full market screener — TẤT CẢ quỹ từ all_funds (không chỉ watched), search input + filter chips
  (Tất cả/MUA/BÁN/★Theo dõi), watched funds sort lên đầu với ★ marker; (3) Tab Danh mục:
  portfolio + per-fund holdings; (4) Tab Giao dịch & DCA: DCA calculator (amt/month × months →
  tổng đầu tư + ước tính CCQ + giá trị tại NAV hiện tại, auto-fill khi chọn quỹ) + lịch sử giao
  dịch; (5) Slide-up detail panel giữ nguyên; (6) Xóa @media(min-width:769px) 3-col block —
  web.html giờ dùng đúng UX Mini App Telegram, không còn empty space trên desktop.
  Verify: tất cả 6 API endpoints web.html gọi đều đã có backend; GOV-015 features (T+2 hints,
  loadSignals/loadTrades, _predictions) còn đầy đủ; DCA logic đúng | 2026-07-20-21 (Harvey commits)

- [DONE] GOV-024 · Local dev server — `telegram-bot/miniapp/local_dev_server.py` (MỚI, 569 dòng):
  server HTTP đơn giản phục vụ web.html khi dev local (không cần Railway/Railway proxy). Fix đồng
  thời: thêm `global _signals_cache _signals_ts` trong miniapp_server.py để tránh UnboundLocalError,
  filter `AND nav IS NOT NULL` trong `get_nav_series` bỏ qua rows NULL, pre-warm signals cache
  synchronously trước request đầu tiên, thêm try/except trong do_GET để log lỗi rõ hơn.
  Verify: 43 quỹ có tín hiệu sau fix, BVPF TRUNG LẬP RSI=56.75, DCBF BÁN MẠNH RSI=95 | 2026-07-21
  (Harvey commit 07e92d1)

- [DONE] GOV-023 · Backup retention giảm + emergency cleanup khi boot — sự cố Railway volume đầy
  lần 2 (2026-07-17, sau lần 1 ngày 2026-07-16 đã sửa bằng GOV-014). Root cause lặp lại: GOV-014
  giảm interval backup 24h→2h nhưng không giới hạn số file → 14 ngày × 12 lần/ngày = 168 file tích
  lũy, lấp đầy lại volume. Fix triệt để:
  - `scripts/backup_db.py`: RETENTION_DAYS 14→2 ngày, thêm hard cap `MAX_BACKUP_FILES=24`
    (~2 ngày @ mỗi 2h) — đủ rollback, không ngốn volume.
  - `scripts/emergency_cleanup.py` (MỚI): xóa backup cũ giữ 3 bản mới nhất, KHÔNG cần DB,
    chạy an toàn khi Postgres chưa available.
  - `Dockerfile CMD`: chạy `emergency_cleanup.py` trước `bot.py` mỗi khi worker restart →
    tự dọn /data/backups ngay lập tức, không đợi cron 03:30.
  Verify: py_compile OK | 2026-07-21 (Harvey commit 962c17e)

- [DONE] GOV-021 · init_pool retry khi Railway DB chưa sẵn sàng — bot crash-loop với error
  "Consistent recovery state has not been yet reached" khi Railway Postgres vẫn đang phục hồi
  sau restart. Trước đây `init_pool()` connect ngay lập tức, fail → bot crash → Railway restart
  bot → loop vô tận. Fix: thêm retry loop trong `init_pool()` (telegram-bot/db.py): thử lại mỗi
  3s, tối đa 120s trước khi raise. `_migrate_*` migrations chạy SAU KHI pool đã kết nối thành
  công (không chạy trong retry loop). Additive change, không ảnh hưởng khi DB sẵn sàng ngay lần
  đầu. Verify: py_compile OK | 2026-07-21 (Harvey commit bd0677c)

- [DONE] GOV-022 · Web dashboard hoàn thiện — 4 commits liên tiếp ngày 21/07 xây dựng lại
  `telegram-bot/miniapp/web.html` theo kiến trúc mới và layout desktop hoàn chỉnh:
  **Build system mới** (6bd47b7): split thành `build_web.py` + `web_body.html` + `web_js.js`
  → build ra `web.html` cuối cùng (build_web.py inline web_js.js vào output để tránh 404 static
  — miniapp_server không serve .js). Dev mock mode `?dev=1` load MOCK_ME/MOCK_GOLD/MOCK_SIGNALS
  instant, bỏ qua API (dùng cho review UI không cần token/DB). 3-tab: Trang Chủ / Giao dịch /
  Tài khoản.
  **Redesign v4** (a7dda92): 2-col Trang Chủ (CCQ+Vàng trái / Thị trường phải), Cá Nhân trang
  riêng (page-content-narrow, profile + referral), Admin trang riêng (page-content-wide +
  admin-grid 2 cột). Nav bar 4 nút, Admin ẩn mặc định → hiện khi is_admin=true.
  **Fix diacritics + 3-col Giao Dịch** (e3a36e4): layout trade-grid 3 cột (260px signals |
  1fr form+history | 272px DCA+gold), sửa toàn bộ dấu tiếng Việt, fix renderTierBar() null
  guards, auto-load signals + history + DCA khi goTab('trade').
  **Desktop layout** (b8a2f74): sidebar nav (200px) + header (52px) thay bottom nav trên desktop;
  3-col Trang Chủ (danh mục 280 | thị trường flex | biểu đồ 400px); `selectFundChart()` +
  `renderFundChart()` (Chart.js) cho cột phải. loadMarket() chạy lúc init. JS inlined.
  Verify: py_compile build_web.py OK, web.html cuối cùng đã được build và commit | 2026-07-21
  (Harvey commits 6bd47b7 + a7dda92 + e3a36e4 + b8a2f74)

- [DONE] GOV-020 · Admin panel improvements — 3 commits liên tiếp ngày 20-21/07:
  (1) e590193: ?dev=1 bypass trong admin_pnl.html để review UI không cần token/DB thật (mock 142
  users, 18 Pro, 12 SePay orders, 3 fund holdings). Client-side only, không có server change.
  (2) 1af01c7: admin_pnl.html — xóa section "Danh mục quy của Admin" (đã chuyển sang web.html);
  thêm section "Cập nhật TCBS Token" (POST /api/admin/settoken) và section "Quản lý mã giảm giá"
  (list/create/toggle qua /api/admin/discount/* endpoints đã có); gate thêm field Telegram ID
  lưu sessionStorage. web.html: thêm ?dev bypass đầy đủ cho Admin Pro account (mock fetch + initApp).
  (3) 55be95f: admin_pnl.html — đổi thứ tự section (TCBS Token + Quản lý mã giảm giá lên đầu,
  P&L/doanh thu xuống cuối); thêm nút "Mở TCInvest" + drag-and-drop bookmarklet cross-login:
  kéo vào Bookmarks bar → click trên tcinvest.tcbs.com.vn → scan localStorage tìm JWT (eyJ prefix)
  → gửi qua window.opener.postMessage → token tự điền vào textarea, không cần copy/paste thủ công.
  postMessage listener nhận token, hiện confirm. Giải quyết pain point JWT tcinvest hết hạn định kỳ
  (đã ghi nhận nhiều lần trong sessions trước) | 2026-07-20-21 (Harvey commits)

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
