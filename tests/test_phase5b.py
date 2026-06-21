"""
test_phase5b.py — QA cho Phase 5B:
  • crypto.py (AES-256-GCM layer)
  • /add-trade command (DB + encryption)
  • /portfolio DB path (decrypt holdings → P&L)
  • job_backfill_settlement (T+1/T+3 NAV fill)
"""

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# conftest.py đã thêm telegram-bot/ vào sys.path
import bot as B
import crypto as C

# ══════════════════════════════════════════════════════════════
# CONSTANTS & HELPERS
# ══════════════════════════════════════════════════════════════

CRYPTO_OK = C.is_available()

_MASTER_KEY = b"test_master_key__32bytes_exactly"   # 32 bytes
_USER_KEY   = b"test_user_key____32bytes_exactly!"  # 32 bytes
_USER_UUID  = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_PORT_UUID  = "11111111-2222-3333-4444-555555555555"

SAMPLE_CONFIG = {
    "bot_token": "123456:TEST",
    "admin_telegram_id": "999000",
    "profiles": [
        {"name": "Harvey", "telegram_id": "111222333", "watched_funds": ["TCBF", "SSISCA"]},
    ],
    "funds": {
        "TCBF":   {"name": "Quỹ Trái Phiếu Techcombank", "fmarket_id": 22},
        "SSISCA": {"name": "Quỹ Tích Lũy Bền Vững SSI",  "fmarket_id": 11},
    },
    "schedule": {"morning_report": "08:00", "evening_report": "17:30",
                 "signal_check_interval_minutes": 60},
}

NAV_STUB = {
    "TCBF": {"nav": 15000, "signal": "MUA", "nav_date": "2026-06-20",
             "rsi": 35.0, "bb_pct": 20.0, "score": 4,
             "chg7": 0.5, "chg30": 1.2, "ma20": 14800, "ma50": 14500},
}


def make_update(text, chat_id="111222333"):
    return {
        "update_id": 1,
        "message": {"chat": {"id": int(chat_id), "first_name": "Harvey"}, "text": text},
    }


def _mock_db():
    """Preconfigured DB mock — every call succeeds by default."""
    db = MagicMock()
    db.is_available.return_value = True
    db.get_user_info.return_value = {"id": _USER_UUID, "enc_salt": b"s" * 32}
    db.get_or_create_user.return_value = _USER_UUID
    db.get_or_create_portfolio.return_value = _PORT_UUID
    db.get_portfolio_id.return_value = _PORT_UUID
    db.add_transaction.return_value = "tx-uuid-001"
    db.get_holdings_raw.return_value = []
    db.upsert_holding.return_value = None
    db.get_pending_backfill.return_value = []
    db.get_nav_on_or_after.return_value = None
    db.backfill_settlement_nav.return_value = None
    return db


def _mock_crypto():
    """Preconfigured crypto mock — all crypto ops return fixed bytes."""
    cr = MagicMock()
    cr.is_available.return_value = True
    cr.get_master_key.return_value = _MASTER_KEY
    cr.derive_user_key.return_value = _USER_KEY
    cr.make_auth_hash.return_value = b"h" * 32
    cr.encrypt_decimal.return_value = b"\x00" * 28   # 12 nonce + data + 16 tag
    cr.decrypt_decimal.return_value = 1000.0
    cr.encrypt_str.return_value = b"\x00" * 20
    return cr


def run_command(text, chat_id="111222333", config=None, db=None, crypto=None):
    """Giả lập 1 lần getUpdates trong command_handler, rồi thoát bằng KeyboardInterrupt."""
    cfg = config or SAMPLE_CONFIG
    db  = db     or _mock_db()
    cr  = crypto or _mock_crypto()
    cnt = [0]
    sent = []

    def fake_get(url, **kw):
        cnt[0] += 1
        if cnt[0] == 1:
            return MagicMock(ok=True, json=lambda: {"result": [make_update(text, chat_id)]})
        raise KeyboardInterrupt

    def fake_post(url, **kw):
        m = MagicMock(ok=True)
        if "sendMessage" in url:
            sent.append(kw.get("json", {}).get("text", ""))
        return m

    with patch("bot.load_config", return_value=cfg), \
         patch("requests.get", side_effect=fake_get), \
         patch("requests.post", side_effect=fake_post), \
         patch.object(B, "_DB_AVAILABLE",     True), \
         patch.object(B, "_CRYPTO_AVAILABLE", True), \
         patch.object(B, "_db",     db, create=True), \
         patch.object(B, "_crypto", cr, create=True):
        try:
            B.command_handler()
        except KeyboardInterrupt:
            pass

    return sent, db, cr


