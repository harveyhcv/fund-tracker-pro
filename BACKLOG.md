# BACKLOG — Fund Tracker Pro
# Format: [STATUS] ID · Mô tả | Priority | Estimate | Dependency
# Status: TODO / IN_PROGRESS / DONE / BLOCKED
# Priority: P0 (blocker) / P1 (important) / P2 (nice-to-have)
# Claude đọc file này ĐẦU TIÊN mỗi session. Pick task IN_PROGRESS nếu có, nếu không pick P0 cao nhất.
#
# Last updated: 2026-07-08

## ĐANG LÀM (IN_PROGRESS)
# Không có task đang chạy — pick P0 đầu tiên

## CẦN LÀM — P0 (Blockers, phải xong trước khi public)


## CẦN LÀM — P1 (Important)

- [TODO] USR-001 · Multi-user registration: lưu DB thay vì config.json | P1 | 5h | SEC-002

## CẦN LÀM — P2 (Nice-to-have)

- [TODO] DASH-001 · Multi-fund selector trên Dashboard (thay vì hardcode) | P2 | 4h | none
- [TODO] FMKT-001 · fmarket_id cho các mã chưa có (tra thủ công hoặc scrape) | P2 | 2h | none

## XONG (DONE)

- [DONE] JWT-001 · TCBS token expiry: decode JWT exp, job 07:30 notify admin 3 ngày trước khi hết | 2026-07-08
- [DONE] DB-001 · Scheduled NAV harvest 18:30 daily — job_harvest_nav() + harvest_nav.py đã implement | 2026-07-08
- [DONE] SIG-006 · Sortino Ratio (rolling 1Y, rf=5%) vào calc_signal() return dict | 2026-07-08
- [DONE] SIG-005 · Volatility annualized (rolling 252 ngày) vào calc_signal() return dict | 2026-07-08
- [DONE] SIG-004 · CCI(20) + ROC(10) vào calc_signal() scoring + return dict | 2026-07-08
- [DONE] GIT-001 · .gitignore hardening: *.log, nav_data.json, daily_review_*.md, __pycache__, .venv | 2026-07-08
- [DONE] SIG-003 · Sharpe Ratio (rolling 1Y, rf=5%) + Max Drawdown 1Y vào calc_signal() + morning report | 2026-07-08
- [DONE] SIG-002 · Stochastic %K/%D (14,3,3) vào calc_signal() + stoch_k/stoch_d trong return dict | 2026-07-08
- [DONE] SIG-001 · Golden Cross / Death Cross (MA20xMA50) vào calc_signal() + gc_type trong return dict | 2026-07-08
- [DONE] SEC-003 · Auth header (X-API-Key) cho server.py mutating endpoints, backward-compat khi key chưa set | 2026-07-08
- [DONE] SEC-002 · Move secrets khỏi config.json sang env vars (BOT_TOKEN, DATABASE_URL, TCBS_TOKEN) | 2026-07-08
- [DONE] BUG-001 · /portfolio chỉ hiện 3/5 mã Harvey (DB path intercept, bỏ qua config.json) | 2026-07-08
- [DONE] BUG-002 · NameError: parts chưa được define trước khi dùng trong loop | 2026-07-08
- [DONE] BUG-003 · /explain và /research bị restore nhầm — đã revert về pass (no-op) | 2026-07-08
- [DONE] BUG-004 · fetch_tcinvest() dùng endpoint sai — đã fix sang apiextaws.tcbs.com.vn | 2026-07-08
- [DONE] BUG-005 · Gold signal stuck 7 ngày vì source SJC dead — đã fix sang giavang.org | 2026-07-08
- [DONE] DATA-001 · Import 91,747 NAV datapoints cho 38 quỹ vào Railway PostgreSQL | 2026-07-08
- [DONE] SEC-001 · Rate limiting cho bot commands (max 10 req/min per user, sliding window per chat_id) | 2026-07-08

## BLOCKED

# Không có task bị block hiện tại
