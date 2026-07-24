# 🧠 Claude Project Brain — Fund Tracker Pro

> Claude đọc file này ĐẦU TIÊN, sau đó đọc `BACKLOG.md` để biết task tiếp theo.

---

## 🔄 SESSION PROTOCOL — Claude tự chạy, không hỏi Harvey

**Mỗi khi bắt đầu session, Claude phải theo đúng thứ tự này:**

```
S1. Đọc BACKLOG.md → tìm task IN_PROGRESS hoặc P0 đầu tiên
    ⚠️ AUTONOMOUS SESSION: chỉ pick task liên quan đến:
       - Web frontend: web.html / web_js.js / web_body.html / build_web.py
       - Native apps: ios/ (iOS) hoặc android/ (Android)
       KHÔNG tự pick task fix backend miniapp_server.py / bot.py trừ khi Harvey yêu cầu.
       Nếu phát hiện bug backend → ghi BACKLOG, KHÔNG implement.
S2. Đọc .claude/memory/project-state.md → lấy context hiện tại
S3. Chạy: git status --short → xem file nào đang thay đổi
S4. Announce rõ ràng: "Tôi sẽ làm [ID]: [mô tả], file sẽ sửa: [list]"
    → Harvey có 30 giây redirect trước khi Claude bắt đầu
S5. Execute → dùng đúng agent, Grep trước Read, parallel calls khi độc lập
S6. Verify → chạy verification gate tương ứng (xem phần VERIFICATION bên dưới)
S7. Update BACKLOG.md (đánh dấu DONE, thêm task mới nếu phát hiện bug)
S8. Cập nhật memory nếu học được điều quan trọng
```

**KHÔNG được:**
- Hỏi "Hôm nay làm gì?" — tự đọc BACKLOG
- Đọc file không liên quan đến task
- Đánh dấu DONE khi chưa qua verification gate
- Restore lệnh /explain, /research, hay bất kỳ lệnh đã bỏ trong bot.py
- Autonomous session tự pick task backend (miniapp_server.py/bot.py) khi không có yêu cầu từ Harvey

## ✅ VERIFICATION GATES

| Task type | Gate |
|-----------|------|
| Python code | `python -m py_compile <file>` |
| Bot command | `python -c "import telegram-bot.bot; print('OK')"` |
| Web server endpoint | `curl -s http://localhost:8443/<path>` |
| DB operation | `SELECT COUNT(*) FROM nav_history` |
| Web frontend JS | Preview tại `http://localhost:8443/web.html?user_id=1`, check console errors |

## 🔍 QA ROUTINE — WEB PARITY CHECK (Harvey yêu cầu 2026-07-24)

**Mỗi khi làm việc với web frontend, Claude phải kiểm tra parity với Mini App:**

```
QA-1. Trang Chủ: Portfolio P&L đúng không? NAV hợp lệ, không 0M?
QA-2. Market board: Hiển thị đủ quỹ? Signal badges (MUA/BÁN/TRUNG LẬP) đúng màu?
QA-3. Phân Tích fund list: Hiện TẤT CẢ quỹ (không phải chỉ 10)?
      Held/watched được pin lên đầu? ★/☆ toggle hoạt động?
QA-4. Phân Tích analysis panel: RSI + BB% + MACD hiển thị đúng giá trị từ API?
      Score đúng? Kết luận đúng? T+2 hiện khi có data?
QA-5. Giao Dịch: Trade form submit OK? Lịch sử giao dịch load đúng?
QA-6. Tín hiệu trong Giao Dịch tab: chỉ hiện quỹ đang nắm (has_position=true)?
QA-7. Gold analysis (Giao Dịch → DCA vàng): RSI vàng, phí bù XAU, phân kỳ đúng?
QA-8. T+2 chart trong Phân Tích: render đúng khi click tab T+2?
QA-9. Console errors: zero errors khi dùng với ?user_id=1?
```

**Features cần parity với Mini App (theo dõi qua WEB-010..018 trong BACKLOG):**
- Tín hiệu phân tích vàng tích hợp vào tab Phân Tích
- So sánh 2 quỹ (fund comparison tool)
- T+2 chart với dữ liệu thật (không phải mock)
- Warning icons cho NAV stale/anomaly giống Mini App
- Quỹ watchlist add/remove từ sidebar Trang Chủ