# ══════════════════════════════════════════════════════════════
# TestCrypto — Pure unit tests for crypto.py
# ══════════════════════════════════════════════════════════════

class TestCrypto:
    def test_is_available_reflects_lib_installation(self):
        import importlib.util
        installed = importlib.util.find_spec("cryptography") is not None
        assert C.is_available() == installed

    def test_get_master_key_none_without_env(self, monkeypatch):
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        assert C.get_master_key() is None

    def test_get_master_key_strips_whitespace(self, monkeypatch):
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        # Blank (spaces only) should also return None
        monkeypatch.setenv("ENCRYPTION_KEY", "   ")
        assert C.get_master_key() is None

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_get_master_key_returns_32_bytes(self, monkeypatch):
        monkeypatch.setenv("ENCRYPTION_KEY", "my-secret-key-123")
        key = C.get_master_key()
        assert isinstance(key, bytes) and len(key) == 32

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_get_master_key_deterministic(self, monkeypatch):
        monkeypatch.setenv("ENCRYPTION_KEY", "same-input")
        assert C.get_master_key() == C.get_master_key()

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_get_master_key_different_inputs_different_keys(self, monkeypatch):
        monkeypatch.setenv("ENCRYPTION_KEY", "input-A")
        k1 = C.get_master_key()
        monkeypatch.setenv("ENCRYPTION_KEY", "input-B")
        k2 = C.get_master_key()
        assert k1 != k2

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_derive_user_key_returns_32_bytes(self):
        key = C.derive_user_key(b"mk" * 16, os.urandom(32))
        assert isinstance(key, bytes) and len(key) == 32

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_derive_user_key_deterministic(self):
        mk   = b"master_key_______32bytes_exactly"
        salt = b"fixed_salt_here_16bytes_exactly!"
        assert C.derive_user_key(mk, salt) == C.derive_user_key(mk, salt)

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_derive_user_key_different_salts_give_different_keys(self):
        mk = b"master_key_______32bytes_exactly"
        k1 = C.derive_user_key(mk, b"salt-A" * 6)
        k2 = C.derive_user_key(mk, b"salt-B" * 6)
        assert k1 != k2

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_make_auth_hash_returns_32_bytes(self):
        h = C.make_auth_hash(123456789, b"mk" * 16)
        assert isinstance(h, bytes) and len(h) == 32

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_make_auth_hash_deterministic(self):
        mk = b"mk" * 16
        assert C.make_auth_hash(111, mk) == C.make_auth_hash(111, mk)

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_make_auth_hash_different_ids_give_different_hashes(self):
        mk = b"mk" * 16
        assert C.make_auth_hash(111, mk) != C.make_auth_hash(222, mk)

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_encrypt_decrypt_roundtrip(self):
        key = os.urandom(32)
        plaintext = b"hello fund tracker pro"
        assert C.decrypt(C.encrypt(plaintext, key), key) == plaintext

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_encrypt_random_nonces_produce_different_ciphertexts(self):
        key = os.urandom(32)
        ct1 = C.encrypt(b"same data", key)
        ct2 = C.encrypt(b"same data", key)
        assert ct1 != ct2   # different 12-byte nonces

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_decrypt_tampered_ciphertext_raises(self):
        from cryptography.exceptions import InvalidTag
        key = os.urandom(32)
        ct = bytearray(C.encrypt(b"data", key))
        ct[-1] ^= 0xFF   # flip last byte of GCM tag
        with pytest.raises(InvalidTag):
            C.decrypt(bytes(ct), key)

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_encrypt_output_minimum_length(self):
        key = os.urandom(32)
        ct = C.encrypt(b"a", key)
        assert len(ct) >= 12 + 1 + 16   # nonce + 1 byte data + GCM tag

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_encrypt_decrypt_decimal_roundtrip(self):
        key = os.urandom(32)
        for val in [0.0, 1.0, 12345.678901, 1_000_000.123456]:
            assert abs(C.decrypt_decimal(C.encrypt_decimal(val, key), key) - val) < 1e-5

    @pytest.mark.skipif(not CRYPTO_OK, reason="cryptography not installed")
    def test_encrypt_decrypt_str_unicode(self):
        key = os.urandom(32)
        for s in ["Harvey", "Xin chào", "TCBF 1,000 CCQ"]:
            assert C.decrypt_str(C.encrypt_str(s, key), key) == s


