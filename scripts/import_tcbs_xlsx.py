#!/usr/bin/env python3
"""
import_tcbs_xlsx.py — Import lịch sử giao dịch CCQ từ file Excel TCBS vào trade_log.

Dùng endpoint /api/admin/import-trades trên Railway server.

Usage:
  python scripts/import_tcbs_xlsx.py --file "path/to/Lịch sử giao dịch quỹ_....xlsx" \
      --telegram-id YOUR_TG_ID [--server URL] [--replace] [--dry-run]

Options:
  --server    URL Railway server (default: đọc từ config.json hoặc env MINIAPP_URL)
  --replace   Xóa toàn bộ trade_log cũ của user trước khi import
  --dry-run   Chỉ parse, không POST lên server
"""
import sys, json, argparse
from pathlib import Path
from datetime import datetime
import urllib.request as _req

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent


def parse_xlsx(xlsx_path: Path) -> list:
    """Parse file Excel TCBS → list of trade dicts."""
    try:
        import openpyxl
    except ImportError:
        print("❌ Cần cài openpyxl: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.load_workbook(str(xlsx_path))
    ws = wb.active

    trades = []
    header_row = None

    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        # Tìm hàng header: có cột "Quỹ" / "Fund"
        if row[0] and str(row[0]).strip().startswith("Quỹ"):
            header_row = i
            continue
        if header_row is None:
            continue  # Chưa tới data

        # Stop at footer
        first = str(row[0]).strip() if row[0] else ""
        if first.startswith("Ngày xuất") or first.startswith("Report") or first.startswith("Chú thích"):
            break

        if not first or first == "None":
            continue

        code     = first.upper().strip()
        tx_raw   = str(row[1]).strip() if row[1] else ""
        date_raw = str(row[2]).strip() if row[2] else ""
        nav_val  = row[3]  # Giá vốn (price/unit)
        units    = row[4]  # Số lượng
        amount   = row[6]  # Tổng tiền
        status   = str(row[7]).strip() if row[7] else ""

        # Chỉ import giao dịch đã hoàn tất
        if "hoàn tất" not in status.lower() and "hoàn thành" not in status.lower():
            print(f"  ⚠️ Bỏ qua ({status}): {code} {date_raw}")
            continue

        # Loại giao dịch
        tx_lower = tx_raw.lower()
        if "mua" in tx_lower:
            tx_type = "buy"
        elif "bán" in tx_lower:
            tx_type = "sell"
        elif tx_raw in ("null", "", "None") or "lợi tức" in tx_lower or "cổ tức" in tx_lower or "tái đầu tư" in tx_lower:
            tx_type = "dividend"
        else:
            print(f"  ⚠️ Loại giao dịch không rõ '{tx_raw}': {code} {date_raw} — bỏ qua")
            continue

        # Parse date DD/MM/YYYY → YYYY-MM-DD
        try:
            dt = datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            print(f"  ⚠️ Ngày không hợp lệ '{date_raw}': {code} — bỏ qua")
            continue

        nav_f    = float(nav_val or 0)
        units_f  = float(units   or 0)
        amount_f = float(amount  or 0)

        if tx_type in ("buy", "sell") and units_f <= 0:
            print(f"  ⚠️ Số lượng 0: {code} {dt} — bỏ qua")
            continue
        if tx_type == "dividend" and units_f <= 0 and amount_f <= 0:
            print(f"  ⚠️ Lợi tức không có số CCQ lẫn số tiền: {code} {dt} — bỏ qua")
            continue

        trades.append({
            "code":   code,
            "type":   tx_type,
            "date":   dt,
            "units":  round(units_f, 4),
            "nav":    round(nav_f, 2),
            "amount": round(amount_f),
            "note":   f"Nhập từ TCBS Excel",
        })

    return trades


def main():
    parser = argparse.ArgumentParser(description="Import TCBS Excel → Railway trade_log")
    parser.add_argument("--file",        required=True, help="Đường dẫn file .xlsx")
    parser.add_argument("--telegram-id", required=True, help="Telegram user ID")
    parser.add_argument("--server",      default=None,  help="URL Railway server")
    parser.add_argument("--replace",     action="store_true", help="Xóa trade_log cũ trước khi import")
    parser.add_argument("--dry-run",     action="store_true", help="Chỉ parse, không POST")
    args = parser.parse_args()

    xlsx_path = Path(args.file)
    if not xlsx_path.exists():
        print(f"❌ File không tồn tại: {xlsx_path}")
        sys.exit(1)

    # Server URL
    server = args.server
    if not server:
        import os
        server = os.environ.get("MINIAPP_URL")
    if not server:
        try:
            cfg = json.loads((ROOT / "telegram-bot" / "config.json").read_text(encoding="utf-8"))
            server = cfg.get("miniapp_url") or cfg.get("railway_url")
        except Exception:
            pass
    if not server and not args.dry_run:
        print("❌ Cần --server URL hoặc đặt MINIAPP_URL env hoặc miniapp_url trong config.json")
        sys.exit(1)

    print(f"📂 File: {xlsx_path.name}")
    print(f"🔧 Mode: {'DRY RUN' if args.dry_run else 'IMPORT → ' + (server or '')}")
    print(f"👤 Telegram ID: {args.telegram_id}")
    print()

    trades = parse_xlsx(xlsx_path)
    print(f"✅ Parse xong: {len(trades)} giao dịch hợp lệ")
    for t in trades:
        if t['type'] == 'dividend':
            print(f"  {t['date']} {t['code']:10s} {'lợi tức':8s} {t['units']:10.4f} CCQ  giá trị: {t['amount']:,.0f} đ")
        else:
            print(f"  {t['date']} {t['code']:10s} {t['type']:4s} {t['units']:10.2f} CCQ × {t['nav']:,.0f} đ = {t['amount']:,.0f} đ")

    if args.dry_run:
        print("\nDry run — không POST lên server.")
        return

    payload = json.dumps({
        "telegram_id": args.telegram_id,
        "trades":      trades,
        "replace":     args.replace,
    }, ensure_ascii=False).encode("utf-8")

    url = server.rstrip("/") + "/api/admin/import-trades"
    print(f"\n📤 POST → {url}")
    req = _req.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with _req.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        print(f"✅ Server: inserted={result.get('inserted')}, total_trade_log={result.get('total_trade_log')}")
    except Exception as e:
        print(f"❌ Lỗi POST: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
