"""Tests for GOV-028: _api_edit_gold_trade now persists `name` column.

Before fix: SELECT did not include `name`; UPDATE did not set `name`.
Frontend sends {name: ...} but backend read `note` → name lost on every edit.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot"))


def _make_handler():
    import miniapp_server as ms
    handler = ms.MiniAppHandler.__new__(ms.MiniAppHandler)
    handler.responses = []
    handler.headers = {}

    def fake_json(h, data, code=200):
        h.responses.append((code, data))

    import miniapp_server
    miniapp_server._json = fake_json
    return handler, ms


def _last(handler):
    return handler.responses[-1]


def _mock_conn(existing_row):
    """Build a mock DB conn that returns existing_row on SELECT and accepts UPDATE."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = existing_row
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


# Row layout: (telegram_id, unit, qty, price_per_luong, total_vnd,
#              trade_date, type, note, name)   ← 9 columns after fix
_EXISTING_ROW = ("123", "luong", 2.0, 95000000.0, 190000000, "2026-07-01", "buy", "", "SJC 1 Lượng")


class TestEditGoldTradeName:

    def test_invalid_idx_returns_400(self):
        handler, _ = _make_handler()
        handler._api_edit_gold_trade("abc", {})
        code, data = _last(handler)
        assert code == 400
        assert "Invalid id" in data.get("error", "")

    def test_missing_trade_returns_404(self):
        handler, _ = _make_handler()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn):
            handler._api_edit_gold_trade("99", {})
        code, data = _last(handler)
        assert code == 404

    def test_name_sent_by_frontend_is_saved(self):
        """Frontend sends name:note (JS variable) → backend must UPDATE name column."""
        handler, ms = _make_handler()
        mock_conn, mock_cur = _mock_conn(_EXISTING_ROW)

        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn), \
             patch("miniapp_server._db_mod", None):
            handler._api_edit_gold_trade("1", {
                "telegram_id": "123",
                "type": "buy",
                "unit": "luong",
                "qty": 2.0,
                "price_per_luong": 95000000.0,
                "total_vnd": 190000000,
                "date": "2026-07-01",
                "name": "SJC Đặc Biệt",   # frontend sends this
            })
        code, data = _last(handler)
        assert code == 200
        assert data.get("ok") is True

        # Verify UPDATE call includes name column
        update_calls = [c for c in mock_cur.execute.call_args_list
                        if "UPDATE" in str(c.args[0]) and "SET" in str(c.args[0])]
        assert update_calls, "No UPDATE call found"
        update_sql = str(update_calls[0].args[0])
        assert "name=%s" in update_sql, "name column not in UPDATE"
        # Verify value in params
        params = update_calls[0].args[1]
        assert "SJC Đặc Biệt" in params, f"New name not in params: {params}"

    def test_name_falls_back_to_existing_when_not_sent(self):
        """When frontend omits name field, existing DB name is preserved."""
        handler, ms = _make_handler()
        mock_conn, mock_cur = _mock_conn(_EXISTING_ROW)

        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn), \
             patch("miniapp_server._db_mod", None):
            handler._api_edit_gold_trade("1", {
                "telegram_id": "123",
                "type": "buy",
                "unit": "luong",
                "qty": 2.0,
                "price_per_luong": 96000000.0,  # changed price
                "date": "2026-07-01",
                # name NOT sent → should fall back to existing row[8] = "SJC 1 Lượng"
            })
        code, _ = _last(handler)
        assert code == 200

        update_calls = [c for c in mock_cur.execute.call_args_list
                        if "UPDATE" in str(c.args[0]) and "SET" in str(c.args[0])]
        params = update_calls[0].args[1]
        assert "SJC 1 Lượng" in params, f"Existing name not preserved in params: {params}"

    def test_name_truncated_to_100_chars(self):
        """name field is capped at 100 characters (same as create endpoint)."""
        handler, ms = _make_handler()
        mock_conn, mock_cur = _mock_conn(_EXISTING_ROW)
        long_name = "A" * 200

        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn), \
             patch("miniapp_server._db_mod", None):
            handler._api_edit_gold_trade("1", {
                "telegram_id": "123",
                "type": "buy",
                "unit": "luong",
                "qty": 2.0,
                "price_per_luong": 95000000.0,
                "date": "2026-07-01",
                "name": long_name,
            })
        update_calls = [c for c in mock_cur.execute.call_args_list
                        if "UPDATE" in str(c.args[0]) and "SET" in str(c.args[0])]
        params = update_calls[0].args[1]
        saved_name = next(p for p in params if isinstance(p, str) and len(p) <= 100 and p.startswith("A"))
        assert len(saved_name) == 100

    def test_audit_log_includes_name(self):
        """Audit log before/after dicts include name field for traceability."""
        handler, ms = _make_handler()
        mock_conn, mock_cur = _mock_conn(_EXISTING_ROW)
        mock_db = MagicMock()

        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn), \
             patch("miniapp_server._db_mod", mock_db):
            handler._api_edit_gold_trade("1", {
                "telegram_id": "123",
                "type": "buy",
                "unit": "luong",
                "qty": 2.0,
                "price_per_luong": 95000000.0,
                "date": "2026-07-01",
                "name": "DOJI 1 Lượng",
            })

        assert mock_db.log_audit.called, "log_audit not called"
        call_kwargs = mock_db.log_audit.call_args
        before = call_kwargs.kwargs.get("before") or call_kwargs[1].get("before", {})
        after  = call_kwargs.kwargs.get("after")  or call_kwargs[1].get("after",  {})
        assert "name" in before, f"'name' missing from audit before: {before}"
        assert "name" in after,  f"'name' missing from audit after: {after}"
        assert after["name"] == "DOJI 1 Lượng"

    def test_select_includes_name_column(self):
        """SELECT query must fetch name column (row[8]) for fallback logic."""
        handler, ms = _make_handler()
        mock_conn, mock_cur = _mock_conn(_EXISTING_ROW)

        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn), \
             patch("miniapp_server._db_mod", None):
            handler._api_edit_gold_trade("1", {"telegram_id": "123", "qty": 2.0,
                                               "price_per_luong": 95000000.0, "date": "2026-07-01"})

        select_calls = [c for c in mock_cur.execute.call_args_list
                        if "SELECT" in str(c.args[0])]
        assert select_calls, "No SELECT call found"
        select_sql = str(select_calls[0].args[0])
        assert "name" in select_sql, f"name not in SELECT: {select_sql}"

    def test_db_error_on_update_returns_500(self):
        """DB failure during UPDATE returns 500, not crash."""
        handler, _ = _make_handler()
        mock_conn1 = MagicMock()
        mock_cur1 = MagicMock()
        mock_cur1.fetchone.return_value = _EXISTING_ROW
        mock_conn1.cursor.return_value.__enter__ = lambda s: mock_cur1
        mock_conn1.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn2 = MagicMock()
        mock_cur2 = MagicMock()
        mock_cur2.execute.side_effect = Exception("update failed")
        mock_conn2.cursor.return_value.__enter__ = lambda s: mock_cur2
        mock_conn2.cursor.return_value.__exit__ = MagicMock(return_value=False)

        conns = [mock_conn1, mock_conn2]
        with patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._get_db_conn", side_effect=conns), \
             patch("miniapp_server._db_mod", None):
            handler._api_edit_gold_trade("1", {
                "telegram_id": "123", "qty": 2.0,
                "price_per_luong": 95000000.0, "date": "2026-07-01",
            })
        code, data = _last(handler)
        assert code == 500
        assert "update failed" in data.get("error", "")