# ══════════════════════════════════════════════════════════════
# TestAddTradeCommand — /add-trade via command_handler
# ══════════════════════════════════════════════════════════════

class TestAddTradeCommand:
    def test_unregistered_user_gets_register_prompt(self):
        msgs, _, _ = run_command("/add-trade TCBF buy 100 1500000", chat_id="000000000")
        assert any("đăng ký" in m for m in msgs)

    def test_no_args_shows_usage(self):
        msgs, _, _ = run_command("/add-trade")
        assert msgs
        assert any("Cú pháp" in m or "buy" in m for m in msgs)

    def test_too_few_args_shows_usage(self):
        # Missing amount arg
        msgs, _, _ = run_command("/add-trade TCBF buy 100")
        assert msgs
        assert any("Cú pháp" in m or "buy" in m for m in msgs)

    def test_invalid_fund_code_shows_error(self):
        msgs, _, _ = run_command("/add-trade INVALID buy 100 1500000")
        assert any("INVALID" in m for m in msgs)

    def test_invalid_tx_type_shows_error(self):
        msgs, _, _ = run_command("/add-trade TCBF transfer 100 1500000")
        assert any("buy" in m and "sell" in m for m in msgs)

    def test_zero_units_shows_error(self):
        msgs, _, _ = run_command("/add-trade TCBF buy 0 1500000")
        assert any("dương" in m or "Số CCQ" in m for m in msgs)

    def test_negative_amount_shows_error(self):
        msgs, _, _ = run_command("/add-trade TCBF buy 100 -500")
        assert any("dương" in m or "Số CCQ" in m for m in msgs)

    def test_invalid_date_format_shows_error(self):
        msgs, _, _ = run_command("/add-trade TCBF buy 100 1500000 14/06/2026")
        assert any("ngày" in m.lower() or "date" in m.lower() or "Ngày" in m for m in msgs)

    def test_db_unavailable_shows_error(self):
        db = _mock_db()
        db.is_available.return_value = False
        msgs, _, _ = run_command("/add-trade TCBF buy 100 1500000", db=db)
        assert any("database" in m.lower() or "kết nối" in m.lower() for m in msgs)

    def test_no_encryption_key_shows_error(self):
        cr = _mock_crypto()
        cr.get_master_key.return_value = None
        msgs, _, _ = run_command("/add-trade TCBF buy 100 1500000", crypto=cr)
        assert any("ENCRYPTION_KEY" in m or "ncryption" in m for m in msgs)

    def test_buy_success_calls_add_transaction(self):
        db = _mock_db()
        _, db_after, _ = run_command("/add-trade TCBF buy 1000.5 15007500", db=db)
        db_after.add_transaction.assert_called_once()
        kw = db_after.add_transaction.call_args.kwargs
        assert kw["fund_code"] == "TCBF"
        assert kw["tx_type"] == "buy"

    def test_buy_success_sends_confirmation_message(self):
        msgs, _, _ = run_command("/add-trade TCBF buy 1000 15000000")
        assert any("TCBF" in m for m in msgs)
        assert any("Mua" in m or "giao dịch" in m.lower() for m in msgs)

    def test_sell_success_calls_add_transaction(self):
        db = _mock_db()
        _, db_after, _ = run_command("/add-trade TCBF sell 200 3000000", db=db)
        db_after.add_transaction.assert_called_once()
        kw = db_after.add_transaction.call_args.kwargs
        assert kw["tx_type"] == "sell"

    def test_buy_calls_upsert_holding_after_transaction(self):
        db = _mock_db()
        _, db_after, _ = run_command("/add-trade TCBF buy 500 7500000", db=db)
        db_after.upsert_holding.assert_called_once()

    def test_date_defaults_to_today_when_omitted(self):
        db = _mock_db()
        _, db_after, _ = run_command("/add-trade TCBF buy 100 1500000", db=db)
        kw = db_after.add_transaction.call_args.kwargs
        assert kw["order_date"] == date.today()

    def test_explicit_date_is_passed_through(self):
        db = _mock_db()
        _, db_after, _ = run_command("/add-trade TCBF buy 100 1500000 2026-01-15", db=db)
        kw = db_after.add_transaction.call_args.kwargs
        assert kw["order_date"] == date(2026, 1, 15)

    def test_nav_at_order_computed_as_amount_over_units(self):
        # 15_000_000 / 1000 = 15_000.0
        db = _mock_db()
        _, db_after, _ = run_command("/add-trade TCBF buy 1000 15000000", db=db)
        kw = db_after.add_transaction.call_args.kwargs
        assert kw["nav_at_order"] == pytest.approx(15000.0, rel=1e-4)

    def test_buy_with_existing_holding_updates_weighted_avg(self):
        db = _mock_db()
        db.get_holdings_raw.return_value = [
            {"fund_code": "TCBF", "units_enc": b"\x00" * 28, "avg_cost_enc": b"\x00" * 28},
        ]
        cr = _mock_crypto()
        # First decrypt call = prev_units (500), second = prev_avg (14000)
        cr.decrypt_decimal.side_effect = [500.0, 14000.0]
        _, db_after, _ = run_command("/add-trade TCBF buy 1000 15000000", db=db, crypto=cr)
        # Should still call upsert_holding (with new weighted avg)
        db_after.upsert_holding.assert_called_once()


