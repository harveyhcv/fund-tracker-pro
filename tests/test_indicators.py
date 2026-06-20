"""
test_indicators.py — QA cho Technical Indicators trong bot.py
Functions: calc_rsi, calc_macd, calc_bb, calc_signal, _ema, _avg
"""
import sys, json, math
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Import trực tiếp từ bot.py ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
# Patch CONFIG_FILE trước khi import để tránh FileNotFoundError
with patch("builtins.open", side_effect=lambda *a, **k: open(*a, **k)):
    pass
# Bot dùng CONFIG_FILE = BASE / "config.json" — ta cần file tồn tại
import bot as B   # import thẳng

# ── Dữ liệu test ────────────────────────────────────────────────────────────

def make_pts(navs: list) -> list:
    """Tạo list {date, nav} từ list giá trị NAV."""
    from datetime import date, timedelta
    base = date(2024, 1, 1)
    return [{"date": (base + timedelta(days=i)).isoformat(), "nav": v}
            for i, v in enumerate(navs)]

# 100 điểm NAV tăng dần nhẹ (realistic bond fund)
NAVS_100 = [10000 + i * 10 + (i % 5) * 3 for i in range(100)]

# 100 điểm giả lập downtrend rõ
NAVS_DOWN = [13000 - i * 15 - (i % 7) * 5 for i in range(100)]

# 100 điểm dao động sideway
NAVS_FLAT = [12000 + (i % 20 - 10) * 5 for i in range(100)]


# ════════════════════════════════════════════════════════
# _avg và _ema
# ════════════════════════════════════════════════════════

class TestAvgEma:

    def test_avg_simple(self):
        assert B._avg([10, 20, 30]) == 20.0

    def test_avg_single(self):
        assert B._avg([5.5]) == 5.5

    def test_ema_returns_float(self):
        result = B._ema([10, 11, 12, 13, 14], 3)
        assert isinstance(result, float)

    def test_ema_period_1_equals_last(self):
        navs = [10.0, 20.0, 30.0]
        result = B._ema(navs, 1)
        assert result == 30.0

    def test_ema_smoothing(self):
        # EMA phải smooth hơn simple average — không test exact value
        navs = [100]*10 + [200]*10
        ema = B._ema(navs, 5)
        avg = B._avg(navs[-5:])
        assert ema != avg  # EMA khác simple average


# ════════════════════════════════════════════════════════
# calc_rsi
# ════════════════════════════════════════════════════════

class TestCalcRsi:

    def test_returns_none_when_insufficient_data(self):
        assert B.calc_rsi([100, 101, 102]) is None  # cần ≥ 15 pts

    def test_returns_none_at_boundary_14(self):
        assert B.calc_rsi([100 + i for i in range(14)]) is None  # cần period+1=15

    def test_returns_float_with_enough_data(self):
        result = B.calc_rsi(NAVS_100)
        assert isinstance(result, float), f"Phải trả float, got {type(result)}"

    def test_rsi_range_0_to_100(self):
        for navs in [NAVS_100, NAVS_DOWN, NAVS_FLAT]:
            rsi = B.calc_rsi(navs)
            assert rsi is not None
            assert 0 <= rsi <= 100, f"RSI={rsi} ngoài [0,100]"

    def test_rsi_uptrend_above_50(self):
        # NAV tăng đều → RSI cao
        navs = [10000 + i * 50 for i in range(30)]
        rsi = B.calc_rsi(navs)
        assert rsi is not None and rsi > 50, f"Uptrend RSI phải > 50, got {rsi}"

    def test_rsi_downtrend_below_50(self):
        # NAV giảm đều → RSI thấp
        navs = [13000 - i * 50 for i in range(30)]
        rsi = B.calc_rsi(navs)
        assert rsi is not None and rsi < 50, f"Downtrend RSI phải < 50, got {rsi}"

    def test_rsi_100_when_no_losses(self):
        # Chỉ tăng, không có ngày giảm → RSI = 100
        navs = [10000 + i * 10 for i in range(20)]
        rsi = B.calc_rsi(navs)
        assert rsi == 100.0, f"All-up RSI phải = 100, got {rsi}"

    def test_rsi_rounded_2_decimals(self):
        rsi = B.calc_rsi(NAVS_100)
        assert rsi == round(rsi, 2), f"RSI phải round 2 chữ số, got {rsi}"

    def test_rsi_custom_period(self):
        # period=7 cần 8 điểm tối thiểu
        navs = [100 + i for i in range(10)]
        result = B.calc_rsi(navs, period=7)
        assert result is not None

    def test_rsi_insufficient_for_custom_period(self):
        navs = [100 + i for i in range(7)]  # cần 8
        result = B.calc_rsi(navs, period=7)
        assert result is None


