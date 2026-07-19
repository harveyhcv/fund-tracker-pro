"""
test_gov017_discount.py — GOV-017: gộp Mã Promo + Voucher thành 1 loại mã duy nhất.
Tests cho redeem_instant_discount_code() và validation create_discount_code().
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

import db as D


def _fake_conn(fetchone_result=None, inserted=True):
    """Trả fake context-manager conn + cursor cho các test."""
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = fetchone_result

    # ON CONFLICT DO NOTHING: nếu inserted=False thì fetchone trả None (duplicate)
    # Dùng side_effect để fetchone() trả row lần 1 (SELECT), rồi None/id lần 2 (INSERT)
    fetch_results = [fetchone_result, {"id": 1} if inserted else None]
    cur.fetchone.side_effect = fetch_results

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn, cur


def _active_row(requires_purchase=False, benefit_type="bonus_days", benefit_value=30,
                active=True, uses_count=0, max_uses=None, valid_from=None, valid_until=None):
    return {
        "code": "FREE30",
        "requires_purchase": requires_purchase,
        "benefit_type": benefit_type,
        "benefit_value": benefit_value,
        "active": active,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "uses_count": uses_count,
        "max_uses": max_uses,
    }


class TestRedeemInstantDiscountCode:
    def test_empty_code_returns_error(self):
        result = D.redeem_instant_discount_code("", 12345)
        assert result["ok"] is False
        assert "nhập mã" in result["error"]

    def test_whitespace_code_returns_error(self):
        result = D.redeem_instant_discount_code("   ", 12345)
        assert result["ok"] is False

    def test_banned_user_blocked(self):
        with patch.object(D, "is_banned", return_value=True):
            result = D.redeem_instant_discount_code("FREE30", 99)
        assert result["ok"] is False
        assert "khoá" in result["error"]

    def test_code_not_found_returns_error(self):
        conn, cur = _fake_conn(fetchone_result=None)
        cur.fetchone.side_effect = None
        cur.fetchone.return_value = None
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"):
            result = D.redeem_instant_discount_code("NOTEXIST", 12345)
        assert result["ok"] is False
        assert "không tồn tại" in result["error"]

    def test_requires_purchase_true_returns_error(self):
        row = _active_row(requires_purchase=True, benefit_type="discount_pct", benefit_value=10)
        conn, cur = _fake_conn(fetchone_result=row)
        cur.fetchone.side_effect = [row]  # chỉ SELECT
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"):
            result = D.redeem_instant_discount_code("DISC10", 12345)
        assert result["ok"] is False
        assert "cần mua hàng" in result["error"]

    def test_expired_code_returns_error(self):
        row = _active_row(requires_purchase=False, benefit_type="bonus_days",
                          valid_until=datetime(2020, 1, 1, tzinfo=timezone.utc))
        conn, cur = _fake_conn(fetchone_result=row)
        cur.fetchone.side_effect = [row]
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"):
            result = D.redeem_instant_discount_code("FREE30", 12345)
        assert result["ok"] is False
        assert "hết hạn" in result["error"]

    def test_max_uses_exhausted_returns_error(self):
        row = _active_row(requires_purchase=False, uses_count=5, max_uses=5)
        conn, cur = _fake_conn(fetchone_result=row)
        cur.fetchone.side_effect = [row]
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"):
            result = D.redeem_instant_discount_code("FREE30", 12345)
        assert result["ok"] is False
        assert "hết hạn" in result["error"] or "hết lượt" in result["error"]

    def test_first_redeem_success_extends_pro(self):
        row = _active_row(requires_purchase=False, benefit_type="bonus_days", benefit_value=30)
        conn, cur = _fake_conn(fetchone_result=row, inserted=True)
        cur.fetchone.side_effect = [row, {"id": 1}]  # SELECT → INSERT RETURNING
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"), \
             patch.object(D, "extend_pro") as mock_extend, \
             patch.object(D, "log_audit"):
            result = D.redeem_instant_discount_code("FREE30", 12345)
        assert result["ok"] is True
        assert result["kind"] == "instant_discount"
        assert result["days"] == 30
        mock_extend.assert_called_once_with(12345, 30, actor_id=12345, note="redeem mã FREE30 (không cần mua)")

    def test_duplicate_redeem_returns_error(self):
        row = _active_row(requires_purchase=False, benefit_type="bonus_days", benefit_value=30)
        conn, cur = _fake_conn(fetchone_result=row, inserted=False)
        cur.fetchone.side_effect = [row, None]  # SELECT → INSERT conflict → RETURNING None
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"), \
             patch.object(D, "extend_pro") as mock_extend, \
             patch.object(D, "log_audit"):
            result = D.redeem_instant_discount_code("FREE30", 12345)
        assert result["ok"] is False
        assert "đã sử dụng" in result["error"]
        mock_extend.assert_not_called()

    def test_order_ref_uses_instant_prefix(self):
        """Xác nhận order_ref format 'INSTANT-<code>-<tg_id>' để đảm bảo idempotency."""
        row = _active_row(requires_purchase=False, benefit_type="bonus_days", benefit_value=7)
        conn, cur = _fake_conn()
        cur.fetchone.side_effect = [row, {"id": 99}]
        insert_calls = []

        def capture_execute(sql, params=None):
            if params and "INSTANT" in str(params):
                insert_calls.append(params)

        cur.execute.side_effect = capture_execute
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"), \
             patch.object(D, "extend_pro"), \
             patch.object(D, "log_audit"):
            D.redeem_instant_discount_code("FREE7", 99999)

        assert any("INSTANT-FREE7-99999" in str(p) for p in insert_calls)

    def test_code_normalized_to_uppercase(self):
        """Mã nhập thường phải được chuẩn hoá thành HOA trước khi tra cứu."""
        row = _active_row(requires_purchase=False, benefit_type="bonus_days", benefit_value=14)
        conn, cur = _fake_conn()
        cur.fetchone.side_effect = [row, {"id": 1}]
        executed_codes = []

        def capture(sql, params=None):
            if params and len(params) == 1 and isinstance(params[0], str):
                executed_codes.append(params[0])

        cur.execute.side_effect = capture
        with patch.object(D, "is_banned", return_value=False), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_discount_tables"), \
             patch.object(D, "extend_pro"), \
             patch.object(D, "log_audit"):
            D.redeem_instant_discount_code("free14", 55)

        assert "FREE14" in executed_codes


class TestCreateDiscountCodeValidation:
    """GOV-017: create_discount_code() phải reject combination không hợp lệ."""

    def test_requires_purchase_false_with_discount_pct_raises(self):
        with pytest.raises(ValueError, match="không thể giảm giá"):
            D.create_discount_code(
                benefit_type="discount_pct",
                benefit_value=10,
                auto_apply=False,
                requires_purchase=False,
                created_by=1,
            )

    def test_requires_purchase_false_with_auto_apply_raises(self):
        with pytest.raises(ValueError, match="tự động áp dụng"):
            D.create_discount_code(
                benefit_type="bonus_days",
                benefit_value=30,
                auto_apply=True,
                requires_purchase=False,
                created_by=1,
            )

    def test_invalid_benefit_type_raises(self):
        with pytest.raises(ValueError, match="benefit_type"):
            D.create_discount_code(
                benefit_type="free_upgrade",
                benefit_value=1,
                auto_apply=False,
                requires_purchase=True,
                created_by=1,
            )
