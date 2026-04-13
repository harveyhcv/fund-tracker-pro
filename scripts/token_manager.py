#!/usr/bin/env python3
"""token_manager.py — Kiểm tra JWT TCBS token freshness.

Dùng:
  python3 scripts/token_manager.py --check   # check + alert nếu gần hết hạn
  python3 scripts/token_manager.py --status  # in trạng thái ra stdout (không alert)
"""
import argparse, base64, datetime, json, os, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "telegram-bot/config.json"
STATE_PATH  = ROOT / "telegram-bot/state.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def decode_jwt_exp(token: str):
    """Parse JWT payload → trả về Unix timestamp 'exp', hoặc None nếu lỗi."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        return payload.get("exp")
    except Exception:
        return None


def check_token(alert: bool = True) -> dict:
    """Kiểm tra token, trả về dict trạng thái."""
    cfg = load_config()
    token = cfg.get("tcbs_token", "")
    now = datetime.datetime.now().timestamp()

    if not token:
        return {"status": "missing", "remaining_minutes": 0}

    exp = decode_jwt_exp(token)
    if exp is None:
        return {"status": "unreadable", "remaining_minutes": 0}

    remaining = exp - now
    remaining_minutes = int(remaining / 60)

    if remaining <= 0:
        status = "expired"
    elif remaining < 3600:          # < 1h
        status = "critical"
    elif remaining < 7200:          # < 2h
        status = "warning"
    else:
        status = "ok"

    result = {"status": status, "remaining_minutes": remaining_minutes, "exp": exp}

    if alert and status in ("expired", "critical", "warning"):
        _send_alert(cfg, status, remaining_minutes)

    return result


def _send_alert(cfg: dict, status: str, remaining_minutes: int):
    """Gửi Telegram alert — dùng send_token_alert_once để tránh spam."""
    sys.path.insert(0, str(ROOT / "telegram-bot"))
    from token_alert_patch import send_token_alert_once

    if status == "expired":
        msg = "🔴 TCBS JWT Token ĐÃ HẾT HẠN! Vào Dashboard Settings → refresh ngay."
    elif status == "critical":
        msg = f"🟠 TCBS JWT Token sắp hết hạn! Còn {remaining_minutes} phút."
    else:
        msg = f"🟡 TCBS JWT Token còn {remaining_minutes} phút — chuẩn bị refresh."

    chat_id   = cfg.get("telegram_chat_id") or cfg.get("admin_chat_id")
    bot_token = cfg.get("telegram_token") or cfg.get("bot_token")
    if not (chat_id and bot_token):
        print(f"[token_manager] Không tìm thấy bot_token/chat_id trong config: {msg}")
        return

    import urllib.request

    def send_fn(text):
        url  = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)

    sent = send_token_alert_once(send_fn, msg)
    if sent:
        print(f"[token_manager] Alert đã gửi: {msg}")
    else:
        print(f"[token_manager] Alert đã gửi trước đó — bỏ qua (dedup)")


def main():
    parser = argparse.ArgumentParser(description="Kiểm tra TCBS JWT token freshness")
    parser.add_argument("--check",  action="store_true", help="Check + gửi alert nếu cần")
    parser.add_argument("--status", action="store_true", help="In trạng thái, không alert")
    args = parser.parse_args()

    result = check_token(alert=args.check)
    status = result["status"]
    mins   = result["remaining_minutes"]

    icons = {
        "ok":         "✅",
        "warning":    "🟡",
        "critical":   "🟠",
        "expired":    "🔴",
        "missing":    "❓",
        "unreadable": "❓",
    }
    print(f"[token_manager] {icons.get(status, '?')} Status: {status.upper()} | Còn: {mins} phút")

    if status == "expired":
        sys.exit(1)  # Exit code 1 → crontab có thể phát hiện


if __name__ == "__main__":
    main()
