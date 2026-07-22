"""
test_gov025_admin_users.py — GOV-025: get_admin_users() + GET /api/admin/users.

Bao phủ:
- DB unavailable → []
- Không có search → trả tất cả (limit 100)
- Search bằng telegram_id (số)
- Search bằng tên (ILIKE)
- Kết quả đúng kiểu (telegram_id int, trade_count int, is_admin bool)
- Quỹ không có tier row → default 'free'
- Quỹ không có trade → trade_count=0
"""
from unittest.mock import MagicMock, patch, call

import pytest

import db as D


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_row(telegram_id=1001, name="Alice", tier="pro", is_admin=False, trade_count=3, created_at="2026-01-01"):
    return {
        "telegram_id": telegram_id,
        "name": name,
        "tier": tier,
        "is_admin": is_admin,
        "trade_count": trade_count,
        "created_at": created_at,
    }


def _make_conn(rows):
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = rows

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn, cur


# ──────────────────────────────────────────────────────────────────────
# DB unavailable
# ──────────────────────────────────────────────────────────────────────

class TestGetAdminUsersUnavailable:
    def test_returns_empty_list_when_db_unavailable(self):
        with patch.object(D, "is_available", return_value=False):
            result = D.get_admin_users()
        assert result == []

    def test_returns_empty_list_with_query_when_unavailable(self):
        with patch.object(D, "is_available", return_value=False):
            result = D.get_admin_users(q="Harvey")
        assert result == []


# ──────────────────────────────────────────────────────────────────────
# Happy path — no search
# ──────────────────────────────────────────────────────────────────────

class TestGetAdminUsersNoSearch:
    def test_returns_all_users_when_no_query(self):
        rows = [_make_row(1001, "Alice", "pro", False, 5), _make_row(1002, "Bob", "free", False, 0)]
        conn, cur = _make_conn(rows)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            result = D.get_admin_users()
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"

    def test_result_fields_correct_types(self):
        rows = [_make_row(1001, "Alice", "pro", True, 7, "2026-01-15")]
        conn, cur = _make_conn(rows)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            result = D.get_admin_users()
        u = result[0]
        assert isinstance(u["telegram_id"], int)
        assert isinstance(u["is_admin"], bool)
        assert isinstance(u["trade_count"], int)
        assert u["telegram_id"] == 1001
        assert u["is_admin"] is True
        assert u["trade_count"] == 7
        assert u["tier"] == "pro"

    def test_no_tier_row_defaults_to_free(self):
        rows = [_make_row(1001, "Alice", "free", False, 0)]
        conn, cur = _make_conn(rows)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            result = D.get_admin_users()
        assert result[0]["tier"] == "free"

    def test_no_trades_returns_zero_count(self):
        rows = [_make_row(1001, "Alice", "free", False, 0)]
        conn, cur = _make_conn(rows)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            result = D.get_admin_users()
        assert result[0]["trade_count"] == 0

    def test_empty_db_returns_empty_list(self):
        conn, cur = _make_conn([])
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            result = D.get_admin_users()
        assert result == []


# ──────────────────────────────────────────────────────────────────────
# Search — bằng telegram_id (q là số)
# ──────────────────────────────────────────────────────────────────────

class TestGetAdminUsersSearchById:
    def test_search_by_numeric_id_uses_exact_match(self):
        rows = [_make_row(9999, "Harvey", "pro", True, 12)]
        conn, cur = _make_conn(rows)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            result = D.get_admin_users(q="9999")
        # SQL phải chứa WHERE telegram_id = %s (không phải ILIKE)
        executed_sql = cur.execute.call_args[0][0]
        assert "telegram_id = %s" in executed_sql
        assert "ILIKE" not in executed_sql

    def test_search_by_numeric_id_converts_to_int(self):
        rows = [_make_row(9999, "Harvey", "pro", True, 12)]
        conn, cur = _make_conn(rows)
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            D.get_admin_users(q="9999")
        params = cur.execute.call_args[0][1]
        assert params[0] == 9999  # phải là int, không phải string

    def test_negative_id_treated_as_numeric(self):
        """telegram_id âm (BETA mode user) cũng tìm được bằng exact match."""
        conn, cur = _make_conn([])
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            D.get_admin_users(q="-12345")
        executed_sql = cur.execute.call_args[0][0]
        assert "telegram_id = %s" in executed_sql
        params = cur.execute.call_args[0][1]
        assert params[0] == -12345


# ──────────────────────────────────────────────────────────────────────
# Search — bằng tên (q là chuỗi)
# ──────────────────────────────────────────────────────────────────────

class TestGetAdminUsersSearchByName:
    def test_search_by_name_uses_ilike(self):
        conn, cur = _make_conn([])
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            D.get_admin_users(q="Harvey")
        executed_sql = cur.execute.call_args[0][0]
        assert "ILIKE" in executed_sql
        assert "telegram_id = %s" not in executed_sql

    def test_search_by_name_wraps_with_percent(self):
        conn, cur = _make_conn([])
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            D.get_admin_users(q="Harvey")
        params = cur.execute.call_args[0][1]
        assert params[0] == "%Harvey%"

    def test_search_strips_whitespace_from_query(self):
        conn, cur = _make_conn([])
        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=conn), \
             patch.object(D, "_ensure_bot_profiles_table"), \
             patch.object(D, "_ensure_user_tiers_table"):
            D.get_admin_users(q="  Harvey  ")
        params = cur.execute.call_args[0][1]
        assert params[0] == "%Harvey%"  # stripped, not "  Harvey  "