# ══════════════════════════════════════════════════════════════
# TestPortfolioDbPath — /portfolio sử dụng DB holdings
# ══════════════════════════════════════════════════════════════

class TestPortfolioDbPath:
    def test_unregistered_user_gets_register_prompt(self):
        msgs, _, _ = run_command("/portfolio", chat_id="000000000")
        assert any("đăng ký" in m for m in msgs)

    def test_portfolio_uses_db_holdings_when_available(self):
        db = _mock_db()
        db.get_holdings_raw.return_value = [
            {"fund_code": "TCBF", "units_enc": b"\x00" * 28, "avg_cost_enc": b"\x00" * 28},
        ]
        cr = _mock_crypto()
        cr.decrypt_decimal.side_effect = [1000.0, 14000.0]  # units, avg_cost

        with patch.object(B, "fetch_all", return_value=NAV_STUB):
            msgs, _, _ = run_command("/portfolio", db=db, crypto=cr)

        assert any("TCBF" in m for m in msgs)
        assert any("1,000" in m or "1000" in m for m in msgs)

    def test_portfolio_db_shows_pnl(self):
        # units=1000 CCQ, avg_cost=14000, nav=15000 → P&L = +1,000,000
        db = _mock_db()
        db.get_holdings_raw.return_value = [
            {"fund_code": "TCBF", "units_enc": b"\x00" * 28, "avg_cost_enc": b"\x00" * 28},
        ]
        cr = _mock_crypto()
        cr.decrypt_decimal.side_effect = [1000.0, 14000.0]

        with patch.object(B, "fetch_all", return_value=NAV_STUB):
            msgs, _, _ = run_command("/portfolio", db=db, crypto=cr)

        joined = " ".join(msgs)
        assert "Lãi" in joined or "lãi" in joined

    def test_portfolio_fallback_when_user_not_in_db(self):
        db = _mock_db()
        db.get_user_info.return_value = None   # user not registered in DB

        with patch.object(B, "fetch_all", return_value={}):
            msgs, _, _ = run_command("/portfolio", db=db)

        assert msgs   # fallback path returns something

    def test_portfolio_fallback_when_no_db_holdings(self):
        db = _mock_db()
        db.get_holdings_raw.return_value = []  # portfolio exists but empty

        with patch.object(B, "fetch_all", return_value={}):
            msgs, _, _ = run_command("/portfolio", db=db)

        assert msgs   # fallback path returns something

    def test_portfolio_fallback_when_no_portfolio_in_db(self):
        db = _mock_db()
        db.get_portfolio_id.return_value = None  # user exists but no portfolio

        with patch.object(B, "fetch_all", return_value={}):
            msgs, _, _ = run_command("/portfolio", db=db)

        assert msgs