---

## 🔐 CHÍNH SÁCH DỮ LIỆU — KHÔNG XOÁ/ĐỔI KHI DEPLOY (GOV-006)

**Nguyên tắc**: Không bao giờ xoá hoặc sửa dữ liệu tài khoản/NAV/dự đoán/audit_log của
Harvey hay user khi thay đổi code. Deploy code mới KHÔNG được phép làm mất dữ liệu cũ.

**Quy tắc migration (`db.py`, `schema.sql`, mọi `_ensure_*_table()`):**
- Mọi `ALTER TABLE` phải là **additive**: `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT
  EXISTS`, `CREATE TABLE IF NOT EXISTS` — không bao giờ `DROP COLUMN`/`DROP TABLE`/`RENAME`
  mà không có kế hoạch backfill + xác nhận từ Harvey trước.
- Nếu bắt buộc phải đổi kiểu dữ liệu hoặc rename cột: thêm cột mới trước, backfill dữ liệu,
  chạy song song 1 thời gian, rồi mới xoá cột cũ ở 1 migration RIÊNG (không gộp chung).
- `audit_log` là append-only tuyệt đối — không có hàm nào được phép UPDATE/DELETE dòng đã ghi
  (xem note trong `db.py` phần AUDIT LOG).
- `nav_history` với `source IN ('fixed','manual','confirmed')` không bao giờ bị ghi đè tự động
  (xem `upsert_nav`/`upsert_nav_with_confidence` — đã có bảo vệ PROTECTED_SOURCES).

**Quy tắc script sửa dữ liệu hàng loạt** (`scripts/*.py` chạm DB thật):
- Phải có chế độ **dry-run mặc định** (in ra sẽ đổi gì, không ghi) — chỉ ghi thật khi có flag
  rõ ràng (vd `--apply`, `--confirm`) hoặc xác nhận tương tác.
- Không chạy trực tiếp lên Railway production DB mà không test trước trên bản backup/local
  (xem GOV-002 backup).
- Log số dòng bị ảnh hưởng trước và sau khi chạy để đối chiếu.

**Trước khi tự ý xoá/sửa dữ liệu vì lý do "dọn dẹp" hay "test data còn sót"**: LUÔN hỏi
Harvey xác nhận trước, trừ khi dữ liệu đó do chính session hiện tại tạo ra để test (vd tài
khoản `/beta`, telegram_id âm — xem BETA-001).

---

---

## 📋 PROJECT OVERVIEW

**Tên dự án**: Fund Tracker Pro
**Mô tả**: Hệ thống theo dõi NAV quỹ mở Việt Nam. Sản phẩm chính: Web App (`web.html`) + Python Backend (`miniapp_server.py`). Tích hợp Telegram Bot tuỳ chọn. Hiển thị NAV real-time, tín hiệu kỹ thuật RSI/MACD/BB, quản lý portfolio.
**Loại**: Web App (standalone, có thể mở browser thẳng) + Python Backend + Telegram Bot (optional channel)
**Ngôn ngữ làm việc**: Tiếng Việt
**Giai đoạn hiện tại**:
- **Phase hiện tại — WEB**: Hoàn thiện `web.html` (standalone web app, port 8443). Dùng local trước khi có domain/Railway.
- **Phase tiếp theo — NATIVE**: iOS (SwiftUI) + Android sau khi Web ổn định.
- **KHÔNG implement native trước khi Web hoàn thiện.**

---

## 🛠️ TECH STACK HIỆN TẠI (WEB — SẢN PHẨM CHÍNH)