# ════════════════════════════════════════════════════════
# calc_bb (Bollinger Bands)
# ════════════════════════════════════════════════════════

class TestCalcBb:

    def test_returns_none_when_insufficient(self):
        assert B.calc_bb([100] * 19) is None  # cần ≥ 20

    def test_returns_dict_with_enough_data(self):
        result = B.calc_bb(NAVS_100)
        assert isinstance(result, dict)

    def test_result_has_required_keys(self):
        result = B.calc_bb(NAVS_100)
        for key in ("upper", "lower", "mid", "pct"):
            assert key in result, f"BB thiếu key: {key}"

    def test_upper_above_mid_above_lower(self):
        result = B.calc_bb(NAVS_100)
        assert result["upper"] > result["mid"] > result["lower"], \
            f"upper={result['upper']}, mid={result['mid']}, lower={result['lower']}"

    def test_pct_range_typically_0_to_100(self):
        result = B.calc_bb(NAVS_FLAT)
        pct = result["pct"]
        # Sideways data nên nằm trong 0-100
        assert -20 <= pct <= 120, f"BB pct={pct} quá extreme"

    def test_pct_near_100_when_at_upper_band(self):
        # NAV tăng mạnh → price ở gần/trên upper band → pct cao
        navs = [10000] * 19 + [13000]
        result = B.calc_bb(navs)
        assert result["pct"] > 80, f"Spike lên phải pct > 80, got {result['pct']}"

    def test_pct_near_0_when_at_lower_band(self):
        # NAV giảm mạnh → price gần lower band → pct thấp
        navs = [10000] * 19 + [7000]
        result = B.calc_bb(navs)
        assert result["pct"] < 20, f"Spike xuống phải pct < 20, got {result['pct']}"

    def test_pct_rounded_1_decimal(self):
        result = B.calc_bb(NAVS_100)
        pct = result["pct"]
        assert pct == round(pct, 1), f"pct phải round 1 chữ số, got {pct}"

    def test_equal_navs_pct_50(self):
        # Tất cả cùng NAV → upper == lower → pct = 50 (theo code)
        navs = [10000.0] * 20
        result = B.calc_bb(navs)
        assert result["pct"] == 50.0


# ════════════════════════════════════════════════════════
# calc_macd
# ════════════════════════════════════════════════════════

class TestCalcMacd:

    def test_returns_none_when_insufficient(self):
        # Cần slow + signal_p + 5 = 26+9+5 = 40
        assert B.calc_macd([100] * 39) is None

    def test_returns_dict_with_enough_data(self):
        result = B.calc_macd(NAVS_100)
        assert isinstance(result, dict)

    def test_result_has_required_keys(self):
        result = B.calc_macd(NAVS_100)
        for key in ("macd", "signal", "hist"):
            assert key in result, f"MACD thiếu key: {key}"

    def test_hist_equals_macd_minus_signal(self):
        result = B.calc_macd(NAVS_100)
        expected_hist = round(result["macd"] - result["signal"], 4)
        assert abs(result["hist"] - expected_hist) < 1e-6, \
            f"hist={result['hist']} phải = macd-signal={expected_hist}"

    def test_uptrend_macd_positive(self):
        # Uptrend mạnh → MACD hist thường dương
        navs = [10000 + i * 100 for i in range(60)]
        result = B.calc_macd(navs)
        assert result is not None
        # Uptrend: fast EMA > slow EMA → macd > 0
        assert result["macd"] > 0, f"Uptrend MACD phải > 0, got {result['macd']}"

    def test_downtrend_macd_negative(self):
        navs = [15000 - i * 100 for i in range(60)]
        result = B.calc_macd(navs)
        assert result is not None
        assert result["macd"] < 0, f"Downtrend MACD phải < 0, got {result['macd']}"

    def test_values_rounded_4_decimals(self):
        result = B.calc_macd(NAVS_100)
        for key in ("macd", "signal", "hist"):
            v = result[key]
            assert v == round(v, 4), f"{key}={v} phải round 4 chữ số"


# ════════════════════════════════════════════════════════
# calc_signal
# ════════════════════════════════════════════════════════

