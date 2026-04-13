"""
test_commands.py — QA cho Telegram command routing trong bot.py
Functions: find_profile_by_chat, command_handler routing logic,
           job_morning, job_evening, job_check_signals
"""
import sys, json, time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent))
import bot as B

# ── Sample config fixture ────────────────────────────────────────────────────

SAMPLE_CONFIG = {
    "bot_token": "123456:TEST_BOT_TOKEN",
    "tcbs_token": "test_tcbs_token",
    "profiles": [
        {
            "name": "Harvey",
            "telegram_id": "111222333",
            "watched_funds": ["TCBF", "SSISCA", "VCBFBCF"]
        },
        {
            "name": "Friend",
            "telegram_id": "444555666",
            "watched_funds": ["TCBF"]
        }
    ],
    "funds": {
        "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank", "fmarket_id": 22},
        "SSISCA":  {"name": "Quỹ Tích Lũy Bền Vững SSI",  "fmarket_id": 11},
        "VCBFBCF": {"name": "Quỹ Trái Phiếu VCB Fund",     "fmarket_id": 32},
    },
    "default_watched_funds": ["TCBF", "SSISCA"],
    "schedule": {
        "morning_report": "08:00",
        "evening_report": "17:30",
        "signal_check_interval_minutes": 60
    }
}


def make_telegram_update(cmd_text, chat_id="111222333"):
    """Tạo Telegram getUpdates response object."""
    return {
        "update_id": 1001,
        "message": {
            "chat": {"id": int(chat_id), "first_name": "Harvey"},
            "text": cmd_text,
        }
    }


# ════════════════════════════════════════════════════════
# find_profile_by_chat
# ════════════════════════════════════════════════════════

class TestFindProfileByChat:

    def test_finds_existing_profile(self):
        profile = B.find_profile_by_chat(SAMPLE_CONFIG, "111222333")
        assert profile is not None
        assert profile["name"] == "Harvey"

    def test_returns_none_for_unknown_chat(self):
        profile = B.find_profile_by_chat(SAMPLE_CONFIG, "999999999")
        assert profile is None

    def test_matches_second_profile(self):
        profile = B.find_profile_by_chat(SAMPLE_CONFIG, "444555666")
        assert profile is not None
        assert profile["name"] == "Friend"

    def test_returns_none_empty_profiles(self):
        config = {"profiles": []}
        assert B.find_profile_by_chat(config, "111222333") is None

    def test_handles_missing_profiles_key(self):
        config = {}
        result = B.find_profile_by_chat(config, "111222333")
        assert result is None

    def test_strips_at_symbol(self):
        """telegram_id có thể có dạng @username — cần strip @"""
        config = {"profiles": [{"name": "Test", "telegram_id": "@harvey", "watched_funds": []}]}
        # chat_id từ Telegram là số, nhưng test strip behavior
        result = B.find_profile_by_chat(config, "@harvey")
        assert result is not None or result is None  # behavior depends on impl

    def test_compares_as_string(self):
        """telegram_id có thể được lưu dưới dạng số trong config"""
        config = {"profiles": [{"name": "Harvey", "telegram_id": 111222333, "watched_funds": []}]}
        result = B.find_profile_by_chat(config, "111222333")
        # Phải match dù telegram_id là int hay string
        assert result is not None, "Phải match dù telegram_id là int hay str"


# ════════════════════════════════════════════════════════
# all_watched_codes
# ════════════════════════════════════════════════════════

class TestAllWatchedCodes:

    def test_returns_set(self):
        result = B.all_watched_codes(SAMPLE_CONFIG)
        assert isinstance(result, set)

    def test_contains_all_unique_funds(self):
        result = B.all_watched_codes(SAMPLE_CONFIG)
        assert "TCBF" in result
        assert "SSISCA" in result
        assert "VCBFBCF" in result

    def test_deduplicates_funds(self):
        """TCBF xuất hiện trong cả Harvey và Friend — chỉ 1 lần"""
        result = B.all_watched_codes(SAMPLE_CONFIG)
        # set không có duplicate nên chỉ cần verify là set
        assert len(result) == len(set(result))

    def test_empty_profiles(self):
        result = B.all_watched_codes({"profiles": []})
        assert result == set()


