# 🧠 Claude Project Brain — Fund Tracker Pro

> Claude đọc file này ĐẦU TIÊN, sau đó đọc `BACKLOG.md` để biết task tiếp theo.

---

## 🔄 SESSION PROTOCOL — Claude tự chạy, không hỏi Harvey

**Mỗi khi bắt đầu session, Claude phải theo đúng thứ tự này:**

```
S1. Đọc BACKLOG.md → tìm task IN_PROGRESS hoặc P0 đầu tiên
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

## ✅ VERIFICATION GATES

| Task type | Gate |
|-----------|------|
| Python code | `python -m py_compile <file>` |
| Bot command | `python -c "import telegram-bot.bot; print('OK')"` |
| Server endpoint | `curl -s http://localhost:8080/<path>` |
| DB operation | `SELECT COUNT(*) FROM nav_history` |
| Dashboard JS | Preview trong browser, check console errors |

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
**Mô tả**: Hệ thống theo dõi NAV quỹ mở Việt Nam gồm 3 thành phần: Web Dashboard (HTML/JS), Local Server (Python), Telegram Bot (Python). Hiển thị NAV real-time, tín hiệu kỹ thuật RSI/MACD/BB, quản lý portfolio.
**Loại**: Web App (local) + Python Backend + Telegram Bot
**Ngôn ngữ làm việc**: Tiếng Việt
**Giai đoạn hiện tại**: **WEB-FIRST** — Hoàn thiện Web Dashboard + Python Backend trước. Swift iOS (`ios/`) là phase tiếp theo, chưa phát triển.

---

## 🛠️ TECH STACK HIỆN TẠI (WEB)

| Layer        | Công nghệ               | File                                    |
|--------------|-------------------------|-----------------------------------------|
| Dashboard    | HTML + Vanilla JS + CSS | `dashboard/Quy Tracker Dashboard.html`  |
| Charts       | Chart.js 4.4.4          | CDN trong HTML                          |
| Fonts        | IBM Plex Mono + DM Sans | Google Fonts trong HTML                 |
| Server       | Python `http.server`    | `dashboard/server.py` (port 8080)       |
| Bot          | Python + requests       | `telegram-bot/bot.py`                   |
| Scheduling   | `schedule` library      | Trong bot.py                            |
| Data Source  | fmarket.vn + TCBS API   | Fetch trong bot.py                      |
| NAV Storage  | `nav_data.json` (delta) | `dashboard/nav_data.json`               |
| History Base | `HIST.chart` (embedded) | Baked vào Dashboard.html (~797KB)       |

## 📱 TECH STACK TƯƠNG LAI (iOS — CHƯA BẮT ĐẦU)

| Layer     | Công nghệ  | Ghi chú                                 |
|-----------|------------|-----------------------------------------|
| UI        | SwiftUI    | `ios/ContentView.swift` (skeleton)      |
| Math      | Swift      | `ios/MathEngine.swift` (đã sync threshold vs Python) |
| Network   | URLSession | `ios/NetworkManager.swift` (skeleton)   |
| Storage   | UserDefaults / Keychain | Chưa implement                 |

> ⚠️ iOS skeleton chỉ để giữ chỗ kiến trúc. **Không được implement iOS trước khi Web hoàn thiện.**

---

## 📁 CẤU TRÚC THỰC TẾ

```
Fund Tracker Pro/
├── claude.md                        ← File này
├── memory.md                        ← Context phiên trước (đọc khi mở)
├── api_docs.md                      ← Tài liệu APIs
├── db_schema.md                     ← Data models
├── migration_log.md                 ← Nhật ký thay đổi
│
├── dashboard/
│   ├── Quy Tracker Dashboard.html   ← Web UI v4.2 (dark theme, Chart.js)
│   └── server.py                    ← Local server port 8080
│
├── telegram-bot/
│   ├── bot.py                       ← Telegram bot
│   ├── config.json                  ← Bot token + profiles (GITIGNORED)
│   ├── config.example.json
│   ├── requirements.txt
│   └── setup_mac.sh
│
├── ios/                             ← Swift skeleton — PHASE 2 (sau khi Web hoàn thiện)
│   ├── ContentView.swift            ← UI skeleton
│   ├── MathEngine.swift             ← Đã sync threshold với Python
│   ├── NetworkManager.swift         ← Skeleton
│   └── Models.swift                 ← Data models skeleton
│
└── .claude/
    ├── agents/
    │   ├── frontend-dev.md          ← Dashboard HTML/CSS/JS
    │   ├── python-dev.md            ← server.py + bot.py
    │   ├── qa-tester.md             ← Test curl + Python + UI checklist
    │   ├── architect.md             ← Lập kế hoạch
    │   ├── researcher.md            ← Tìm tài liệu
    │   └── reviewer.md              ← Review code
    └── rules/
        └── python-rules.md
```

---

## 🔗 QUAN HỆ GIỮA CÁC THÀNH PHẦN

```
dashboard/
  Quy Tracker Dashboard.html  ←→  server.py (port 8080)
                                    ├── GET  /nav-data        → nav_data.json (delta)
                                    ├── POST /save-nav        → ghi vào nav_data.json
                                    ├── GET/POST /bot-config  → telegram-bot/config.json
                                    ├── POST /tcbs-auth/otp   → proxy TCBS
                                    └── POST /tcbs-auth/verify → lưu token → config.json

  HIST.chart (797KB embedded)  ←─ Full history từ ngày thành lập → 2026-04-02
  nav_data.json (delta, ~2KB)  ←─ Chỉ điểm NAV SAU HIST cutoff

telegram-bot/
  bot.py  ←→  fmarket API (trực tiếp)
          ←→  TCBS API (trực tiếp)
          ←→  Telegram API (long-polling)
          ─→  [TODO] POST localhost:8080/save-nav (sau mỗi job_morning)
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
