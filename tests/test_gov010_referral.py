"""
test_gov010_referral.py — GOV-010: grant_referral_purchase_bonus() — giai đoạn 2 referral.

Logic: sau khi referee thanh toán thật lần đầu, cấp REFERRAL_PURCHASE_BONUS_DAYS
cho CẢ referrer lẫn referee. Idempotent, ban-aware.
"""
from unittest.mock import MagicMock, patch, call

import pytest

import db as D


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

_REFEREE_ID   = 11111
_REFERRER_ID  = 22222
_CODE         = "REF-HARVEY"
_REDEMPTION_ID = 99


def _make_referral_row(referrer_id=_REFERRER_ID):
    return {"id": _REDEMPTION_ID, "code": _CODE, "referrer_id": referrer_id}


def _make_conn(fetchone_result):
    """Fake conn + cursor. Hỗ trợ RealDictCursor pattern (cursor_factory kwarg bị ignore)."""
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = fetchone_result

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn, cur


# ──────────────────────────────────────────────────────────────────────
# Cases trả về None (không cấp bonus)
# ──────────────────────────────────────────────────────────────────────

class TestGrantReferralPurchaseBonusNoBonus:
    def test_returns_none_when_no_referral_found(self):
        conn, cur = _make_conn(fetchone_result=None)
        with patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_promo_tables"):
            result = D.grant_referral_purchase_bonus(_REFEREE_ID)
        assert result is None

    def test_returns_none_when_referrer_id_is_none(self):
        row = {"id": _REDEMPTION_ID, "code": _CODE, "referrer_id": None}
        conn, cur = _make_conn(fetchone_result=row)
        with patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_promo_tables"):
            result = D.grant_referral_purchase_bonus(_REFEREE_ID)
        assert result is None

    def test_returns_none_when_referee_is_banned(self):
        conn, cur = _make_conn(fetchone_result=_make_referral_row())

        def _is_banned_fn(tg_id):
            return int(tg_id) == _REFEREE_ID  # referee bị ban

        with patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_promo_tables"), \
             patch.object(D, "is_banned", side_effect=_is_banned_fn), \
             patch.object(D, "log_audit") as mock_audit, \
             patch.object(D, "extend_pro") as mock_extend:
            result = D.grant_referral_purchase_bonus(_REFEREE_ID)

        assert result is None
        mock_extend.assert_not_called()
        # Phải ghi audit "blocked"
        mock_audit.assert_called_once()
        args = mock_audit.call_args[0]
        assert "blocked" in args[1]

    def test_returns_none_when_referrer_is_banned(self):
        conn, cur = _make_conn(fetchone_result=_make_referral_row())

        def _is_banned_fn(tg_id):
            return int(tg_id) == _REFERRER_ID  # referrer bị ban

        with patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_promo_tables"), \
             patch.object(D, "is_banned", side_effect=_is_banned_fn), \
             patch.object(D, "log_audit") as mock_audit, \
             patch.object(D, "extend_pro") as mock_extend:
            result = D.grant_referral_purchase_bonus(_REFEREE_ID)

        assert result is None
        mock_extend.assert_not_called()
        mock_audit.assert_called_once()
        args = mock_audit.call_args[0]
        assert "blocked" in args[1]


# ──────────────────────────────────────────────────────────────────────
# Happy path — cấp bonus cho cả 2 bên
# ──────────────────────────────────────────────────────────────────────

class TestGrantReferralPurchaseBonusHappyPath:
    def _run_happy(self, actor_id=None):
        conn, cur = _make_conn(fetchone_result=_make_referral_row())
        with patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_promo_tables"), \
             patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "extend_pro") as mock_extend, \
             patch.object(D, "log_audit") as mock_audit:
            result = D.grant_referral_purchase_bonus(_REFEREE_ID, actor_id=actor_id)
        return result, mock_extend, mock_audit

    def test_returns_correct_dict_on_success(self):
        result, _, _ = self._run_happy()
        assert result is not None
        assert result["referee"] == _REFEREE_ID
        assert result["referrer"] == _REFERRER_ID
        assert result["days_each"] == D.REFERRAL_PURCHASE_BONUS_DAYS

    def test_calls_extend_pro_for_both_parties(self):
        result, mock_extend, _ = self._run_happy()
        assert mock_extend.call_count == 2
        # referee
        calls_tg_ids = {c.args[0] for c in mock_extend.call_args_list}
        assert _REFEREE_ID in calls_tg_ids
        assert _REFERRER_ID in calls_tg_ids

    def test_extend_pro_uses_correct_bonus_days(self):
        result, mock_extend, _ = self._run_happy()
        for c in mock_extend.call_args_list:
            assert c.args[1] == D.REFERRAL_PURCHASE_BONUS_DAYS

    def test_logs_audit_after_granting(self):
        result, _, mock_audit = self._run_happy()
        mock_audit.assert_called_once()
        args = mock_audit.call_args[0]
        assert args[1] == "referral.purchase_bonus"

    def test_passes_actor_id_to_extend_pro(self):
        result, mock_extend, _ = self._run_happy(actor_id=99)
        for c in mock_extend.call_args_list:
            assert c.kwargs.get("actor_id") == 99 or 99 in (c.args + tuple(c.kwargs.values()))

    def test_marks_redemption_bonus_at_in_db(self):
        conn, cur = _make_conn(fetchone_result=_make_referral_row())
        with patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_promo_tables"), \
             patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "extend_pro"), \
             patch.object(D, "log_audit"):
            D.grant_referral_purchase_bonus(_REFEREE_ID)
        # cur.execute gọi lần 2 phải là UPDATE (lần 1 là SELECT)
        calls = cur.execute.call_args_list
        # SELECT có "FOR UPDATE" nên lọc bằng "SET" để phân biệt UPDATE thật
        update_calls = [c for c in calls if "SET" in str(c.args[0])]
        assert len(update_calls) >= 1
        assert str(_REDEMPTION_ID) in str(update_calls[0])