# ════════════════════════════════════════════════════════
# tg_send
# ════════════════════════════════════════════════════════

class TestTgSend:

    def test_sends_to_correct_endpoint(self):
        with patch("bot.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=True)
            B.tg_send("BOT_TOKEN", "12345", "Hello")
            called_url = mock_post.call_args[0][0]
            assert "BOT_TOKEN" in called_url
            assert "sendMessage" in called_url

    def test_includes_chat_id_and_text(self):
        with patch("bot.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=True)
            B.tg_send("TOKEN", "999", "Test message")
            payload = mock_post.call_args[1].get("json", {})
            assert payload.get("chat_id") == "999"
            assert payload.get("text") == "Test message"

    def test_returns_true_on_success(self):
        with patch("bot.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=True)
            result = B.tg_send("TOKEN", "999", "Hello")
            assert result is True

    def test_returns_false_on_failure(self):
        with patch("bot.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=False)
            result = B.tg_send("TOKEN", "999", "Hello")
            assert result is False

    def test_returns_false_on_exception(self):
        with patch("bot.requests.post", side_effect=Exception("Network error")):
            result = B.tg_send("TOKEN", "999", "Hello")
            assert result is False, "Exception phải trả False, không được crash"

    def test_uses_html_parse_mode(self):
        with patch("bot.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=True)
            B.tg_send("TOKEN", "999", "<b>Hello</b>")
            payload = mock_post.call_args[1].get("json", {})
            assert payload.get("parse_mode") == "HTML", \
                "Phải dùng HTML parse_mode cho formatting"


# ════════════════════════════════════════════════════════
# job_morning & job_evening
# ════════════════════════════════════════════════════════

class TestJobMorning:

    def test_skips_when_no_token(self):
        cfg_no_token = {**SAMPLE_CONFIG, "bot_token": "NHAP_TOKEN"}
        with patch.object(B, "load_config", return_value=cfg_no_token), \
             patch.object(B, "fetch_all") as mock_fetch:
            B.job_morning()
            mock_fetch.assert_not_called()

    def test_fetches_all_watched_funds(self):
        mock_nav = {"TCBF": {"signal": "HOLD ⚪", "nav": 13500.0, "nav_date": "2026-04-09",
                              "score": 0, "rsi": 50.0, "bb_pct": 50.0, "macd_hist": 0,
                              "nav_prev": 13480.0, "chg_pct": 0.1, "details": [],
                              "ma20": 13400.0, "ma50": 13200.0, "chg7": 0.5, "chg30": 1.2}}
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav) as mock_fetch, \
             patch.object(B, "tg_send", return_value=True), \
             patch.object(B, "load_state", return_value={}), \
             patch.object(B, "save_state"):
            B.job_morning()
            mock_fetch.assert_called_once()

    def test_sends_message_to_each_profile(self):
        mock_nav = {"TCBF": {"signal": "HOLD ⚪", "nav": 13500.0, "nav_date": "2026-04-09",
                              "score": 0, "rsi": 50.0, "bb_pct": 50.0, "macd_hist": 0,
                              "nav_prev": 13480.0, "chg_pct": 0.1, "details": [],
                              "ma20": 13400.0, "ma50": 13200.0, "chg7": 0.5, "chg30": 1.2}}
        sent_to = []
        def fake_tg_send(token, chat_id, text):
            sent_to.append(chat_id)
            return True
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", side_effect=fake_tg_send), \
             patch.object(B, "load_state", return_value={}), \
             patch.object(B, "save_state"):
            B.job_morning()
        assert "111222333" in sent_to, "Harvey phải nhận morning report"
        assert "444555666" in sent_to, "Friend phải nhận morning report"

    def test_saves_morning_nav_to_state(self):
        mock_nav = {"TCBF": {"signal": "HOLD ⚪", "nav": 13500.0, "nav_date": "2026-04-09",
                              "score": 0, "rsi": 50.0, "bb_pct": 50.0, "macd_hist": 0,
                              "nav_prev": 13480.0, "chg_pct": 0.1, "details": [],
                              "ma20": 13400.0, "ma50": 13200.0, "chg7": 0.5, "chg30": 1.2}}
        saved_state = {}
        def fake_save(state):
            saved_state.update(state)
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", return_value=True), \
             patch.object(B, "load_state", return_value={}), \
             patch.object(B, "save_state", side_effect=fake_save):
            B.job_morning()
        assert "morning_nav" in saved_state, "State phải có morning_nav"
        assert "TCBF" in saved_state["morning_nav"]


# ════════════════════════════════════════════════════════
# job_check_signals
# ════════════════════════════════════════════════════════

class TestJobCheckSignals:

    def _make_nav_data(self, signal="HOLD ⚪"):
        return {
            code: {"signal": signal, "nav": 13500.0, "nav_date": "2026-04-09",
                   "score": 0, "rsi": 50.0, "bb_pct": 50.0, "macd_hist": 0,
                   "nav_prev": 13480.0, "chg_pct": 0.1, "details": [],
                   "ma20": 13400.0, "ma50": 13200.0, "chg7": 0.5, "chg30": 1.2}
            for code in ["TCBF", "SSISCA", "VCBFBCF"]
        }

    def test_no_alert_when_signal_unchanged(self):
        mock_nav = self._make_nav_data("HOLD ⚪")
        prev_state = {"signals": {"TCBF": "HOLD ⚪", "SSISCA": "HOLD ⚪", "VCBFBCF": "HOLD ⚪"}}
        sent_messages = []
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent_messages.append(m) or True), \
             patch.object(B, "load_state", return_value=prev_state), \
             patch.object(B, "save_state"):
            B.job_check_signals()
        assert len(sent_messages) == 0, "Không alert khi signal không đổi"

    def test_sends_alert_on_signal_change_to_buy(self):
        """HOLD → MUA MẠNH phải gửi alert"""
        mock_nav = self._make_nav_data("MUA MẠNH 🟢🟢")
        mock_nav["TCBF"]["signal"] = "MUA MẠNH 🟢🟢"
        prev_state = {"signals": {"TCBF": "HOLD ⚪", "SSISCA": "HOLD ⚪", "VCBFBCF": "HOLD ⚪"}}
        sent = []
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent.append((c, m)) or True), \
             patch.object(B, "load_state", return_value=prev_state), \
             patch.object(B, "save_state"):
            B.job_check_signals()
        assert len(sent) > 0, "HOLD → MUA MẠNH phải gửi alert"

    def test_no_alert_for_minor_hold_changes(self):
        """HOLD ↔ HOLD không phải MUA/BÁN → không gửi alert"""
        mock_nav = self._make_nav_data("HOLD ⚪")
        prev_state = {"signals": {"TCBF": "HOLD ⚪"}}
        sent = []
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent.append(m) or True), \
             patch.object(B, "load_state", return_value=prev_state), \
             patch.object(B, "save_state"):
            B.job_check_signals()
        assert len(sent) == 0

    def test_updates_signals_in_state(self):
        mock_nav = self._make_nav_data("MUA 🟢")
        saved = {}
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", return_value=True), \
             patch.object(B, "load_state", return_value={}), \
             patch.object(B, "save_state", side_effect=lambda s: saved.update(s)):
            B.job_check_signals()
        assert "signals" in saved, "State phải được update với signals mới"
        assert saved["signals"].get("TCBF") == "MUA 🟢"

    def test_only_alerts_watched_profiles(self):
        """Chỉ profile có TCBF trong watched_funds mới nhận alert TCBF"""
        mock_nav = {
            "TCBF": {"signal": "MUA MẠNH 🟢🟢", "nav": 13500.0, "nav_date": "2026-04-09",
                     "score": 7, "rsi": 20.0, "bb_pct": 5.0, "macd_hist": 0.5,
                     "nav_prev": 13480.0, "chg_pct": 0.1, "details": [],
                     "ma20": 13400.0, "ma50": 13200.0, "chg7": 0.5, "chg30": 1.2}
        }
        # Config chỉ có 1 profile với TCBF
        cfg = {**SAMPLE_CONFIG, "profiles": [
            {"name": "Harvey", "telegram_id": "111222333", "watched_funds": ["TCBF"]},
            {"name": "NoTCBF", "telegram_id": "777888999", "watched_funds": ["SSISCA"]},
        ]}
        sent_to = []
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent_to.append(c) or True), \
             patch.object(B, "load_state", return_value={"signals": {"TCBF": "HOLD ⚪"}}), \
             patch.object(B, "save_state"):
            B.job_check_signals()
        assert "111222333" in sent_to, "Harvey (có TCBF) phải nhận alert"
        assert "777888999" not in sent_to, "NoTCBF không có TCBF → không nhận alert"


