"""
test_server.py — QA cho server.py endpoints
Endpoints: GET /bot-config, POST /bot-config, POST /save-nav,
           POST /refresh-nav, POST /tcbs-auth/otp, POST /tcbs-auth/verify
"""
import sys, json, re, io, tempfile, shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from http.server import HTTPServer
import threading, urllib.request, urllib.error

sys.path.insert(0, str(Path(__file__).parent))

# ── Import Handler từ server.py ──────────────────────────────────────────────
import importlib, types

# server.py dùng đường dẫn tuyệt đối từ __file__ nên cần patch trước khi import
# Ta sẽ test Handler class trực tiếp với mock file paths
import server as S

# ── Helpers ──────────────────────────────────────────────────────────────────

class MockWFile:
    def __init__(self):
        self.data = b""
    def write(self, b):
        self.data += b

class MockHandler:
    """Minimal mock của HTTP handler để test _json_resp và các helpers"""
    def __init__(self):
        self.wfile = MockWFile()
        self._headers = {}
        self._status = None
        self.headers = {}

    def send_response(self, code):
        self._status = code

    def send_header(self, k, v):
        self._headers[k] = v

    def end_headers(self):
        pass

    def get_response_body(self):
        return json.loads(self.wfile.data.decode("utf-8"))


def make_real_handler_with_tmp_files():
    """Tạo handler thực với thư mục tạm chứa HTML + config files."""
    tmp = tempfile.mkdtemp()

    # Tạo Dashboard.html tạm
    html_path = Path(tmp) / "Quy Tracker Dashboard.html"
    html_path.write_text(
        'var cn={"TCBF":[{"date":"2024-01-01","nav":13000}]};'
        'Object.keys(cn).forEach(function(){});'
        'var _bkRef="2024-01-01";',
        encoding="utf-8"
    )

    # Tạo config.json tạm
    bot_cfg_dir = Path(tmp) / "telegram-bot"
    bot_cfg_dir.mkdir()
    config = {
        "bot_token": "REAL_TOKEN_123",
        "tcbs_token": "SECRET_TCBS_TOKEN",
        "profiles": [{"name": "Harvey", "telegram_id": "111", "watched_funds": ["TCBF"]}]
    }
    (bot_cfg_dir / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    return tmp, html_path, bot_cfg_dir / "config.json"


# ════════════════════════════════════════════════════════
# _json_resp helper
# ════════════════════════════════════════════════════════

class TestJsonResp:

    def test_writes_json_body(self):
        handler = MockHandler()
        S._json_resp(handler, {"ok": True, "value": 42})
        body = handler.get_response_body()
        assert body["ok"] is True
        assert body["value"] == 42

    def test_sets_200_by_default(self):
        handler = MockHandler()
        S._json_resp(handler, {"ok": True})
        assert handler._status == 200

    def test_custom_status_code(self):
        handler = MockHandler()
        S._json_resp(handler, {"ok": False, "error": "not found"}, 404)
        assert handler._status == 404

    def test_content_type_json(self):
        handler = MockHandler()
        S._json_resp(handler, {"x": 1})
        assert "application/json" in handler._headers.get("Content-Type", "")

    def test_unicode_preserved(self):
        handler = MockHandler()
        S._json_resp(handler, {"msg": "Quỹ Tracker"})
        body = handler.get_response_body()
        assert body["msg"] == "Quỹ Tracker"


# ════════════════════════════════════════════════════════
# GET /bot-config — _get_bot_config
# ════════════════════════════════════════════════════════

class TestGetBotConfig:

    def test_returns_config_without_tokens(self):
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        try:
            with patch.object(S, "BOT_CFG", cfg_path):

                class FakeHandler(MockHandler):
                    pass
                FakeHandler.send_response = MockHandler.send_response
                FakeHandler.send_header = MockHandler.send_header
                FakeHandler.end_headers = MockHandler.end_headers

                handler = FakeHandler()
                # Gọi trực tiếp method
                S.Handler._get_bot_config(handler)

                body = handler.get_response_body()
                assert body.get("ok") is True
                cfg = body.get("config", {})
                # Token phải bị masking
                assert cfg.get("bot_token") == "", "bot_token phải bị mask thành ''"
                assert cfg.get("bot_token_set") is True
                assert cfg.get("tcbs_token") == "", "tcbs_token phải bị mask"
                assert cfg.get("tcbs_token_set") is True
        finally:
            shutil.rmtree(tmp)

    def test_returns_404_when_config_missing(self):
        with patch.object(S, "BOT_CFG", Path("/nonexistent/config.json")):
            handler = MockHandler()
            S.Handler._get_bot_config(handler)
            body = handler.get_response_body()
            assert body.get("ok") is False
            assert handler._status == 404

    def test_profiles_included_in_response(self):
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        try:
            with patch.object(S, "BOT_CFG", cfg_path):
                handler = MockHandler()
                S.Handler._get_bot_config(handler)
                body = handler.get_response_body()
                cfg = body.get("config", {})
                assert "profiles" in cfg, "profiles phải có trong response"
        finally:
            shutil.rmtree(tmp)


# ════════════════════════════════════════════════════════
# POST /bot-config — _handle_save_bot_config
# ════════════════════════════════════════════════════════

class TestSaveBotConfig:

    def test_merges_new_data_with_existing(self):
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        try:
            with patch.object(S, "BOT_CFG", cfg_path):
                handler = MockHandler()
                new_data = {"profiles": [{"name": "NewUser", "telegram_id": "999", "watched_funds": []}]}
                S.Handler._handle_save_bot_config(handler, new_data)
                body = handler.get_response_body()
                assert body.get("ok") is True

                # Verify saved
                saved = json.loads(cfg_path.read_text())
                assert saved["profiles"][0]["name"] == "NewUser"
                # Token cũ phải được giữ
                assert saved["bot_token"] == "REAL_TOKEN_123"
        finally:
            shutil.rmtree(tmp)

    def test_preserves_existing_token_when_not_sent(self):
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        try:
            with patch.object(S, "BOT_CFG", cfg_path):
                handler = MockHandler()
                # Gửi update nhưng không gửi bot_token
                S.Handler._handle_save_bot_config(handler, {"some_key": "some_val"})
                saved = json.loads(cfg_path.read_text())
                assert saved["bot_token"] == "REAL_TOKEN_123", \
                    "bot_token cũ phải được giữ nguyên khi không gửi token mới"
        finally:
            shutil.rmtree(tmp)

    def test_removes_token_set_flags(self):
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        try:
            with patch.object(S, "BOT_CFG", cfg_path):
                handler = MockHandler()
                # Gửi token_set flags (từ frontend)
                S.Handler._handle_save_bot_config(handler, {
                    "bot_token_set": True,
                    "tcbs_token_set": True
                })
                saved = json.loads(cfg_path.read_text())
                assert "bot_token_set" not in saved, "bot_token_set không được lưu vào file"
                assert "tcbs_token_set" not in saved
        finally:
            shutil.rmtree(tmp)

    def test_returns_404_when_config_missing(self):
        with patch.object(S, "BOT_CFG", Path("/nonexistent/config.json")):
            handler = MockHandler()
            S.Handler._handle_save_bot_config(handler, {})
            body = handler.get_response_body()
            assert body.get("ok") is False
            assert handler._status == 404


# ════════════════════════════════════════════════════════
# POST /save-nav — _save_nav
# ════════════════════════════════════════════════════════

class TestSaveNav:
    """_save_nav ghi INCREMENTAL delta vào nav_data.json (chỉ điểm sau HIST cutoff)."""

    # histCutoff = ngày cuối HIST cho mỗi quỹ
    HIST_CUTOFF = {"TCBF": "2026-04-02", "SSISCA": "2026-04-02"}

    def _make_nav_data(self):
        """Payload chuẩn: có cả histCutoff. Ngày 04-08/04-09 > cutoff 04-02 → được lưu."""
        return {
            "cachedNav": {
                "TCBF": [
                    {"date": "2026-03-30", "nav": 13480.0},   # <= cutoff → phải bị lọc
                    {"date": "2026-04-02", "nav": 13490.0},   # = cutoff  → phải bị lọc
                    {"date": "2026-04-08", "nav": 13500.0},   # > cutoff  → phải được lưu
                    {"date": "2026-04-09", "nav": 13520.0},   # > cutoff  → phải được lưu
                ],
                "SSISCA": [
                    {"date": "2026-04-08", "nav": 12100.0},
                    {"date": "2026-04-09", "nav": 12110.0},
                ]
            },
            "lastRefresh": "2026-04-09",
            "histCutoff": self.HIST_CUTOFF,
        }

    def _tmp_nav_file(self):
        """Tạo file nav_data.json tạm, trả về (tmp_dir, nav_path)."""
        tmp = tempfile.mkdtemp()
        nav_path = Path(tmp) / "nav_data.json"
        return tmp, nav_path

    def test_writes_incremental_points_only(self):
        """nav_data.json chỉ được chứa điểm SAU HIST cutoff."""
        tmp, nav_path = self._tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                S.Handler._save_nav(handler, self._make_nav_data())
                assert nav_path.exists(), "nav_data.json phải được tạo"
                saved = json.loads(nav_path.read_text(encoding="utf-8"))
                tcbf = saved.get("TCBF", [])
                # Chỉ có 2 điểm sau cutoff 2026-04-02
                assert len(tcbf) == 2, f"Chỉ 2 điểm sau cutoff, got {len(tcbf)}"
                for p in tcbf:
                    assert p["date"] > "2026-04-02", f"Điểm {p['date']} phải > cutoff"
        finally:
            shutil.rmtree(tmp)

    def test_stores_last_refresh_in_json(self):
        """_lastRefresh phải được lưu vào nav_data.json."""
        tmp, nav_path = self._tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                S.Handler._save_nav(handler, self._make_nav_data())
                saved = json.loads(nav_path.read_text(encoding="utf-8"))
                assert saved.get("_lastRefresh") == "2026-04-09"
        finally:
            shutil.rmtree(tmp)

    def test_returns_fund_list_and_latest_date(self):
        tmp, nav_path = self._tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                result = S.Handler._save_nav(handler, self._make_nav_data())
                assert "funds" in result
                assert "latest_date" in result
                assert "TCBF" in result["funds"]
                assert result["latest_date"] == "2026-04-09"
        finally:
            shutil.rmtree(tmp)

    def test_skips_when_all_points_older_than_cutoff(self):
        """Tất cả điểm đều <= cutoff → không ghi file."""
        tmp, nav_path = self._tmp_nav_file()
        try:
            data = {
                "cachedNav": {"TCBF": [{"date": "2026-04-01", "nav": 13400.0}]},
                "lastRefresh": "2026-04-01",
                "histCutoff": {"TCBF": "2026-04-02"},
            }
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                result = S.Handler._save_nav(handler, data)
                assert "skipped" in result
                assert not nav_path.exists(), "nav_data.json không nên tạo khi không có điểm mới"
        finally:
            shutil.rmtree(tmp)

    def test_skips_when_no_cached_nav(self):
        tmp, nav_path = self._tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                result = S.Handler._save_nav(handler, {"cachedNav": {}, "lastRefresh": ""})
                assert "skipped" in result
                assert not nav_path.exists()
        finally:
            shutil.rmtree(tmp)

    def test_backward_compat_without_hist_cutoff(self):
        """Nếu không có histCutoff, fallback về NAV_KEEP_POINTS trim."""
        tmp, nav_path = self._tmp_nav_file()
        try:
            many_pts = [{"date": f"2023-{str(i % 12 + 1).zfill(2)}-01", "nav": 13000.0 + i}
                        for i in range(600)]
            data = {"cachedNav": {"TCBF": many_pts}, "lastRefresh": "2026-01-01"}
            # Không có histCutoff → fallback
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                S.Handler._save_nav(handler, data)
                saved = json.loads(nav_path.read_text(encoding="utf-8"))
                assert len(saved.get("TCBF", [])) <= S.NAV_KEEP_POINTS
        finally:
            shutil.rmtree(tmp)

    def test_merges_with_existing_nav_data(self):
        """Quỹ không có trong payload phải được giữ nguyên trong nav_data.json."""
        tmp, nav_path = self._tmp_nav_file()
        try:
            # Pre-populate VCBFTBF trong nav_data.json
            nav_path.write_text(json.dumps({
                "VCBFTBF": [{"date": "2026-04-08", "nav": 29000.0}],
                "_lastRefresh": "2026-04-08"
            }), encoding="utf-8")
            # Gửi chỉ TCBF
            data = {
                "cachedNav": {"TCBF": [{"date": "2026-04-09", "nav": 13520.0}]},
                "lastRefresh": "2026-04-09",
                "histCutoff": {"TCBF": "2026-04-02"},
            }
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                S.Handler._save_nav(handler, data)
                saved = json.loads(nav_path.read_text(encoding="utf-8"))
                assert "TCBF" in saved, "TCBF phải được thêm"
                assert "VCBFTBF" in saved, "VCBFTBF phải được giữ nguyên"
        finally:
            shutil.rmtree(tmp)

    def test_html_not_modified_by_save_nav(self):
        """Đảm bảo _save_nav không còn ghi vào HTML nữa."""
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        nav_tmp, nav_path = self._tmp_nav_file()
        original_html = html_path.read_text(encoding="utf-8")
        try:
            with patch.object(S, "NAV_DATA_FILE", nav_path):
                handler = MockHandler()
                S.Handler._save_nav(handler, self._make_nav_data())
                assert html_path.read_text(encoding="utf-8") == original_html, \
                    "HTML không được bị sửa bởi _save_nav"
        finally:
            shutil.rmtree(tmp)
            shutil.rmtree(nav_tmp)


# ════════════════════════════════════════════════════════
# POST /tcbs-auth/otp — _handle_tcbs_otp
# ════════════════════════════════════════════════════════

class TestTcbsOtp:

    def test_returns_400_without_phone(self):
        handler = MockHandler()
        S.Handler._handle_tcbs_otp(handler, {})
        body = handler.get_response_body()
        assert body.get("ok") is False
        assert handler._status == 400

    def test_returns_400_with_empty_phone(self):
        handler = MockHandler()
        S.Handler._handle_tcbs_otp(handler, {"phone": "  "})
        body = handler.get_response_body()
        assert body.get("ok") is False
        assert handler._status == 400

    def test_proxies_to_tcbs_endpoint(self):
        with patch.object(S, "_proxy_post", return_value=(200, {"status": "sent"})) as mock_proxy:
            handler = MockHandler()
            S.Handler._handle_tcbs_otp(handler, {"phone": "0901234567"})
            assert mock_proxy.called
            called_url = mock_proxy.call_args[0][0]
            assert "tcbs" in called_url.lower() or "apipub" in called_url

    def test_returns_ok_on_tcbs_success(self):
        with patch.object(S, "_proxy_post", return_value=(200, {"status": "sent"})):
            handler = MockHandler()
            S.Handler._handle_tcbs_otp(handler, {"phone": "0901234567"})
            body = handler.get_response_body()
            assert body.get("ok") is True

    def test_returns_502_when_tcbs_fails(self):
        with patch.object(S, "_proxy_post", return_value=(500, {"error": "TCBS down"})):
            handler = MockHandler()
            S.Handler._handle_tcbs_otp(handler, {"phone": "0901234567"})
            body = handler.get_response_body()
            assert body.get("ok") is False
            assert handler._status == 502


# ════════════════════════════════════════════════════════
# POST /tcbs-auth/verify — _handle_tcbs_verify
# ════════════════════════════════════════════════════════

class TestTcbsVerify:

    def test_returns_400_without_phone_or_otp(self):
        handler = MockHandler()
        S.Handler._handle_tcbs_verify(handler, {"phone": "0901234567"})
        assert handler._status == 400

    def test_returns_400_without_otp(self):
        handler = MockHandler()
        S.Handler._handle_tcbs_verify(handler, {"otp": "123456"})
        assert handler._status == 400

    def test_saves_token_to_config_on_success(self):
        tmp, html_path, cfg_path = make_real_handler_with_tmp_files()
        try:
            tcbs_resp = (200, {"data": {"access_token": "NEW_TCBS_TOKEN_XYZ"}})
            with patch.object(S, "_proxy_post", return_value=tcbs_resp), \
                 patch.object(S, "BOT_CFG", cfg_path):
                handler = MockHandler()
                S.Handler._handle_tcbs_verify(handler, {
                    "phone": "0901234567", "otp": "123456"
                })
                body = handler.get_response_body()
                assert body.get("ok") is True
                assert body.get("token") == "NEW_TCBS_TOKEN_XYZ"

                # Kiểm tra đã lưu vào config.json
                saved = json.loads(cfg_path.read_text())
                assert saved.get("tcbs_token") == "NEW_TCBS_TOKEN_XYZ", \
                    "tcbs_token mới phải được lưu vào config.json"
        finally:
            shutil.rmtree(tmp)

    def test_returns_error_when_no_token_in_response(self):
        with patch.object(S, "_proxy_post", return_value=(200, {"data": {}})):
            handler = MockHandler()
            S.Handler._handle_tcbs_verify(handler, {"phone": "0901234567", "otp": "123456"})
            body = handler.get_response_body()
            assert body.get("ok") is False
            assert "token" in body.get("error", "").lower() or "token" in str(body)

    def test_returns_502_when_tcbs_verify_fails(self):
        with patch.object(S, "_proxy_post", return_value=(401, {"error": "Invalid OTP"})):
            handler = MockHandler()
            S.Handler._handle_tcbs_verify(handler, {"phone": "0901234567", "otp": "999999"})
            body = handler.get_response_body()
            assert body.get("ok") is False
            assert handler._status == 502


# ════════════════════════════════════════════════════════
# _proxy_post
# ════════════════════════════════════════════════════════

class TestProxyPost:

    def test_returns_status_and_dict(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda s: mock_resp
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_ctx):
            status, data = S._proxy_post("https://example.com", {"key": "val"})
            assert status == 200
            assert data == {"ok": True}

    def test_handles_http_error(self):
        import urllib.error
        err = urllib.error.HTTPError(
            "https://example.com", 401, "Unauthorized",
            {}, io.BytesIO(b'{"error":"unauthorized"}')
        )
        with patch("urllib.request.urlopen", side_effect=err):
            status, data = S._proxy_post("https://example.com", {})
            assert status == 401

    def test_handles_connection_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            status, data = S._proxy_post("https://example.com", {})
            assert status == 0
            assert "error" in data


# ════════════════════════════════════════════════════════
# POST /refresh-nav — server-side NAV fetch
# ════════════════════════════════════════════════════════

class TestRefreshNav:
    """Test _handle_refresh_nav: server fetch NAV từ fmarket/TCBS → nav_data.json."""

    FMARKET_NAV = [{"date": "2026-04-03", "nav": 45900.0}, {"date": "2026-04-08", "nav": 46000.0}]
    TCBS_NAV    = [{"date": "2026-04-03", "nav": 20490.0}]

    def _make_tmp_nav_file(self):
        tmp = tempfile.mktemp(suffix=".json")
        return Path(tmp)

    def test_refresh_writes_fmarket_funds(self):
        """fmarket quỹ (SSISCA) → nav_data.json có điểm mới."""
        tmp_nav = self._make_tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", tmp_nav), \
                 patch.object(S, "_fetch_fmarket_nav", return_value=self.FMARKET_NAV), \
                 patch.object(S, "_fetch_tcbs_nav", return_value=[]):
                handler = MockHandler()
                S.Handler._handle_refresh_nav(handler, {"funds": ["SSISCA"]})
                body = handler.get_response_body()
                assert body["ok"] is True
                assert "SSISCA" in body["funds"]
                assert body["new_points"] == 2
                saved = json.loads(tmp_nav.read_text(encoding="utf-8"))
                assert "SSISCA" in saved
                assert len(saved["SSISCA"]) == 2
        finally:
            if tmp_nav.exists():
                tmp_nav.unlink()

    def test_refresh_writes_tcbs_funds(self):
        """TCBS quỹ (TCBF) → nav_data.json có điểm mới."""
        tmp_nav = self._make_tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", tmp_nav), \
                 patch.object(S, "_fetch_fmarket_nav", return_value=[]), \
                 patch.object(S, "_fetch_tcbs_nav", return_value=self.TCBS_NAV), \
                 patch.object(S, "BOT_CFG", Path("/nonexistent/config.json")):
                handler = MockHandler()
                S.Handler._handle_refresh_nav(handler, {"funds": ["TCBF"]})
                body = handler.get_response_body()
                assert body["ok"] is True
                assert "TCBF" in body["funds"]
                saved = json.loads(tmp_nav.read_text(encoding="utf-8"))
                assert "TCBF" in saved
        finally:
            if tmp_nav.exists():
                tmp_nav.unlink()

    def test_refresh_merges_with_existing_data(self):
        """Dữ liệu mới merge với quỹ cũ trong nav_data.json."""
        tmp_nav = self._make_tmp_nav_file()
        existing = {"VCBFTBF": [{"date": "2026-04-05", "nav": 39200.0}], "_lastRefresh": "05/04/2026 09:00"}
        tmp_nav.write_text(json.dumps(existing), encoding="utf-8")
        try:
            with patch.object(S, "NAV_DATA_FILE", tmp_nav), \
                 patch.object(S, "_fetch_fmarket_nav", return_value=self.FMARKET_NAV), \
                 patch.object(S, "_fetch_tcbs_nav", return_value=[]):
                handler = MockHandler()
                S.Handler._handle_refresh_nav(handler, {"funds": ["SSISCA"]})
                body = handler.get_response_body()
                assert body["ok"] is True
                saved = json.loads(tmp_nav.read_text(encoding="utf-8"))
                # Quỹ cũ được giữ nguyên
                assert "VCBFTBF" in saved
                # Quỹ mới được thêm
                assert "SSISCA" in saved
        finally:
            if tmp_nav.exists():
                tmp_nav.unlink()

    def test_refresh_returns_error_when_all_funds_fail(self):
        """Khi tất cả API fail → trả về ok=False."""
        tmp_nav = self._make_tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", tmp_nav), \
                 patch.object(S, "_fetch_fmarket_nav", return_value=[]), \
                 patch.object(S, "_fetch_tcbs_nav", return_value=[]), \
                 patch.object(S, "BOT_CFG", Path("/nonexistent/config.json")):
                handler = MockHandler()
                S.Handler._handle_refresh_nav(handler, {"funds": ["SSISCA", "TCBF"]})
                body = handler.get_response_body()
                assert body["ok"] is False
                assert "error" in body
        finally:
            if tmp_nav.exists():
                tmp_nav.unlink()

    def test_refresh_defaults_to_all_funds_when_no_body(self):
        """Không truyền funds → fetch tất cả FUNDS_CONFIG."""
        tmp_nav = self._make_tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", tmp_nav), \
                 patch.object(S, "_fetch_fmarket_nav", return_value=self.FMARKET_NAV), \
                 patch.object(S, "_fetch_tcbs_nav", return_value=self.TCBS_NAV), \
                 patch.object(S, "BOT_CFG", Path("/nonexistent/config.json")):
                handler = MockHandler()
                S.Handler._handle_refresh_nav(handler, {})
                body = handler.get_response_body()
                assert body["ok"] is True
                # Phải fetch cả 5 quỹ
                assert len(body["funds"]) == len(S.FUNDS_CONFIG)
        finally:
            if tmp_nav.exists():
                tmp_nav.unlink()

    def test_refresh_writes_last_refresh_timestamp(self):
        """_lastRefresh được ghi vào nav_data.json."""
        tmp_nav = self._make_tmp_nav_file()
        try:
            with patch.object(S, "NAV_DATA_FILE", tmp_nav), \
                 patch.object(S, "_fetch_fmarket_nav", return_value=self.FMARKET_NAV), \
                 patch.object(S, "_fetch_tcbs_nav", return_value=[]):
                handler = MockHandler()
                S.Handler._handle_refresh_nav(handler, {"funds": ["SSISCA"]})
                saved = json.loads(tmp_nav.read_text(encoding="utf-8"))
                assert "_lastRefresh" in saved
                # Format dd/mm/yyyy HH:MM
                import re
                assert re.match(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", saved["_lastRefresh"])
        finally:
            if tmp_nav.exists():
                tmp_nav.unlink()

    def test_fetch_fmarket_nav_filters_by_from_date(self):
        """_fetch_fmarket_nav loại bỏ điểm <= from_date."""
        pts = [
            {"date": "2026-04-01", "nav": 45800.0},
            {"date": "2026-04-02", "nav": 45820.0},
            {"date": "2026-04-03", "nav": 45900.0},
        ]
        mock_response = b'{"data":{"navHistories":[' + b",".join(
            json.dumps({"navDate": p["date"], "nav": p["nav"]}).encode() for p in pts
        ) + b"]}}"
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = S._fetch_fmarket_nav(11, from_date="2026-04-02")
        # Chỉ lấy điểm > 2026-04-02
        assert all(p["date"] > "2026-04-02" for p in result)
        assert len(result) == 1
        assert result[0]["date"] == "2026-04-03"

    def test_fetch_tcbs_nav_filters_by_from_date(self):
        """_fetch_tcbs_nav loại bỏ điểm <= from_date."""
        nav_pts = [
            {"navDate": "2026-04-01", "nav": 20470.0},
            {"navDate": "2026-04-03", "nav": 20490.0},
        ]
        mock_response = json.dumps({"data": nav_pts}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = S._fetch_tcbs_nav("TCBF", from_date="2026-04-02")
        assert all(p["date"] > "2026-04-02" for p in result)
        assert len(result) == 1
