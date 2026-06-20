"""
PATCH: Dedup token-expired alerts — chỉ gửi 1 tin nhắn mỗi lần token hết hạn.

Vấn đề gốc:
  - Job check token chạy theo schedule (mỗi N phút)
  - Mỗi lần chạy đều gửi alert → spam nhiều tin nhắn liên tục

Giải pháp:
  - Lưu flag `token_expired_alerted` vào state.json
  - Chỉ gửi khi flag = False (lần đầu phát hiện hết hạn)
  - Reset flag về False khi token được refresh thành công

CÁCH ÁP DỤNG:
  1. Import 2 hàm này vào bot.py
  2. Thay thế đoạn "gửi alert token hết hạn" bằng send_token_alert_once()
  3. Gọi reset_token_alert() sau khi refresh token thành công
"""

import json
import os

# ── Đường dẫn state file — theo DATA_DIR (giống bot.py) ─────────────────────
_STATE_FILE = os.path.join(os.environ.get("DATA_DIR", os.path.dirname(__file__)), "state.json")


def _load_state() -> dict:
    """Đọc state.json, trả về {} nếu lỗi."""
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    """Ghi state.json."""
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_token_alert_once(send_fn, message: str) -> bool:
    """
    Gửi alert token hết hạn — chỉ 1 lần cho mỗi chu kỳ hết hạn.

    Args:
        send_fn: hàm gửi Telegram message, ví dụ: lambda msg: bot.send_message(chat_id, msg)
        message: nội dung tin nhắn cảnh báo

    Returns:
        True nếu vừa gửi, False nếu đã gửi rồi (skip).

    Ví dụ dùng trong bot.py:
        def check_token():
            if is_token_expired():
                sent = send_token_alert_once(
                    send_fn=lambda m: send_message(ADMIN_CHAT_ID, m),
                    message="⚠️ TCBS Token đã hết hạn! Vào browser refresh lại."
                )
    """
    state = _load_state()

    if state.get("token_expired_alerted", False):
        # Đã gửi alert cho lần hết hạn này → bỏ qua
        return False

    # Lần đầu phát hiện → gửi alert và đánh dấu
    try:
        send_fn(message)
        state["token_expired_alerted"] = True
        _save_state(state)
        return True
    except Exception as e:
        # Nếu gửi Telegram thất bại → không set flag để có thể thử lại lần sau
        print(f"[token_alert] Gửi alert thất bại: {e}")
        return False


def reset_token_alert() -> None:
    """
    Reset flag sau khi token được refresh thành công.
    Gọi hàm này ngay sau khi lưu token mới vào config.json.

    Ví dụ trong bot.py:
        def save_new_token(new_token):
            config["tcbs_token"] = new_token
            save_config(config)
            reset_token_alert()   # ← thêm dòng này
    """
    state = _load_state()
    if state.get("token_expired_alerted", False):
        state["token_expired_alerted"] = False
        _save_state(state)
        print("[token_alert] Flag reset — sẵn sàng alert cho lần hết hạn tiếp theo.")