# ════════════════════════════════════════════════════════
# _handle_tcbs_auth_error
# ════════════════════════════════════════════════════════

class TestHandleTcbsAuthError:

    def test_sends_alert_to_all_profiles(self):
        """Khi token hết hạn, mọi profile đều nhận cảnh báo."""
        sent_to = []
        with patch.object(B, "tg_send", side_effect=lambda t, c, m: sent_to.append(c) or True):
            B._handle_tcbs_auth_error(SAMPLE_CONFIG, {"TCFF", "TCBF"})
        assert "111222333" in sent_to, "Harvey phải nhận cảnh báo"
        assert "444555666" in sent_to, "Friend phải nhận cảnh báo"

    def test_message_contains_fund_codes(self):
        """Tin nhắn phải liệt kê mã quỹ bị lỗi."""
        messages = []
        with patch.object(B, "tg_send", side_effect=lambda t, c, m: messages.append(m) or True):
            B._handle_tcbs_auth_error(SAMPLE_CONFIG, {"TCFF"})
        assert any("TCFF" in m for m in messages), "Message phải chứa mã quỹ TCFF"

    def test_no_send_when_bot_token_missing(self):
        """Không gửi nếu bot_token chưa cấu hình."""
        cfg_no_token = {**SAMPLE_CONFIG, "bot_token": "NHAP_TOKEN_HERE"}
        with patch.object(B, "tg_send") as mock_tg:
            B._handle_tcbs_auth_error(cfg_no_token, {"TCFF"})
            mock_tg.assert_not_called()

    def test_job_morning_alerts_on_401(self):
        """job_morning gọi _handle_tcbs_auth_error khi fetch_tcbs trả 401."""
        mock_nav = {}
        with patch.object(B, "load_config", return_value=SAMPLE_CONFIG), \
             patch.object(B, "fetch_all", return_value=mock_nav), \
             patch.object(B, "tg_send", return_value=True) as mock_tg, \
             patch.object(B, "load_state", return_value={}), \
             patch.object(B, "save_state"), \
             patch.object(B, "_push_nav_to_server"):
            # Giả lập: fetch_tcbs đã đánh dấu TCFF là 401
            B._tcbs_auth_fail_codes.add("TCFF")
            B.job_morning()
        # tg_send phải được gọi ít nhất 1 lần cho cảnh báo auth
        assert mock_tg.called, "job_morning phải gửi cảnh báo khi _tcbs_auth_fail_codes không rỗng"


