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

- [TODO] SEC-002 · Move secrets khỏi config.json sang env vars (BOT_TOKEN, DATABASE_URL, TCBS_TOKEN) | P0 | 1h | none
- [TODO] SEC-003 · Auth header cho server.py endpoints (tránh bất kỳ ai gọi /save-nav) | P0 | 2h | none
- [TODO] SIG-001 · Golden Cross / Death Cross signal (MA20×MA50) vào calc_signal() | P0 | 3h | none
- [TODO] SIG-002 · Stochastic %K/%D (14,3,3) vào calc_signal() | P0 | 3h | SIG-001
- [TODO] SIG-003 · Sharpe Ratio (rolling 1Y) + Max Drawdown 1Y vào morning report | P0 | 2h | none

## CẦN LÀM — P1 (Important)

- [TODO] SIG-004 · CCI (20) + ROC (10) vào calc_signal() | P1 | 2h | SIG-001
- [TODO] SIG-005 · Volatility annualized (rolling 252 ngày) | P1 | 1h | none
- [TODO] SIG-006 · Sortino Ratio (rolling 1Y) | P1 | 2h | SIG-003
- [TODO] USR-001 · Multi-user registration: lưu DB thay vì config.json | P1 | 5h | SEC-002
- [TODO] JWT-001 · TCBS JWT auto-refresh (thay vì manual paste) | P1 | 3h | none
- [TODO] DB-001 · Scheduled NAV harvest từ TCinvest/fmarket vào Railway (cron daily) | P1 | 3h | none

## CẦN LÀM — P2 (Nice-to-have)

- [TODO] DASH-001 · Multi-fund selector trên Dashboard (thay vì hardcode) | P2 | 4h | none
- [TODO] GIT-001 · .gitignore hardening: thêm config.json, *.log, __pycache__ | P2 | 30m | none
- [TODO] FMKT-001 · fmarket_id cho các mã chưa có (tra thủ công hoặc scrape) | P2 | 2h | none

## XONG (DONE)

- [DONE] BUG-001 · /portfolio chỉ hiện 3/5 mã Harvey (DB path intercept, bỏ qua config.json) | 2026-07-08
- [DONE] BUG-002 · NameError: parts chưa được define trước khi dùng trong loop | 2026-07-08
- [DONE] BUG-003 · /explain và /research bị restore nhầm — đã revert về pass (no-op) | 2026-07-08
- [DONE] BUG-004 · fetch_tcinvest() dùng endpoint sai — đã fix sang apiextaws.tcbs.com.vn | 2026-07-08
- [DONE] BUG-005 · Gold signal stuck 7 ngày vì source SJC dead — đã fix sang giavang.org | 2026-07-08
- [DONE] DATA-001 · Import 91,747 NAV datapoints cho 38 quỹ vào Railway PostgreSQL | 2026-07-08
- [DONE] SEC-001 · Rate limiting cho bot commands (max 10 req/min per user, sliding window per chat_id) | 2026-07-08

## BLOCKED

# Không có task bị block hiện tại
