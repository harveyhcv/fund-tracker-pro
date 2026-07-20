"""
test_gov015_web_auth.py — GOV-015: Telegram Login Widget + web session token.

Bao phủ:
  - _verify_telegram_login_widget(): xác thực payload widget, chống replay
  - _issue_web_session() + _verify_web_session(): vòng đời session token
"""
import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

# conftest.py đã thêm telegram-bot/ vào sys.path
import miniapp_server as M


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

_BOT_TOKEN = "testtoken123"
_SESSION_SECRET = "super-secret-session-key-for-tests"


def _make_widget_hash(data: dict, bot_token: str) -> str:
    """Tính hash hợp lệ cho Telegram Login Widget payload."""
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()


def _valid_widget_payload(
    tg_id: int = 12345,
    first_name: str = "Harvey",
    age_seconds: int = 0,
    bot_token: str = _BOT_TOKEN,
) -> dict:
    """Tạo payload Login Widget hợp lệ, mặc định fresh (age=0)."""
    data = {
        "id": tg_id,
        "first_name": first_name,
        "auth_date": int(time.time()) - age_seconds,
    }
    payload = dict(data)
    payload["hash"] = _make_widget_hash(data, bot_token)
    return payload


# ──────────────────────────────────────────────────────────────────────
# _verify_telegram_login_widget
# ──────────────────────────────────────────────────────────────────────

class TestVerifyTelegramLoginWidget:
    def test_returns_none_for_empty_payload(self):
        assert M._verify_telegram_login_widget({}, _BOT_TOKEN) is None

    def test_returns_none_for_none_payload(self):
        assert M._verify_telegram_login_widget(None, _BOT_TOKEN) is None  # type: ignore

    def test_returns_none_for_empty_bot_token(self):
        payload = _valid_widget_payload()
        assert M._verify_telegram_login_widget(payload, "") is None

    def test_returns_none_when_hash_missing(self):
        payload = _valid_widget_payload()
        del payload["hash"]
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None

    def test_returns_none_for_wrong_hash(self):
        payload = _valid_widget_payload()
        payload["hash"] = "deadbeef" * 8
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None

    def test_returns_none_for_hash_with_wrong_bot_token(self):
        payload = _valid_widget_payload(bot_token="wrong_token")
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None

    def test_returns_none_when_auth_date_too_old(self):
        # 24h + 1s — hết hạn replay protection
        payload = _valid_widget_payload(age_seconds=M._LOGIN_WIDGET_MAX_AGE_SECONDS + 1)
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None

    def test_returns_none_when_auth_date_too_far_future(self):
        # Vài giờ trong tương lai — dấu hiệu clock sai hoặc giả mạo
        skew = M._INIT_DATA_CLOCK_SKEW_SECONDS + 60
        payload = _valid_widget_payload(age_seconds=-skew)
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None

    def test_returns_user_dict_for_valid_fresh_payload(self):
        payload = _valid_widget_payload()
        result = M._verify_telegram_login_widget(payload, _BOT_TOKEN)
        assert result is not None
        assert result["id"] == 12345
        assert result["first_name"] == "Harvey"

    def test_returns_user_dict_when_just_before_expiry(self):
        # Payload từ gần đúng ngưỡng 24h — vẫn hợp lệ
        payload = _valid_widget_payload(age_seconds=M._LOGIN_WIDGET_MAX_AGE_SECONDS - 10)
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is not None

    def test_tampered_field_invalidates_hash(self):
        payload = _valid_widget_payload()
        payload["first_name"] = "Attacker"  # hash đã ký first_name=Harvey
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None

    def test_returns_none_when_auth_date_invalid_type(self):
        payload = _valid_widget_payload()
        payload["auth_date"] = "not_a_number"
        # Phải tính lại hash vì auth_date thay đổi
        data_no_hash = {k: v for k, v in payload.items() if k != "hash"}
        payload["hash"] = _make_widget_hash(data_no_hash, _BOT_TOKEN)
        assert M._verify_telegram_login_widget(payload, _BOT_TOKEN) is None


# ──────────────────────────────────────────────────────────────────────
# _issue_web_session + _verify_web_session
# ──────────────────────────────────────────────────────────────────────

class TestWebSessionIssueAndVerify:
    def test_roundtrip_returns_telegram_id(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            token = M._issue_web_session("99001")
            result = M._verify_web_session(token)
        assert result == "99001"

    def test_returns_none_for_empty_token(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            assert M._verify_web_session("") is None

    def test_returns_none_when_secret_not_set(self):
        # _WEB_SESSION_SECRET chưa được set → server chưa config xác thực Web
        with patch.object(M, "_WEB_SESSION_SECRET", ""):
            token = f"99001.{int(time.time()) + 3600}.fakesig"
            assert M._verify_web_session(token) is None

    def test_returns_none_for_tampered_telegram_id(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            token = M._issue_web_session("99001")
            parts = token.split(".", 2)
            parts[0] = "99999"  # đổi tg_id → sig không còn khớp
            tampered = ".".join(parts)
            assert M._verify_web_session(tampered) is None

    def test_returns_none_for_tampered_expiry(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            token = M._issue_web_session("99001")
            parts = token.split(".", 2)
            parts[1] = str(int(parts[1]) + 999999)  # kéo dài thời hạn → sig lệch
            tampered = ".".join(parts)
            assert M._verify_web_session(tampered) is None

    def test_returns_none_for_expired_token(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            # Giả lập token đã hết hạn (expiry trong quá khứ)
            expiry = int(time.time()) - 1  # 1s trước
            body = f"99001.{expiry}"
            sig = hmac.new(_SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
            token = f"{body}.{sig}"
            assert M._verify_web_session(token) is None

    def test_returns_none_for_wrong_segment_count(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            assert M._verify_web_session("only.two") is None

    def test_returns_none_when_signed_with_different_secret(self):
        with patch.object(M, "_WEB_SESSION_SECRET", "secret-A"):
            token = M._issue_web_session("99001")
        with patch.object(M, "_WEB_SESSION_SECRET", "secret-B"):
            assert M._verify_web_session(token) is None

    def test_different_tg_ids_produce_different_tokens(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            t1 = M._issue_web_session("111")
            t2 = M._issue_web_session("222")
        assert t1 != t2

    def test_token_format_is_three_dot_segments(self):
        with patch.object(M, "_WEB_SESSION_SECRET", _SESSION_SECRET):
            token = M._issue_web_session("12345")
        parts = token.split(".")
        assert len(parts) == 3
        assert parts[0] == "12345"
        assert int(parts[1]) > int(time.time())  # expiry ở tương lai
        assert len(parts[2]) == 64  # SHA-256 hex = 64 ký tự