class TestCalcSignal:

    def test_returns_na_when_insufficient_pts(self):
        # Cần ≥ 60 điểm
        result = B.calc_signal("TCBF", make_pts([100] * 59))
        assert result["signal"] == "N/A", f"< 60 pts phải NA, got {result['signal']}"

    def test_returns_na_with_empty(self):
        result = B.calc_signal("TCBF", [])
        assert result["signal"] == "N/A"

    def test_returns_dict_with_60_pts(self):
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        assert isinstance(result, dict)

    def test_result_has_required_keys(self):
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        for key in ("signal", "score", "rsi", "bb_pct", "macd_hist", "nav",
                    "nav_date", "details", "nav_prev", "chg_pct", "chg7", "chg30"):
            assert key in result, f"calc_signal thiếu key: {key}"

    def test_signal_is_valid_string(self):
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        assert isinstance(result["signal"], str)
        assert len(result["signal"]) > 0

    def test_valid_signal_values(self):
        valid = {"MUA MẠNH 🟢🟢", "MUA 🟢", "BÁN 🔴", "BÁN MẠNH 🔴🔴", "HOLD ⚪", "N/A"}
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        assert result["signal"] in valid, f"Signal không hợp lệ: {result['signal']}"

    def test_strong_uptrend_gives_sell_signal(self):
        # System là MEAN-REVERSION: uptrend mạnh → RSI overbought → BB cao → score ÂM → BÁN
        navs = [10000 + i * 80 for i in range(100)]
        result = B.calc_signal("TCBF", make_pts(navs))
        assert result["score"] < 0, f"Uptrend mạnh → RSI overbought → score phải < 0, got {result['score']}"
        assert result["rsi"] is not None and result["rsi"] > 65, f"Uptrend RSI phải > 65"

    def test_strong_downtrend_gives_buy_signal(self):
        # System là MEAN-REVERSION: downtrend mạnh → RSI oversold → BB thấp → score DƯƠNG → MUA
        navs = [15000 - i * 80 for i in range(100)]
        result = B.calc_signal("TCBF", make_pts(navs))
        assert result["score"] > 0, f"Downtrend mạnh → RSI oversold → score phải > 0, got {result['score']}"
        assert result["rsi"] is not None and result["rsi"] < 35, f"Downtrend RSI phải < 35"

    def test_nav_field_equals_last_nav(self):
        navs = NAVS_100
        pts = make_pts(navs)
        result = B.calc_signal("TCBF", pts)
        assert result["nav"] == navs[-1], \
            f"nav phải = last NAV ({navs[-1]}), got {result['nav']}"

    def test_chg_pct_calculation(self):
        navs = [10000.0, 10200.0]  # 2% tăng
        # Cần 60 pts — pad với stable data trước
        full_navs = [9900.0] * 98 + [10000.0, 10200.0]
        pts = make_pts(full_navs)
        result = B.calc_signal("TCBF", pts)
        expected = (10200 - 10000) / 10000 * 100
        assert abs(result["chg_pct"] - expected) < 0.01, \
            f"chg_pct={result['chg_pct']} phải ≈ {expected:.2f}"

    def test_chg7_is_5_trading_day_change(self):
        # Code dùng navs[-6] làm ref cho chg7 (5 khoảng cách)
        navs = [10000.0] * 94 + [9500.0] * 5 + [10000.0]  # giảm mạnh 5 ngày trước
        pts = make_pts(navs)
        result = B.calc_signal("TCBF", pts)
        # navs[-6] = 9500, navs[-1] = 10000
        expected_chg7 = round((10000 - 9500) / 9500 * 100, 2)
        assert result["chg7"] is not None
        assert abs(result["chg7"] - expected_chg7) < 0.1, \
            f"chg7={result['chg7']} phải ≈ {expected_chg7}"

    def test_details_is_list(self):
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        assert isinstance(result["details"], list)

    def test_details_contains_rsi_info(self):
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        rsi_in_details = any("RSI" in str(d) for d in result["details"])
        assert rsi_in_details, f"details phải chứa RSI info: {result['details']}"

    def test_na_result_has_zero_score(self):
        result = B.calc_signal("TCBF", make_pts([100] * 10))
        assert result["score"] == 0
        assert result["nav"] == 0

    def test_signal_score_mapping(self):
        """Score → Signal mapping thực tế trong code:
        score >= 6 → MUA MẠNH 🟢🟢
        score >= 3 → MUA 🟢
        score <= -6 → BÁN MẠNH 🔴🔴
        score <= -3 → BÁN 🔴
        else → HOLD ⚪"""
        bot_path = Path(__file__).parent.parent / "telegram-bot" / "bot.py"
        with open(bot_path, encoding="utf-8") as f:
            src = f.read()
        assert "MUA MẠNH 🟢🟢" in src, "Thiếu signal MUA MẠNH 🟢🟢"
        assert "MUA 🟢" in src,         "Thiếu signal MUA 🟢"
        assert "BÁN MẠNH 🔴🔴" in src,  "Thiếu signal BÁN MẠNH 🔴🔴"
        assert "BÁN 🔴" in src,          "Thiếu signal BÁN 🔴"
        assert "HOLD ⚪" in src,         "Thiếu signal HOLD ⚪"

    def test_result_has_ma20_ma50(self):
        """calc_signal phải trả về ma20 và ma50"""
        result = B.calc_signal("TCBF", make_pts(NAVS_100))
        assert "ma20" in result, "Thiếu key ma20"
        assert "ma50" in result, "Thiếu key ma50"
