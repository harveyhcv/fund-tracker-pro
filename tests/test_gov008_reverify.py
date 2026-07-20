"""
test_gov008_reverify.py — GOV-008: NAV 3-layer re-verification.

Bao phủ reverify_nav_tier(): tất cả nhánh trả về
'skip' / 'corrected' / 'upgraded' / 'unchanged'.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

import db as D


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

_CODE = "TCBF"
_NAV_DATE = date(2026, 7, 10)
_STORED_NAV = 20000.0


def _make_conn(stored_nav=_STORED_NAV, source="tcinvest", cur_tier=0):
    """Fake DB conn + cursor trả row (stored_nav, source, tier)."""
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (stored_nav, source, cur_tier)

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn, cur


def _today_at(days_ahead: int = 5):
    """Trả date cách _NAV_DATE `days_ahead` ngày."""
    return _NAV_DATE + timedelta(days=days_ahead)


# ──────────────────────────────────────────────────────────────────────
# Skip cases
# ──────────────────────────────────────────────────────────────────────

class TestReverifyNavTierSkip:
    def test_skip_when_db_unavailable(self):
        with patch.object(D, "is_available", return_value=False):
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, _STORED_NAV)
        assert result == "skip"

    def test_skip_when_nav_date_is_today(self):
        today = date.today()
        with patch.object(D, "is_available", return_value=True), \
             patch("db.date") as mock_date:
            mock_date.today.return_value = today
            result = D.reverify_nav_tier(_CODE, today, _STORED_NAV)
        assert result == "skip"

    def test_skip_when_row_not_found(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = None
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(5)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, _STORED_NAV)
        assert result == "skip"

    def test_skip_when_source_is_fmarket(self):
        conn, cur = _make_conn(source="fmarket")
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(5)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, _STORED_NAV)
        assert result == "skip"

    def test_skip_when_source_is_fixed(self):
        conn, cur = _make_conn(source="fixed")
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(5)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, _STORED_NAV)
        assert result == "skip"

    def test_skip_when_source_is_manual(self):
        conn, cur = _make_conn(source="manual")
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(2)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, _STORED_NAV)
        assert result == "skip"


# ──────────────────────────────────────────────────────────────────────
# Corrected (TCBS tự sửa lại, lệch > tolerance)
# ──────────────────────────────────────────────────────────────────────

class TestReverifyNavTierCorrected:
    def _run_corrected(self, stored_nav, fresh_nav, cur_tier=0, days=5):
        conn, cur = _make_conn(stored_nav=stored_nav, cur_tier=cur_tier)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "log_audit") as mock_audit, \
             patch.object(D, "_update_nav_row_hash") as mock_hash, \
             patch.object(D, "_log_nav_verification") as mock_log, \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(days)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, fresh_nav)
        return result, mock_audit, mock_hash, mock_log

    def test_returns_corrected_when_diff_above_tolerance(self):
        # Lệch 1% >> tolerance 0.05%
        fresh = _STORED_NAV * 1.01
        result, _, _, _ = self._run_corrected(_STORED_NAV, fresh)
        assert result == "corrected"

    def test_corrected_logs_audit_with_correct_action(self):
        fresh = _STORED_NAV * 1.01
        result, mock_audit, _, _ = self._run_corrected(_STORED_NAV, fresh)
        mock_audit.assert_called_once()
        args = mock_audit.call_args[0]
        assert args[1] == "nav_reverify_corrected"

    def test_corrected_calls_update_row_hash(self):
        fresh = _STORED_NAV * 1.01
        result, _, mock_hash, _ = self._run_corrected(_STORED_NAV, fresh)
        mock_hash.assert_called_once_with(_CODE, _NAV_DATE)

    def test_corrected_logs_nav_verification_with_corrected_status(self):
        fresh = _STORED_NAV * 1.01
        result, _, _, mock_log = self._run_corrected(_STORED_NAV, fresh)
        mock_log.assert_called_once()
        # arg thứ 4 là result_status = "corrected"
        assert mock_log.call_args[0][4] == "corrected"

    def test_not_corrected_when_diff_exactly_at_tolerance(self):
        # tolerance = 0.05% — lệch đúng 0.05% coi là "khớp"
        fresh = _STORED_NAV * (1 + D.NAV_VERIFY_TOLERANCE_PCT / 100)
        result, _, _, _ = self._run_corrected(_STORED_NAV, fresh)
        # diff_pct = 0.05 → KHÔNG vượt tolerance → không corrected
        assert result != "corrected"


# ──────────────────────────────────────────────────────────────────────
# Upgraded (khớp, đủ tuổi để lên tier cao hơn)
# ──────────────────────────────────────────────────────────────────────

class TestReverifyNavTierUpgraded:
    def _run_match(self, cur_tier, days, fresh_nav=_STORED_NAV):
        conn, cur = _make_conn(cur_tier=cur_tier)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "log_audit"), \
             patch.object(D, "_update_nav_row_hash") as mock_hash, \
             patch.object(D, "_log_nav_verification") as mock_log, \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(days)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, fresh_nav)
        return result, mock_hash, mock_log

    def test_upgraded_tier0_to_1_after_1_day(self):
        result, _, _ = self._run_match(cur_tier=0, days=1)
        assert result == "upgraded"

    def test_upgraded_tier1_to_8_after_8_days(self):
        result, _, _ = self._run_match(cur_tier=1, days=8)
        assert result == "upgraded"

    def test_upgraded_tier8_to_31_after_31_days(self):
        result, _, _ = self._run_match(cur_tier=8, days=31)
        assert result == "upgraded"

    def test_upgraded_tier0_to_31_directly_after_31_days(self):
        # Bỏ qua luôn tier1 và tier8 nếu đã đủ 31 ngày
        result, _, _ = self._run_match(cur_tier=0, days=31)
        assert result == "upgraded"

    def test_upgraded_calls_update_row_hash(self):
        result, mock_hash, _ = self._run_match(cur_tier=0, days=5)
        assert result == "upgraded"
        mock_hash.assert_called_once_with(_CODE, _NAV_DATE)

    def test_upgraded_logs_verification_with_upgraded_status(self):
        result, _, mock_log = self._run_match(cur_tier=0, days=5)
        assert result == "upgraded"
        mock_log.assert_called_once()
        assert mock_log.call_args[0][4] == "upgraded"


# ──────────────────────────────────────────────────────────────────────
# Unchanged (khớp nhưng đã max tier hoặc chưa đủ tuổi)
# ──────────────────────────────────────────────────────────────────────

class TestReverifyNavTierUnchanged:
    def _run_match(self, cur_tier, days):
        conn, cur = _make_conn(cur_tier=cur_tier)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "log_audit"), \
             patch.object(D, "_update_nav_row_hash") as mock_hash, \
             patch.object(D, "_log_nav_verification") as mock_log, \
             patch("db.date") as mock_date:
            mock_date.today.return_value = _today_at(days)
            result = D.reverify_nav_tier(_CODE, _NAV_DATE, _STORED_NAV)
        return result, mock_hash, mock_log

    def test_unchanged_when_already_at_max_tier(self):
        # Tier 31 là max — không cần nâng thêm
        result, _, _ = self._run_match(cur_tier=31, days=50)
        assert result == "unchanged"

    def test_unchanged_when_tier1_but_only_5_days(self):
        # Cần 8 ngày để lên tier 8, hiện mới 5 ngày
        result, _, _ = self._run_match(cur_tier=1, days=5)
        assert result == "unchanged"

    def test_unchanged_does_not_update_hash(self):
        result, mock_hash, _ = self._run_match(cur_tier=31, days=50)
        assert result == "unchanged"
        mock_hash.assert_not_called()

    def test_unchanged_logs_verification_with_unchanged_status(self):
        result, _, mock_log = self._run_match(cur_tier=31, days=50)
        assert result == "unchanged"
        mock_log.assert_called_once()
        assert mock_log.call_args[0][4] == "unchanged"
