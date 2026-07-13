"""
test_new_commands.py — QA cho /admin + env config.

/watch, /unwatch, /funds đã được thay bằng redirect tĩnh "chuyển vào Mini App"
(bot.py, cmd in ("/dca","/funds","/watch","/unwatch")) — không còn logic thật để
test (mutate watchlist, liệt kê quỹ...) nên các test class tương ứng đã bị xoá
thay vì sửa để "pass giả" theo hành vi redirect (không có giá trị coverage).
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))
import bot as B

SAMPLE_CONFIG = {
    "bot_token": "123456:TEST",
    "admin_telegram_id": "999000999",
    "default_watched_funds": ["TCBF", "SSISCA"],
    "profiles": [
        {"name": "Harvey",  "telegram_id": "111222333", "watched_funds": ["TCBF", "SSISCA"]},
        {"name": "Friend",  "telegram_id": "444555666", "watched_funds": ["TCBF"]},
    ],
    "funds": {
        "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank", "fmarket_id": 22},
        "SSISCA":  {"name": "Quỹ Tích Lũy Bền Vững SSI",  "fmarket_id": 11},
        "VCBFBCF": {"name": "Quỹ Trái Phiếu VCB Fund",    "fmarket_id": 32},
        "MBBF":    {"name": "Quỹ Trái Phiếu MB Capital",  "fmarket_id": 40},
    },
    "schedule": {"morning_report": "08:00", "evening_report": "17:30", "signal_check_interval_minutes": 60},
}


def make_update(text, chat_id="111222333"):
    return {
        "update_id": 1,
        "message": {"chat": {"id": int(chat_id), "first_name": "Harvey"}, "text": text},
    }


def run_one_command(text, chat_id="111222333", config=None):
    """Giả lập 1 lần getUpdates rồi dùng KeyboardInterrupt thoát vòng lặp."""
    cfg = config or SAMPLE_CONFIG
    call_count = [0]
    sent_messages = []
    saved_configs = []

    def fake_get(url, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return MagicMock(ok=True, json=lambda: {"result": [make_update(text, chat_id)]})
        raise KeyboardInterrupt  # Thoát infinite loop trong command_handler

    def fake_post(url, **kwargs):
        m = MagicMock(ok=True)
        if "sendMessage" in url:
            sent_messages.append(kwargs.get("json", {}).get("text", ""))
        return m

    def fake_save(c):
        saved_configs.append(json.loads(json.dumps(c)))

    with patch("bot.load_config", return_value=cfg), \
         patch("bot.save_config", side_effect=fake_save), \
         patch("requests.get", side_effect=fake_get), \
         patch("requests.post", side_effect=fake_post):
        try:
            B.command_handler()
        except KeyboardInterrupt:
            pass

    mock_save = MagicMock()
    mock_save.call_count = len(saved_configs)
    mock_save.called = len(saved_configs) > 0
    mock_save.saved = saved_configs
    return sent_messages, mock_save


# ════════════════════════════════════════════════════════
# /watch, /unwatch, /funds — redirect tĩnh, xem docstring đầu file
# ════════════════════════════════════════════════════════

class TestDeprecatedCommandsRedirect:
    """Xác nhận các lệnh cũ hướng dẫn user sang Mini App thay vì lỗi im lặng."""

    def test_funds_redirects_to_miniapp(self):
        msgs, _ = run_one_command("/funds", chat_id="111222333")
        assert any("Mini App" in m for m in msgs)

    def test_watch_redirects_to_miniapp(self):
        msgs, _ = run_one_command("/watch VCBFBCF", chat_id="111222333")
        assert any("Mini App" in m for m in msgs)

    def test_unwatch_redirects_to_miniapp(self):
        msgs, _ = run_one_command("/unwatch TCBF", chat_id="111222333")
        assert any("Mini App" in m for m in msgs)


# ════════════════════════════════════════════════════════
# /admin
# ════════════════════════════════════════════════════════

class TestAdminCommand:
    ADMIN_ID = "999000999"

    def test_admin_blocked_for_non_admin(self):
        msgs, _ = run_one_command("/admin users", chat_id="111222333")
        assert any("admin" in m.lower() or "⛔" in m for m in msgs)

    def test_admin_users_shows_profiles(self):
        msgs, _ = run_one_command("/admin users", chat_id=self.ADMIN_ID)
        combined = " ".join(msgs)
        assert "Harvey" in combined
        assert "Friend" in combined

    def test_admin_users_shows_count(self):
        msgs, _ = run_one_command("/admin users", chat_id=self.ADMIN_ID)
        assert any("2" in m for m in msgs)

    def test_admin_users_empty(self):
        cfg = json.loads(json.dumps(SAMPLE_CONFIG))
        cfg["profiles"] = []
        msgs, _ = run_one_command("/admin users", chat_id=self.ADMIN_ID, config=cfg)
        assert any("Chưa có" in m or "📭" in m for m in msgs)

    def test_admin_kick_removes_profile(self):
        cfg = json.loads(json.dumps(SAMPLE_CONFIG))
        msgs, mock_save = run_one_command("/admin kick 444555666", chat_id=self.ADMIN_ID, config=cfg)
        combined = " ".join(msgs)
        assert "444555666" in combined
        assert mock_save.called

    def test_admin_kick_nonexistent(self):
        msgs, mock_save = run_one_command("/admin kick 000000000", chat_id=self.ADMIN_ID)
        assert any("Không tìm thấy" in m for m in msgs)
        assert not mock_save.called

    def test_admin_no_subcommand_shows_help(self):
        msgs, _ = run_one_command("/admin", chat_id=self.ADMIN_ID)
        combined = " ".join(msgs)
        assert "users" in combined and "kick" in combined

    def test_admin_broadcast_sends_to_users(self):
        sent_to = []
        cfg = json.loads(json.dumps(SAMPLE_CONFIG))
        call_count = [0]

        def fake_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(ok=True, json=lambda: {
                    "result": [make_update("/admin broadcast Xin chào!", self.ADMIN_ID)]
                })
            raise KeyboardInterrupt

        def fake_post(url, **kwargs):
            m = MagicMock(ok=True)
            if "sendMessage" in url:
                sent_to.append(kwargs.get("json", {}).get("chat_id", ""))
            return m

        with patch("bot.load_config", return_value=cfg), \
             patch("bot.save_config"), \
             patch("requests.get", side_effect=fake_get), \
             patch("requests.post", side_effect=fake_post):
            try:
                B.command_handler()
            except KeyboardInterrupt:
                pass

        user_chats = [c for c in sent_to if c in ("111222333", "444555666")]
        assert len(user_chats) == 2


# ════════════════════════════════════════════════════════
# ENV variable support
# ════════════════════════════════════════════════════════

class TestEnvConfig:
    def test_bot_token_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BOT_TOKEN", "env_token_value")
        monkeypatch.setattr(B, "CONFIG_FILE", tmp_path / "missing.json")
        cfg = B.load_config()
        assert cfg.get("bot_token") == "env_token_value"

    def test_admin_id_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ADMIN_TELEGRAM_ID", "777888999")
        monkeypatch.setattr(B, "CONFIG_FILE", tmp_path / "missing.json")
        cfg = B.load_config()
        assert cfg.get("admin_telegram_id") == "777888999"

    def test_env_overrides_config_file(self, monkeypatch, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"bot_token": "file_token"}), encoding="utf-8")
        monkeypatch.setenv("BOT_TOKEN", "env_token_wins")
        monkeypatch.setattr(B, "CONFIG_FILE", cfg_path)
        cfg = B.load_config()
        assert cfg.get("bot_token") == "env_token_wins"

    def test_ensure_config_creates_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BOT_TOKEN", "bootstrap_token")
        monkeypatch.setenv("ADMIN_TELEGRAM_ID", "987654321")
        monkeypatch.setattr(B, "CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(B, "DATA_DIR", tmp_path)
        B._ensure_config_exists()
        assert (tmp_path / "config.json").exists()
        data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert data["bot_token"] == "bootstrap_token"
        assert data["admin_telegram_id"] == "987654321"
        assert "funds" in data
        assert "schedule" in data

    def test_ensure_config_skips_if_exists(self, monkeypatch, tmp_path):
        existing = tmp_path / "config.json"
        existing.write_text(json.dumps({"bot_token": "existing"}), encoding="utf-8")
        monkeypatch.setenv("BOT_TOKEN", "new_token")
        monkeypatch.setattr(B, "CONFIG_FILE", existing)
        monkeypatch.setattr(B, "DATA_DIR", tmp_path)
        B._ensure_config_exists()
        data = json.loads(existing.read_text())
        assert data["bot_token"] == "existing"  # không bị overwrite

    def test_ensure_config_no_env_token_does_nothing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("BOT_TOKEN", raising=False)
        monkeypatch.setattr(B, "CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(B, "DATA_DIR", tmp_path)
        B._ensure_config_exists()
        assert not (tmp_path / "config.json").exists()