| Layer        | Công nghệ               | File                                             |
|--------------|-------------------------|--------------------------------------------------|
| Web App      | HTML + Vanilla JS + CSS | `telegram-bot/miniapp/web.html` (built file)     |
| Source       | web_body.html + web_js.js | `telegram-bot/miniapp/` (edit ở đây)           |
| Build script | Python                  | `telegram-bot/miniapp/build_web.py`              |
| Charts       | Chart.js 4.4.4          | CDN trong HTML                                   |
| Fonts        | IBM Plex Mono + DM Sans | Google Fonts trong HTML                          |
| Web Server   | Python (aiohttp)        | `telegram-bot/miniapp/local_dev_server.py` (port 8443) |
| API Backend  | Python                  | `telegram-bot/miniapp/miniapp_server.py`         |
| Bot          | Python + requests       | `telegram-bot/bot.py` (optional Telegram channel)|
| Data Source  | fmarket.vn + TCBS API   | Fetch trong bot.py / miniapp_server.py           |
| DB           | SQLite (local) / PostgreSQL (Railway) | `telegram-bot/miniapp/local_users.db` |

> ℹ️ `dashboard/` (port 8080) là bản cũ, không còn là sản phẩm chính. Giữ lại để tham chiếu.

## 📱 TECH STACK TƯƠNG LAI (NATIVE — PHASE SAU)

| Platform  | Công nghệ  | Ghi chú                                          |
|-----------|------------|--------------------------------------------------|
| iOS       | SwiftUI    | `ios/` (skeleton có sẵn, chưa implement)         |
| Android   | Jetpack Compose hoặc Flutter | Chưa bắt đầu                        |
| Shared    | REST API từ `miniapp_server.py` | Native apps gọi cùng backend        |

> ⚠️ **Không implement native trước khi Web hoàn thiện.**

---

## 📁 CẤU TRÚC THỰC TẾ

```
Fund Tracker Pro/
├── CLAUDE.md                        ← File này
├── BACKLOG.md                       ← Task list (đọc mỗi session)
├── api_docs.md                      ← Tài liệu APIs
├── db_schema.md                     ← Data models
│
├── telegram-bot/
│   ├── bot.py                       ← Telegram bot (optional channel)
│   ├── miniapp_server.py            ← API backend (port 8443)
│   ├── db.py                        ← Database layer
│   ├── config.json                  ← Bot token + profiles (GITIGNORED)
│   └── miniapp/                     ← ★ SẢN PHẨM CHÍNH (WEB APP)
│       ├── web.html                 ← Built file (KHÔNG edit trực tiếp)
│       ├── web_body.html            ← HTML source → edit ở đây
│       ├── web_js.js                ← JS source → edit ở đây
│       ├── build_web.py             ← Build script: body+js → web.html
│       └── local_dev_server.py      ← Dev server port 8443
│
├── dashboard/                       ← Bản cũ (port 8080) — giữ tham chiếu, không phát triển thêm
│   ├── Quy Tracker Dashboard.html
│   └── server.py
│
├── ios/                             ← Native iOS — PHASE SAU khi Web xong
│   ├── ContentView.swift
│   ├── MathEngine.swift
│   ├── NetworkManager.swift
│   └── Models.swift
│
└── .claude/
    ├── agents/                      ← Sub-agent definitions
    └── rules/
        └── python-rules.md
```

---

## 🔗 QUAN HỆ GIỮA CÁC THÀNH PHẦN

```
telegram-bot/miniapp/
  web.html (built)  ←→  local_dev_server.py (port 8443)
                           └── proxy API calls → miniapp_server.py
                                 ├── GET  /api/me              → user profile + portfolio
                                 ├── GET  /api/signals         → RSI/BB/MACD signals
                                 ├── GET  /api/history         → trade history (CCQ + Vàng)
                                 ├── GET  /api/nav_history/<code> → NAV chart data
                                 ├── POST /api/trade/ccq       → mua/bán CCQ
                                 ├── POST /api/trade/gold      → mua/bán vàng
                                 ├── POST /api/nav/manual      → nhập NAV thủ công
                                 └── ... (30+ endpoints)

  Dev URL: http://localhost:8443/web.html?user_id=1
  Prod URL: https://<railway-domain>/web.html (khi có Railway)

telegram-bot/
  bot.py  ←→  fmarket API (trực tiếp)
          ←→  TCBS API (trực tiếp)
          ←→  Telegram API (long-polling)
          ←→  miniapp_server.py (DB shared qua db.py)
```

---

## 🎨 DASHBOARD DESIGN SYSTEM — KHÔNG ĐƯỢC ĐỔI

