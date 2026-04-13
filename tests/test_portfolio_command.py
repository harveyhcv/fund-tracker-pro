"""
test_portfolio_command.py — Unit tests cho /portfolio command (msg_portfolio)
Functions: msg_portfolio, _msg_portfolio_detail
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import bot as B

# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_nav(nav=13500.0, signal="HOLD ⚪", score=0):
    return {
        "signal": signal, "nav": nav, "nav_date": "2026-04-13",
        "score": score, "rsi": 50.0, "bb_pct": 50.0, "macd_hist": 0.0,
        "nav_prev": 13480.0, "chg_pct": 0.15, "details": [],
        "ma20": 13400.0, "ma50": 13200.0, "chg7": 0.5, "chg30": 1.2,
    }


PROFILE_NO_PORTFOLIO = {
    "name": "Harvey",
    "telegram_id": "111222333",
    "watched_funds": ["TCBF", "SSISCA"],
}

PROFILE_WITH_PORTFOLIO = {
    "name": "Harvey",
    "telegram_id": "111222333",
    "watched_funds": ["TCBF", "SSISCA"],
    "portfolio": [
        {"code": "TCBF",   "units": 10000, "avg_cost": 12500},
        {"code": "SSISCA", "units": 5000,  "avg_cost": 20000},
    ],
}

NAV_DATA = {
    "TCBF":   _make_nav(13500.0, "MUA 🟢"),
    "SSISCA": _make_nav(21000.0, "HOLD ⚪"),
}


# ════════════════════════════════════════════════════════
# Fallback (không có portfolio data)
# ════════════════════════════════════════════════════════

class TestMsgPortfolioFallback:

    def test_shows_fund_codes(self):
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, NAV_DATA)
        assert "TCBF" in msg
        assert "SSISCA" in msg

    def test_shows_profile_name(self):
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, NAV_DATA)
        assert "Harvey" in msg

    def test_shows_signal(self):
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, NAV_DATA)
        assert "MUA 🟢" in msg

    def test_shows_7_30_day_change(self):
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, NAV_DATA)
        assert "7 ngày" in msg or "30 ngày" in msg

    def test_no_pnl_section_when_no_portfolio(self):
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, NAV_DATA)
        assert "Giá vốn" not in msg
        assert "Tổng:" not in msg

    def test_handles_missing_nav_gracefully(self):
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, {"TCBF": None, "SSISCA": None})
        assert "N/A" in msg

    def test_handles_zero_nav_gracefully(self):
        nav_zero = {"TCBF": _make_nav(0), "SSISCA": _make_nav(0)}
        msg = B.msg_portfolio(PROFILE_NO_PORTFOLIO, nav_zero)
        assert "N/A" in msg


# ════════════════════════════════════════════════════════
# P&L detail (có portfolio data)
# ════════════════════════════════════════════════════════

class TestMsgPortfolioDetail:

    def test_shows_pnl_section(self):
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, NAV_DATA)
        assert "Giá vốn" in msg
        assert "Giá trị" in msg

    def test_shows_total_value(self):
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, NAV_DATA)
        assert "Tổng:" in msg

    def test_calculates_profit_correctly(self):
        """TCBF: 10000 CCQ × 13500 = 135,000,000đ; vốn = 10000 × 12500 = 125,000,000đ → lãi 10,000,000đ"""
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, {"TCBF": _make_nav(13500.0), "SSISCA": _make_nav(20000.0)})
        # TCBF: nav=vốn=12500, không lãi lỗ. Với nav 13500 > avg_cost 12500 → Lãi
        assert "Lãi" in msg

    def test_calculates_loss_correctly(self):
        """TCBF avg_cost=12500, nav=11000 → lỗ"""
        nav_loss = {"TCBF": _make_nav(11000.0), "SSISCA": _make_nav(20000.0)}
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, nav_loss)
        assert "Lỗ" in msg

    def test_shows_units_in_message(self):
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, NAV_DATA)
        assert "10,000.000 CCQ" in msg or "10000" in msg

    def test_shows_percent_change(self):
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, NAV_DATA)
        assert "%" in msg

    def test_total_includes_both_funds(self):
        """Tổng = TCBF value + SSISCA value"""
        # TCBF: 10000 × 13500 = 135,000,000đ
        # SSISCA: 5000 × 21000 = 105,000,000đ
        # Tổng = 240,000,000đ
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, NAV_DATA)
        assert "240" in msg.replace(",", "").replace(".", "")  # 240000000

    def test_handles_missing_nav_in_portfolio(self):
        """Quỹ trong portfolio nhưng không có NAV data → hiện cảnh báo, không crash."""
        msg = B.msg_portfolio(PROFILE_WITH_PORTFOLIO, {})
        assert "N/A" in msg

    def test_empty_portfolio_falls_back(self):
        """portfolio = [] → fallback về view 7/30 ngày."""
        profile_empty = {**PROFILE_WITH_PORTFOLIO, "portfolio": []}
        msg = B.msg_portfolio(profile_empty, NAV_DATA)
        assert "7 ngày" in msg or "30 ngày" in msg

    def test_portfolio_with_zero_units_ignored(self):
        """Holdings với units=0 bị bỏ qua → fallback."""
        profile_zero = {**PROFILE_WITH_PORTFOLIO, "portfolio": [
            {"code": "TCBF", "units": 0, "avg_cost": 12500}
        ]}
        msg = B.msg_portfolio(profile_zero, NAV_DATA)
        assert "7 ngày" in msg or "30 ngày" in msg
