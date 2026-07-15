"""
test_nav_source_audit.py — Tự động hoá quy trình cross-check NAV source
(BACKLOG GOV-007-part3): db.get_nav_source_audit() + bot.job_nav_source_audit().
"""
from unittest.mock import MagicMock, patch

import pytest

# conftest.py đã thêm telegram-bot/ vào sys.path
import bot as B
import db as D


def _mock_db():
    db = MagicMock()
    db.is_available.return_value = True
    return db


class TestGetNavSourceAudit:
    def test_returns_empty_list_when_db_unavailable(self):
        with patch.object(D, "is_available", return_value=False):
            assert D.get_nav_source_audit(days=30) == []

    def test_returns_flagged_rows_from_query(self):
        fake_rows = [
            {"fund_code": "VCBFTBF", "untrusted_count": 5,
             "sources_seen": ["fmarket"], "sample_dates": ["2026-07-13", "2026-07-12"]},
        ]
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = fake_rows
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.__exit__.return_value = False

        fake_conn = MagicMock()
        fake_conn.cursor.return_value = fake_cursor
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False

        with patch.object(D, "is_available", return_value=True), \
             patch.object(D, "get_conn", return_value=fake_conn):
            result = D.get_nav_source_audit(days=30)

        assert result == fake_rows
        # source != ALL(%s) phải dùng đúng TRUSTED_SOURCES, không hardcode lại
        params = fake_cursor.execute.call_args[0][1]
        assert params[0] == 30
        assert set(params[1]) == set(D.TRUSTED_SOURCES)


class TestJobNavSourceAudit:
    def _run(self, db, config=None):
        cfg = config or {"bot_token": "TOKEN", "admin_telegram_id": "111"}
        with patch.object(B, "_DB_AVAILABLE", True), \
             patch.object(B, "_db", db, create=True), \
             patch.object(B, "load_config", return_value=cfg), \
             patch.object(B, "tg_send") as sent:
            B.job_nav_source_audit()
            return sent

    def test_skips_when_db_not_available(self):
        db = _mock_db()
        db.is_available.return_value = False
        sent = self._run(db)
        db.get_nav_source_audit.assert_not_called()
        sent.assert_not_called()

    def test_no_alert_when_no_funds_flagged(self):
        db = _mock_db()
        db.get_nav_source_audit.return_value = []
        sent = self._run(db)
        sent.assert_not_called()

    def test_sends_admin_alert_when_funds_flagged(self):
        db = _mock_db()
        db.get_nav_source_audit.return_value = [
            {"fund_code": "VCBFTBF", "untrusted_count": 5,
             "sources_seen": ["fmarket"], "sample_dates": ["2026-07-13", "2026-07-12"]},
        ]
        sent = self._run(db)
        sent.assert_called_once()
        args = sent.call_args[0]
        assert args[0] == "TOKEN"
        assert args[1] == "111"
        assert "VCBFTBF" in args[2]
        assert "5 ngày" in args[2]
        db.log_audit.assert_called_once()

    def test_no_alert_when_admin_config_missing(self):
        db = _mock_db()
        db.get_nav_source_audit.return_value = [
            {"fund_code": "VCBFTBF", "untrusted_count": 5,
             "sources_seen": ["fmarket"], "sample_dates": ["2026-07-13"]},
        ]
        sent = self._run(db, config={"bot_token": "", "admin_telegram_id": ""})
        sent.assert_not_called()

    def test_survives_db_query_exception(self):
        db = _mock_db()
        db.get_nav_source_audit.side_effect = RuntimeError("boom")
        sent = self._run(db)
        sent.assert_not_called()

    def test_survives_log_audit_exception(self):
        db = _mock_db()
        db.get_nav_source_audit.return_value = [
            {"fund_code": "VCBFTBF", "untrusted_count": 1,
             "sources_seen": ["fmarket"], "sample_dates": ["2026-07-13"]},
        ]
        db.log_audit.side_effect = RuntimeError("audit down")
        sent = self._run(db)
        sent.assert_called_once()
