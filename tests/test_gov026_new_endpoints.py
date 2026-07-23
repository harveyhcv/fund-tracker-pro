"""Tests for GOV-026: 4 new API endpoints in miniapp_server.py
- GET /api/history           (unified CCQ+gold trades)
- GET /api/nav_history/<code>?limit=N  (NAV chart data)
- GET /api/gold/price_history/<product> (gold price series)
- GET /api/admin/payments/recent       (admin payment list)
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot"))

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_handler():
    """Instantiate MiniAppHandler with stubbed socket/request/server."""
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
    code, data = handler.responses[-1]
    return code, data


# ── /api/history ─────────────────────────────────────────────────────────────

class TestUnifiedHistory:
    def test_missing_user_id_returns_400(self):
        handler, ms = _make_handler()
        handler._api_unified_history({})
        code, data = _last(handler)
        assert code == 400
        assert "user_id required" in data.get("error", "")

    def test_auth_fail_returns_early(self):
        handler, ms = _make_handler()
        with patch("miniapp_server._auth_write", return_value=False), \
             patch("miniapp_server._qs_tg_id", return_value="123"):
            handler._api_unified_history({"user_id": ["123"]})
        assert not handler.responses  # no response when auth fails

    def test_db_error_returns_500(self):
        handler, ms = _make_handler()
        with patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._qs_tg_id", return_value="123"), \
             patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._get_db_conn", side_effect=Exception("db down")):
            handler._api_unified_history({"user_id": ["123"]})
        code, data = _last(handler)
        assert code == 500
        assert "db down" in data.get("error", "")

    def test_merges_ccq_and_gold(self):
        handler, ms = _make_handler()
        ccq_row = (1, "TCBF", "buy", "2026-07-01", 10.5, 15000.0, 150000, "", False)
        gold_row = (2, "SJC_1L", "buy", "2026-07-02", "luong", 1.0, 1.0, 110000000.0, 110000000, "", "SJC 1 Lượng")
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [[ccq_row], [gold_row]]
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._qs_tg_id", return_value="123"), \
             patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn):
            handler._api_unified_history({"user_id": ["123"]})
        code, data = _last(handler)
        assert code == 200
        trades = data["trades"]
        assert len(trades) == 2
        ccq = next(t for t in trades if t["asset_type"] == "ccq")
        gold = next(t for t in trades if t["asset_type"] == "gold")
        assert ccq["fund_code"] == "TCBF"
        assert ccq["code"] == "TCBF"
        assert gold["product"] == "SJC_1L"
        assert gold["name"] == "SJC 1 Lượng"

    def test_sorted_newest_first(self):
        handler, ms = _make_handler()
        # CCQ older, Gold newer
        ccq_row = (1, "TCBF", "buy", "2026-06-01", 10.0, 15000.0, 150000, "", False)
        gold_row = (2, "SJC_1L", "buy", "2026-07-15", "luong", 1.0, 1.0, 100000000.0, 100000000, "", "")
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [[ccq_row], [gold_row]]
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._qs_tg_id", return_value="123"), \
             patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn):
            handler._api_unified_history({"user_id": ["123"]})
        _, data = _last(handler)
        dates = [t["date"] for t in data["trades"]]
        assert dates == sorted(dates, reverse=True)

    def test_empty_result(self):
        handler, ms = _make_handler()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [[], []]
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server._qs_tg_id", return_value="123"), \
             patch("miniapp_server._init_trade_tables"), \
             patch("miniapp_server._get_db_conn", return_value=mock_conn):
            handler._api_unified_history({"user_id": ["123"]})
        code, data = _last(handler)
        assert code == 200
        assert data["trades"] == []


# ── /api/nav_history/<code> ───────────────────────────────────────────────────

class TestNavHistoryChart:
    def test_invalid_code_returns_400(self):
        handler, ms = _make_handler()
        handler._api_nav_history_chart("", {})
        code, data = _last(handler)
        assert code == 400

    def test_code_too_long_returns_400(self):
        handler, ms = _make_handler()
        handler._api_nav_history_chart("A" * 20, {})
        code, data = _last(handler)
        assert code == 400

    def test_no_db_url_returns_503(self):
        handler, ms = _make_handler()
        with patch.dict("os.environ", {}, clear=True), \
             patch("miniapp_server._load_cfg", return_value={}):
            handler._api_nav_history_chart("TCBF", {})
        code, data = _last(handler)
        assert code == 503

    def test_returns_history_oldest_first(self):
        handler, ms = _make_handler()
        rows = [("2026-07-10", 15500.0), ("2026-07-09", 15400.0), ("2026-07-08", 15300.0)]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = rows
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        import psycopg2
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_nav_history_chart("TCBF", {"limit": ["3"]})
        code, data = _last(handler)
        assert code == 200
        assert data["code"] == "TCBF"
        # rows returned newest-first from DB, reversed in response → oldest-first
        history = data["history"]
        assert len(history) == 3
        assert history[0]["date"] == "2026-07-08"
        assert history[-1]["date"] == "2026-07-10"

    def test_default_limit_365(self):
        handler, ms = _make_handler()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_nav_history_chart("TCBF", {})
        # verify LIMIT param passed is 365
        call_args = mock_cur.execute.call_args
        assert call_args[0][1][1] == 365

    def test_limit_clamped_to_3650(self):
        handler, ms = _make_handler()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_nav_history_chart("TCBF", {"limit": ["99999"]})
        call_args = mock_cur.execute.call_args
        assert call_args[0][1][1] == 3650

    def test_db_error_returns_500(self):
        handler, ms = _make_handler()
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", side_effect=Exception("conn fail")):
            handler._api_nav_history_chart("TCBF", {})
        code, data = _last(handler)
        assert code == 500


# ── /api/gold/price_history/<product> ────────────────────────────────────────

class TestGoldPriceHistory:
    def test_empty_product_returns_400(self):
        handler, ms = _make_handler()
        handler._api_gold_price_history("")
        code, data = _last(handler)
        assert code == 400

    def test_no_db_url_returns_503(self):
        handler, ms = _make_handler()
        with patch.dict("os.environ", {}, clear=True), \
             patch("miniapp_server._load_cfg", return_value={}):
            handler._api_gold_price_history("SJC_1L")
        code, data = _last(handler)
        assert code == 503

    def test_returns_history_with_price(self):
        handler, ms = _make_handler()
        rows = [("2026-07-08", 110000000.0), ("2026-07-09", 111000000.0)]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = rows
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_gold_price_history("SJC_1L")
        code, data = _last(handler)
        assert code == 200
        assert data["product"] == "SJC_1L"
        assert len(data["history"]) == 2
        assert data["history"][0] == {"date": "2026-07-08", "price": 110000000.0}

    def test_unknown_product_returns_empty_history(self):
        handler, ms = _make_handler()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_gold_price_history("Nhẫn 1 chỉ")
        code, data = _last(handler)
        assert code == 200
        assert data["history"] == []

    def test_db_error_returns_500(self):
        handler, ms = _make_handler()
        with patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", side_effect=Exception("timeout")):
            handler._api_gold_price_history("SJC_1L")
        code, data = _last(handler)
        assert code == 500


# ── /api/admin/payments/recent ───────────────────────────────────────────────

class TestAdminPaymentsRecent:
    def test_non_admin_returns_403(self):
        handler, ms = _make_handler()
        with patch("miniapp_server._is_admin", return_value=False):
            handler._api_admin_payments_recent({"user_id": ["999"]})
        code, data = _last(handler)
        assert code == 403
        assert "admin_only" in data.get("error", "")

    def test_auth_fail_returns_early(self):
        handler, ms = _make_handler()
        with patch("miniapp_server._is_admin", return_value=True), \
             patch("miniapp_server._auth_write", return_value=False):
            handler._api_admin_payments_recent({"user_id": ["admin"]})
        assert not handler.responses

    def test_no_db_url_returns_empty(self):
        handler, ms = _make_handler()
        with patch("miniapp_server._is_admin", return_value=True), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch.dict("os.environ", {}, clear=True), \
             patch("miniapp_server._load_cfg", return_value={}):
            handler._api_admin_payments_recent({"user_id": ["admin"]})
        code, data = _last(handler)
        assert code == 200
        assert data["payments"] == []

    def test_returns_merged_payments(self):
        handler, ms = _make_handler()
        sepay_rows = [
            ("100", "m1", 20000.0, "paid", "2026-07-20T10:00:00", "Harvey"),
        ]
        other_rows = [
            ("200", "stars", "2026-07-19T09:00:00", "Bob"),
        ]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [sepay_rows, other_rows]
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._is_admin", return_value=True), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_admin_payments_recent({"user_id": ["admin"]})
        code, data = _last(handler)
        assert code == 200
        payments = data["payments"]
        assert len(payments) == 2
        sepay = next(p for p in payments if p["method"] == "sepay")
        stars = next(p for p in payments if p["method"] == "stars")
        assert sepay["name"] == "Harvey"
        assert sepay["plan"] == "m1"
        assert stars["name"] == "Bob"
        assert stars["status"] == "paid"

    def test_sorted_newest_first(self):
        handler, ms = _make_handler()
        sepay_rows = [("100", "m1", 20000.0, "paid", "2026-07-15T10:00:00", "A")]
        other_rows = [("200", "stars", "2026-07-20T10:00:00", "B")]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [sepay_rows, other_rows]
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._is_admin", return_value=True), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_admin_payments_recent({"user_id": ["admin"]})
        _, data = _last(handler)
        dates = [p["created_at"] for p in data["payments"]]
        assert dates == sorted(dates, reverse=True)

    def test_db_error_returns_500(self):
        handler, ms = _make_handler()
        with patch("miniapp_server._is_admin", return_value=True), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", side_effect=Exception("db error")):
            handler._api_admin_payments_recent({"user_id": ["admin"]})
        code, data = _last(handler)
        assert code == 500

    def test_limits_to_50(self):
        handler, ms = _make_handler()
        # 35 sepay + 35 other → should return only 50
        sepay_rows = [(str(i), "m1", 20000.0, "paid", f"2026-07-{i:02d}T10:00:00", f"U{i}") for i in range(1, 36)]
        other_rows = [(str(100+i), "stars", f"2026-08-{i:02d}T10:00:00", f"V{i}") for i in range(1, 36)]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [sepay_rows, other_rows]
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch("miniapp_server._is_admin", return_value=True), \
             patch("miniapp_server._auth_write", return_value=True), \
             patch("miniapp_server.os.environ", {"DATABASE_URL": "postgresql://fake"}), \
             patch("psycopg2.connect", return_value=mock_conn):
            handler._api_admin_payments_recent({"user_id": ["admin"]})
        _, data = _last(handler)
        assert len(data["payments"]) == 50
