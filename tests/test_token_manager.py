"""
test_token_manager.py — Unit tests cho scripts/token_manager.py
Functions: decode_jwt_exp, check_token
"""
import sys, json, base64, time
from pathlib import Path
from unittest.mock import patch, MagicMock

# Thêm scripts/ vào path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import token_manager as TM


# ── JWT helpers ─────────────────────────────────────────────────────────────

def _make_jwt(exp: int) -> str:
    """Tạo JWT giả với exp timestamp cho test."""
    header  = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "sub": "test"}).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesignature"


def _make_config(token: str = "") -> dict:
    return {"tcbs_token": token, "bot_token": "TEST_BOT", "profiles": []}


# ════════════════════════════════════════════════════════
# decode_jwt_exp
# ════════════════════════════════════════════════════════

class TestDecodeJwtExp:

    def test_valid_jwt_returns_exp(self):
        future_exp = int(time.time()) + 3600
        jwt = _make_jwt(future_exp)
        result = TM.decode_jwt_exp(jwt)
        assert result == future_exp

    def test_invalid_jwt_returns_none(self):
        assert TM.decode_jwt_exp("not.a.jwt.at.all") is None

    def test_empty_string_returns_none(self):
        assert TM.decode_jwt_exp("") is None

    def test_only_two_parts_returns_none(self):
        assert TM.decode_jwt_exp("header.payload") is None

    def test_bad_base64_returns_none(self):
        assert TM.decode_jwt_exp("hdr.!!!invalid!!!.sig") is None

    def test_payload_without_exp_returns_none(self):
        payload = base64.urlsafe_b64encode(b'{"sub":"test"}').rstrip(b"=").decode()
        jwt = f"header.{payload}.sig"
        result = TM.decode_jwt_exp(jwt)
        assert result is None


# ════════════════════════════════════════════════════════
# check_token
# ════════════════════════════════════════════════════════

class TestCheckToken:

    def _patch_config(self, token: str = ""):
        return patch.object(TM, "load_config", return_value=_make_config(token))

    def test_missing_token_returns_missing_status(self):
        with self._patch_config(""):
            result = TM.check_token(alert=False)
        assert result["status"] == "missing"
        assert result["remaining_minutes"] == 0

    def test_invalid_jwt_returns_unreadable(self):
        with self._patch_config("not_a_jwt"):
            result = TM.check_token(alert=False)
        assert result["status"] == "unreadable"

    def test_expired_token_returns_expired(self):
        past_exp = int(time.time()) - 3600  # đã hết hạn 1 giờ trước
        jwt = _make_jwt(past_exp)
        with self._patch_config(jwt):
            result = TM.check_token(alert=False)
        assert result["status"] == "expired"
        assert result["remaining_minutes"] < 0

    def test_critical_token_under_1h(self):
        near_exp = int(time.time()) + 1800  # còn 30 phút
        jwt = _make_jwt(near_exp)
        with self._patch_config(jwt):
            result = TM.check_token(alert=False)
        assert result["status"] == "critical"
        assert 25 <= result["remaining_minutes"] <= 35

    def test_warning_token_1h_to_2h(self):
        warn_exp = int(time.time()) + 5400  # còn 90 phút
        jwt = _make_jwt(warn_exp)
        with self._patch_config(jwt):
            result = TM.check_token(alert=False)
        assert result["status"] == "warning"

    def test_ok_token_over_2h(self):
        good_exp = int(time.time()) + 7200 + 60  # còn hơn 2 giờ
        jwt = _make_jwt(good_exp)
        with self._patch_config(jwt):
            result = TM.check_token(alert=False)
        assert result["status"] == "ok"

    def test_result_contains_exp_key(self):
        good_exp = int(time.time()) + 3600 * 5
        jwt = _make_jwt(good_exp)
        with self._patch_config(jwt):
            result = TM.check_token(alert=False)
        assert "exp" in result
        assert result["exp"] == good_exp

    def test_no_alert_called_when_ok(self):
        good_exp = int(time.time()) + 3600 * 5
        jwt = _make_jwt(good_exp)
        with self._patch_config(jwt), \
             patch.object(TM, "_send_alert") as mock_alert:
            TM.check_token(alert=True)
            mock_alert.assert_not_called()

    def test_alert_called_when_expired(self):
        past_exp = int(time.time()) - 100
        jwt = _make_jwt(past_exp)
        with self._patch_config(jwt), \
             patch.object(TM, "_send_alert") as mock_alert:
            TM.check_token(alert=True)
            mock_alert.assert_called_once()

    def test_no_alert_when_alert_false(self):
        past_exp = int(time.time()) - 100
        jwt = _make_jwt(past_exp)
        with self._patch_config(jwt), \
             patch.object(TM, "_send_alert") as mock_alert:
            TM.check_token(alert=False)
            mock_alert.assert_not_called()