```css
--bg: #060b14        /* Dark navy background */
--c0: #00e5ff        /* Cyan — primary accent */
--buy: #4ade80       /* Green — MUA signal */
--sell: #f87171      /* Red — BÁN signal */
--mono: 'IBM Plex Mono'
--sans: 'DM Sans'
```

---

## ⚙️ WORKFLOW

1. **PLAN trước, CODE sau** — Tạo `plan.md`. Xác định rõ sửa file nào (dashboard/ hay telegram-bot/).
2. **3 thành phần liên kết** — Khi thêm API endpoint trong `server.py`, kiểm tra JS trong Dashboard có gọi đúng không.
3. **config.json path** — server.py trỏ tới `../telegram-bot/config.json`. Bot trỏ tới `./config.json`.
4. **Dùng /compact** khi context > 80% → ghi quyết định vào `memory.md`.
5. **Báo cáo**: ✅ Đã làm | ⚠️ Vấn đề | 🔜 Bước tiếp.
6. **Notion Sync** — Sau mỗi lần chỉnh sửa file (code, docs, config), lưu tóm tắt thay đổi vào Notion. Xem section 🗂️ NOTION SYNC bên dưới.

---

## 🤖 AI TOOL ROUTING — GEMINI & CLAUDE

Phân công tác vụ giữa Gemini và Claude để tối ưu chi phí token và tận dụng điểm mạnh của từng model:

| Tác vụ | Tool | Lý do |
|--------|------|-------|
| Tìm kiếm web, research API docs | **Gemini** | Context window lớn, free tier rộng |
| Đọc và tóm tắt file dài (>10k tokens) | **Gemini** | Xử lý long-context tốt, tiết kiệm Claude token |
| Phân tích log, debug output lớn | **Gemini** | Phù hợp với data-heavy tasks |
| Viết code, refactor, architecture | **Claude** | Lập luận logic và code quality cao hơn |
| Review bảo mật, kiểm tra edge case | **Claude** | Reasoning phức tạp, multi-step |
| Tạo plan.md, quyết định thiết kế | **Claude** | Cần hiểu context dự án sâu |
| Dịch tài liệu, viết comment | **Gemini** | Tiết kiệm token cho tác vụ đơn giản |

**Quy tắc routing:**
- Trước khi dùng Claude cho tác vụ research/đọc tài liệu → cân nhắc dùng Gemini trước
- Khi context đã >60% và cần tra cứu thêm → chuyển sang Gemini để bảo toàn context Claude
- Output từ Gemini → đưa vào Claude dưới dạng tóm tắt cô đọng (không paste raw)

---

## 🗂️ NOTION SYNC

**Quy tắc bắt buộc**: Sau mỗi lần chỉnh sửa file trong project (code, docs, config, tests), phải đồng bộ tóm tắt lên Notion.

**Những gì cần lưu vào Notion:**
- Tóm tắt thay đổi (file nào, thay đổi gì, lý do)
- Quyết định kiến trúc quan trọng
- Bug đã fix và nguyên nhân gốc rễ
- Kết quả test suite (pass/fail count)
- Các TODO / kế hoạch tiếp theo

**Format entry Notion tiêu chuẩn:**
```
📅 [Ngày] — [Tên tính năng/fix]
📁 File: [tên file]
✏️ Thay đổi: [mô tả ngắn]
🔍 Lý do: [tại sao cần thay đổi]
✅ Kết quả: [outcome hoặc test result]
```

**Lưu ý:** Nếu Notion MCP chưa kết nối, ghi tóm tắt vào `memory.md` trước, sync Notion khi có kết nối.

---

## 🤖 AUTO-SKILL CREATION

Task lặp > 2 lần → đề xuất tạo Skill trong `.claude/skills/`

---

## 🤖 SUB-AGENTS

- `@architect` — Lập kế hoạch, tạo plan.md
- `@frontend-dev` — Dashboard HTML/CSS/JS, Chart.js
- `@python-dev` — server.py + bot.py
- `@qa-tester` — Test curl endpoints, indicators, UI checklist
- `@researcher` — Tìm tài liệu Chart.js, fmarket/TCBS API
- `@reviewer` — Review code, security check