# ══════════════════════════════════════════════════════════════
# TestBackfillJob — job_backfill_settlement
# ══════════════════════════════════════════════════════════════

class TestBackfillJob:
    def _run_backfill(self, db):
        with patch.object(B, "_DB_AVAILABLE", True), \
             patch.object(B, "_db", db, create=True):
            B.job_backfill_settlement()

    def test_skips_when_db_not_available(self):
        db = _mock_db()
        db.is_available.return_value = False
        self._run_backfill(db)
        db.get_pending_backfill.assert_not_called()

    def test_skips_when_db_flag_false(self):
        db = _mock_db()
        with patch.object(B, "_DB_AVAILABLE", False), \
             patch.object(B, "_db", db, create=True):
            B.job_backfill_settlement()
        db.get_pending_backfill.assert_not_called()

    def test_no_pending_signals_does_nothing(self):
        db = _mock_db()
        db.get_pending_backfill.return_value = []
        self._run_backfill(db)
        db.backfill_settlement_nav.assert_not_called()

    def test_queries_with_todays_date(self):
        db = _mock_db()
        self._run_backfill(db)
        db.get_pending_backfill.assert_called_once_with(date.today())

    def test_fills_signal_when_nav_found(self):
        db = _mock_db()
        db.get_pending_backfill.return_value = [{
            "fund_code": "TCBF",
            "signal_date": date(2026, 6, 15),
            "est_exec_date": date(2026, 6, 17),
            "settlement_rule": "T2",
        }]
        db.get_nav_on_or_after.return_value = 15000.0
        self._run_backfill(db)
        db.backfill_settlement_nav.assert_called_once_with("TCBF", date(2026, 6, 15), 15000.0)

    def test_skips_signal_when_nav_not_found(self):
        db = _mock_db()
        db.get_pending_backfill.return_value = [{
            "fund_code": "TCBF",
            "signal_date": date(2026, 6, 15),
            "est_exec_date": date(2026, 6, 17),
            "settlement_rule": "T2",
        }]
        db.get_nav_on_or_after.return_value = None
        self._run_backfill(db)
        db.backfill_settlement_nav.assert_not_called()

    def test_handles_multiple_signals_partial_nav(self):
        db = _mock_db()
        db.get_pending_backfill.return_value = [
            {"fund_code": "TCBF",   "signal_date": date(2026, 6, 10),
             "est_exec_date": date(2026, 6, 12), "settlement_rule": "T2"},
            {"fund_code": "SSISCA", "signal_date": date(2026, 6, 11),
             "est_exec_date": date(2026, 6, 13), "settlement_rule": "T2"},
        ]
        db.get_nav_on_or_after.side_effect = [14500.0, None]  # TCBF found, SSISCA not
        self._run_backfill(db)
        assert db.backfill_settlement_nav.call_count == 1
        db.backfill_settlement_nav.assert_called_once_with("TCBF", date(2026, 6, 10), 14500.0)

    def test_continues_after_backfill_db_error(self):
        db = _mock_db()
        db.get_pending_backfill.return_value = [
            {"fund_code": "TCBF",   "signal_date": date(2026, 6, 10),
             "est_exec_date": date(2026, 6, 12), "settlement_rule": "T2"},
            {"fund_code": "SSISCA", "signal_date": date(2026, 6, 11),
             "est_exec_date": date(2026, 6, 13), "settlement_rule": "T2"},
        ]
        db.get_nav_on_or_after.return_value = 15000.0
        db.backfill_settlement_nav.side_effect = [Exception("DB error"), None]
        # Must not raise — second signal should still be attempted
        self._run_backfill(db)
        assert db.backfill_settlement_nav.call_count == 2

    def test_passes_correct_fund_code_to_nav_lookup(self):
        db = _mock_db()
        db.get_pending_backfill.return_value = [{
            "fund_code": "SSISCA",
            "signal_date": date(2026, 6, 1),
            "est_exec_date": date(2026, 6, 3),
            "settlement_rule": "T2",
        }]
        self._run_backfill(db)
        db.get_nav_on_or_after.assert_called_once_with("SSISCA", date(2026, 6, 3))