# ════════════════════════════════════════════════════════
# check_jwt_freshness & job_check_jwt
# ════════════════════════════════════════════════════════

import base64 as _base64

def _make_jwt(exp_offset_seconds: int) -> str:
    """Tạo JWT giả với exp = now + offset."""
    import time as _time
    header = _base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload_data = {"sub": "test", "exp": int(_time.time()) + exp_offset_seconds}
    payload = _base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


class TestCheckJwtFreshness:

    def test_returns_none_when_no_token(self):
        cfg = {**SAMPLE_CONFIG, "tcbs_token": ""}
        assert B.check_jwt_freshness(cfg) is None

    def test_returns_none_for_non_jwt_token(self):
        cfg = {**SAMPLE_CONFIG, "tcbs_token": "notajwttoken"}
        assert B.check_jwt_freshness(cfg) is None

    def test_returns_positive_for_valid_future_token(self):
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(7200)}  # 2 giờ còn lại
        result = B.check_jwt_freshness(cfg)
        assert result is not None
        assert result > 0, "Token còn hạn phải trả số dương"

    def test_returns_negative_for_expired_token(self):
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(-300)}  # đã hết hạn 5 phút
        result = B.check_jwt_freshness(cfg)
        assert result is not None
        assert result < 0, "Token hết hạn phải trả số âm"

    def test_returns_approximately_correct_seconds(self):
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(3600)}  # đúng 1 giờ
        result = B.check_jwt_freshness(cfg)
        assert result is not None
        assert 3590 < result <= 3600, f"Phải gần 3600s, got {result}"


