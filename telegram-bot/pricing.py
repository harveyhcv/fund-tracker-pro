"""
pricing.py — Bảng giá Premium dùng chung cho bot.py (Telegram Stars) và
miniapp_server.py (Stars + MoMo). Không import gì khác để cả 2 module luôn
import được, kể cả khi psycopg2/requests chưa cài (bot.py, db.py có thể fail
import trong môi trường dev thiếu dependency).

Mục tiêu kinh doanh: khuyến khích thanh toán theo năm — giá/tháng giảm dần
theo kỳ hạn dài hơn.
"""

PRO_PLANS = {
    "m1": {"days": 30,  "stars": 50,  "vnd": 20000,  "label": "1 tháng",          "discount_pct": 0},
    "q1": {"days": 90,  "stars": 135, "vnd": 54000,  "label": "1 quý (3 tháng)",  "discount_pct": 10},
    "h1": {"days": 180, "stars": 225, "vnd": 90000,  "label": "Nửa năm (6 tháng)", "discount_pct": 25},
    "y1": {"days": 365, "stars": 330, "vnd": 132000, "label": "1 năm",            "discount_pct": 45},
}
# Giá/⭐ giữ cố định ở 400 VND/⭐ cho mọi gói (khớp với tỷ giá 20.000đ/50⭐ gói tháng) —
# discount_pct luôn khớp thật với giá: vnd = 20000 * (days/30) * (1 - discount_pct/100).

DEFAULT_PLAN = "m1"

# Thứ tự hiển thị trong UI (menu Telegram, mini app) — cố ý đẩy gói năm lên
# gần cuối nhưng làm nổi bật bằng nhãn "TIẾT KIỆM NHẤT" phía caller.
PLAN_ORDER = ["m1", "q1", "h1", "y1"]


def resolve_plan(key: str) -> dict:
    """Trả plan dict hợp lệ; fallback về DEFAULT_PLAN nếu key lạ/rỗng
    (vd: payload/orderId cũ trước khi có multi-tier, hoặc dữ liệu hỏng)."""
    return PRO_PLANS.get(key, PRO_PLANS[DEFAULT_PLAN])