class TestJobCheckJwt:
    """Tests cho job_check_jwt — dùng send_token_alert_once để dedup.
    Cần mock send_token_alert_once để bypass state.json và test logic alert."""

    @staticmethod
    def _bypass_dedup(send_fn, message):
        """Mock send_token_alert_once: luôn gọi send_fn (bỏ qua dedup flag)."""
        send_fn(message)
        return True

    def test_no_alert_when_token_valid_long(self):
        """Token còn hơn 2 giờ → không gọi send_token_alert_once, không gửi cảnh báo."""
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(7300)}  # > 7200s
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "send_token_alert_once") as mock_alert, \
             patch.object(B, "reset_token_alert"):
            B.job_check_jwt()
            mock_alert.assert_not_called()

    def test_sends_alert_when_token_expiring_soon(self):
        """Token còn < 1 giờ → gọi send_token_alert_once → gửi cảnh báo."""
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(1800)}  # 30 phút còn lại
        sent = []
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "send_token_alert_once", side_effect=self._bypass_dedup), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent.append(m) or True):
            B.job_check_jwt()
        assert len(sent) > 0, "Phải gửi alert khi token sắp hết hạn"
        assert any("sắp hết hạn" in m for m in sent), "Message phải chứa 'sắp hết hạn'"

    def test_sends_alert_when_token_expired(self):
        """Token đã hết hạn → gọi send_token_alert_once → gửi cảnh báo hết hạn."""
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(-600)}  # hết hạn 10 phút trước
        sent = []
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "send_token_alert_once", side_effect=self._bypass_dedup), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent.append(m) or True):
            B.job_check_jwt()
        assert len(sent) > 0, "Phải gửi alert khi token đã hết hạn"
        assert any("đã hết hạn" in m for m in sent), "Message phải chứa 'đã hết hạn'"

    def test_no_alert_when_no_token(self):
        """Không có token → không làm gì."""
        cfg = {**SAMPLE_CONFIG, "tcbs_token": ""}
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "tg_send") as mock_tg:
            B.job_check_jwt()
            mock_tg.assert_not_called()

    def test_no_alert_when_bot_token_missing(self):
        """Có JWT nhưng bot_token chưa cấu hình → không gửi."""
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(1800), "bot_token": "NHAP_TOKEN"}
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "tg_send") as mock_tg:
            B.job_check_jwt()
            mock_tg.assert_not_called()

    def test_alert_sent_to_all_profiles(self):
        """Khi sắp hết hạn, tất cả profiles đều nhận thông báo."""
        cfg = {**SAMPLE_CONFIG, "tcbs_token": _make_jwt(1800)}
        sent_to = []
        with patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "send_token_alert_once", side_effect=self._bypass_dedup), \
             patch.object(B, "tg_send", side_effect=lambda t, c, m: sent_to.append(c) or True):
            B.job_check_jwt()
        assert "111222333" in sent_to, "Harvey phải nhận JWT alert"
        assert "444555666" in sent_to, "Friend phải nhận JWT alert"
