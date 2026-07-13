"""
PostgreSQL connection layer — Fund Tracker Pro
ThreadedConnectionPool: safe cho bot.py multi-thread (scheduler + long-polling).
Usage:
    from db import db_conn, set_app_uid, upsert_nav, save_signal
"""
import os
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None

SETTLEMENT_DAYS = {"T1": 1, "T2": 2, "T3": 3}


def _migrate_data_src_enum() -> None:
    """Thêm các giá trị dùng trong NAV confidence workflow (provisional/manual/
    pending_confirm/confirmed/fixed) vào enum data_src nếu chưa có. Thiếu bất kỳ
    giá trị nào ở đây sẽ khiến MỌI câu SELECT/UPDATE lọc theo giá trị đó crash với
    InvalidTextRepresentation (từng gây lỗi 502 cho /api/admin/nav/pending vì
    'pending_confirm' chưa từng được thêm — chỉ 'manual'/'fixed' được migrate).
    ALTER TYPE ADD VALUE phải chạy ngoài transaction → dùng autocommit connection riêng."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return
    try:
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(0)  # autocommit
        with conn.cursor() as cur:
            # Kiểm tra xem source column có phải là ENUM không
            cur.execute("""
                SELECT udt_name FROM information_schema.columns
                WHERE table_name = 'nav_history' AND column_name = 'source'
            """)
            row = cur.fetchone()
            if not row or row[0] == 'text':
                conn.close()
                return  # TEXT column, không cần migrate
            # Thêm các giá trị mới vào enum (IF NOT EXISTS từ PG 9.3+)
            for val in ('manual', 'fixed', 'provisional', 'pending_confirm', 'confirmed'):
                try:
                    cur.execute(f"ALTER TYPE data_src ADD VALUE IF NOT EXISTS '{val}'")
                    logger.info("Migrated data_src enum: added '%s'", val)
                except Exception as e:
                    logger.debug("data_src enum '%s' skip: %s", val, e)
        conn.close()
    except Exception as e:
        logger.warning("_migrate_data_src_enum failed (non-fatal): %s", e)


def _migrate_nav_confidence_cols() -> None:
    """Thêm pending_nav + confirmed_at vào nav_history nếu chưa có."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE nav_history
                    ADD COLUMN IF NOT EXISTS pending_nav   NUMERIC,
                    ADD COLUMN IF NOT EXISTS confirmed_at  TIMESTAMPTZ
            """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("_migrate_nav_confidence_cols (non-fatal): %s", e)


def init_pool(min_conn: int = 1, max_conn: int = 5) -> None:
    global _pool
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set — PostgreSQL disabled")
        return
    _migrate_data_src_enum()      # Chạy trước khi mở pool
    _migrate_nav_confidence_cols()
    _pool = ThreadedConnectionPool(min_conn, max_conn, db_url)
    logger.info("PostgreSQL pool initialised (min=%d max=%d)", min_conn, max_conn)


def is_available() -> bool:
    return _pool is not None


@contextmanager
def get_conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() first")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def set_app_uid(conn, user_uuid: str) -> None:
    """Activate RLS for this connection — call before any user-scoped query."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL app.uid = %s", (user_uuid,))


# ─── AUDIT LOG (GOV-001) ──────────────────────────────────────────────────────
# Ghi lại MỌI thay đổi trên dữ liệu nhạy cảm: tier/thanh toán, mã giảm giá,
# NAV thủ công/xác nhận, giao dịch CCQ/vàng — để truy vết khi có lỗi hoặc tranh
# chấp. Không bao giờ xoá/sửa dòng audit_log (append-only). log_audit() KHÔNG
# BAO GIỜ được phép làm hỏng thao tác chính — mọi lỗi ghi log chỉ log cảnh báo,
# không raise, không rollback nghiệp vụ đang chạy.

def _ensure_audit_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id            BIGSERIAL PRIMARY KEY,
                actor_id      BIGINT,
                action        TEXT NOT NULL,
                target_table  TEXT,
                target_id     TEXT,
                before_state  JSONB,
                after_state   JSONB,
                note          TEXT,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC)")


def log_audit(actor_id, action: str, target_table: str = None, target_id: str = None,
              before: dict = None, after: dict = None, note: str = None) -> None:
    """Ghi 1 dòng audit. actor_id=None nghĩa là hệ thống tự động thực hiện (cron,
    webhook thanh toán...). Không bao giờ raise ra ngoài — lỗi ghi audit không
    được phép làm hỏng thao tác nghiệp vụ chính đang chạy."""
    if not is_available():
        return
    try:
        import json as _json
        with get_conn() as conn:
            _ensure_audit_table(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO audit_log (actor_id, action, target_table, target_id, before_state, after_state, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    int(actor_id) if actor_id not in (None, "") else None,
                    action, target_table, str(target_id) if target_id is not None else None,
                    _json.dumps(before, default=str) if before is not None else None,
                    _json.dumps(after, default=str) if after is not None else None,
                    note,
                ))
    except Exception as e:
        logger.warning(f"[audit] log_audit failed (non-fatal): action={action} err={e}")


def get_audit_log(limit: int = 100, action: str = None, actor_id=None) -> "list[dict]":
    """Xem lịch sử audit gần đây — dùng cho admin dashboard (GOV-004)."""
    if not is_available():
        return []
    with get_conn() as conn:
        _ensure_audit_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filters, params = [], []
            if action:
                filters.append("action = %s"); params.append(action)
            if actor_id is not None:
                filters.append("actor_id = %s"); params.append(int(actor_id))
            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            params.append(limit)
            cur.execute(f"""
                SELECT id, actor_id, action, target_table, target_id,
                       before_state, after_state, note, created_at::text
                FROM audit_log {where}
                ORDER BY id DESC LIMIT %s
            """, params)
            return [dict(r) for r in cur.fetchall()]


# ─── PAYMENT DEDUP (GOV-003) ──────────────────────────────────────────────────
# Cổng thanh toán (MoMo IPN, Telegram Stars) có thể gọi webhook 2 lần cho CÙNG 1
# giao dịch (network retry khi không nhận response đủ nhanh) — nếu không chặn,
# extend_pro() sẽ cộng dồn 2 lần ngày Pro cho cùng 1 lần trả tiền. record_payment_once()
# dùng UNIQUE (provider, charge_id) để chỉ cho phép xử lý 1 lần, INSERT thứ 2 trở đi
# trả về False (không raise) để caller biết đây là duplicate và bỏ qua + log audit.

def _ensure_payment_dedup_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS processed_payments (
                provider    TEXT NOT NULL,
                charge_id   TEXT NOT NULL,
                telegram_id BIGINT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (provider, charge_id)
            )
        """)


def record_payment_once(provider: str, charge_id: str, telegram_id=None) -> bool:
    """True nếu đây là lần đầu ghi nhận (xử lý bình thường), False nếu đã xử lý
    trước đó (duplicate webhook — caller PHẢI bỏ qua, không gọi extend_pro lần nữa)."""
    if not is_available():
        return True  # DB không khả dụng — không thể dedup, để caller xử lý như bình thường
    if not provider or not charge_id:
        return True
    with get_conn() as conn:
        _ensure_payment_dedup_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO processed_payments (provider, charge_id, telegram_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (provider, charge_id) DO NOTHING
                """,
                (provider, str(charge_id), int(telegram_id) if telegram_id not in (None, "") else None),
            )
            return cur.rowcount > 0


# ─── NAV ────────────────────────────────────────────────────────────────────

def upsert_nav(fund_code: str, nav_date: date, nav: float, source: str = "fmarket") -> None:
    if not is_available():
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO nav_history (fund_code, nav_date, nav, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (fund_code, nav_date) DO UPDATE
                    SET nav        = CASE
                            WHEN nav_history.source IN ('fixed', 'manual') THEN nav_history.nav
                            ELSE EXCLUDED.nav
                        END,
                        source     = CASE
                            WHEN nav_history.source = 'fixed'  THEN 'fixed'
                            WHEN nav_history.source = 'manual' THEN 'fixed'
                            ELSE EXCLUDED.source
                        END,
                        fetched_at = NOW()
                WHERE nav_history.source NOT IN ('fixed', 'manual')
            """, (fund_code, nav_date, nav, source))
    logger.debug("upsert_nav %s %s %.4f src=%s", fund_code, nav_date, nav, source)
    # Sau khi API data confirmed → unify pending Pro drafts nếu khớp
    try:
        unify_nav_drafts(fund_code, nav_date, nav)
    except Exception as e:
        logger.debug("unify_nav_drafts skip: %s", e)


# ─── NAV CONFIDENCE WORKFLOW ─────────────────────────────────────────────────
#
# Source state machine:
#   provisional     → fetched today == yesterday (API chưa publish, giá trị cũ)
#   tcbs / fmarket  → fetched today != yesterday (giá trị mới, chưa xác nhận)
#   manual          → user nhập tay
#   pending_confirm → fetch ≠ manual, cần admin xác nhận
#   confirmed       → fetch ≈ manual HOẶC admin đã chọn
#   fixed           → admin khóa cứng vĩnh viễn
#
# Priority hiển thị: fixed > confirmed > manual > tcbs/fmarket > provisional

CONFIDENCE_EPSILON = 1.0   # Trong vòng 1 VND = cùng giá trị (NAV thường 10k-20k)
PROTECTED_SOURCES  = ('fixed', 'confirmed')   # không bao giờ bị ghi đè tự động
TRUSTED_SOURCES    = ('fixed', 'confirmed', 'manual')  # không bị tính là provisional


def upsert_nav_with_confidence(
    fund_code: str,
    nav_date: date,
    nav_fetched: float,
    source_api: str,
    yesterday_nav: float | None = None,
) -> str:
    """
    Smart upsert với confidence tracking.

    Returns: 'inserted' | 'provisional' | 'updated' | 'confirmed' |
             'pending_confirm' | 'skipped'
    """
    if not is_available():
        return 'skipped'

    # Detect provisional: fetch == yesterday (API chưa update NAV mới)
    is_prov = (
        yesterday_nav is not None
        and abs(nav_fetched - yesterday_nav) <= CONFIDENCE_EPSILON
    )
    effective_source = 'provisional' if is_prov else source_api

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nav, source, pending_nav FROM nav_history "
                "WHERE fund_code=%s AND nav_date=%s",
                (fund_code, nav_date)
            )
            row = cur.fetchone()

        if row is None:
            # INSERT mới
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO nav_history (fund_code, nav_date, nav, source) "
                    "VALUES (%s, %s, %s, %s)",
                    (fund_code, nav_date, nav_fetched, effective_source)
                )
            logger.debug("nav_confidence INSERT %s %s %.0f src=%s",
                         fund_code, nav_date, nav_fetched, effective_source)
            return 'provisional' if is_prov else 'inserted'

        existing_nav, existing_source, existing_pending = row

        # ── Immune states ─────────────────────────────────────────────────────
        if existing_source in ('fixed',):
            return 'skipped'

        if existing_source == 'confirmed':
            # Cross-check: nếu fetch mới khác confirmed → log WARNING nhưng không đổi
            if (not is_prov
                    and abs(nav_fetched - float(existing_nav)) > CONFIDENCE_EPSILON):
                logger.warning(
                    "⚠ NAV đã confirmed nhưng fetch mới khác: %s %s "
                    "confirmed=%.0f fetch=%.0f — cần admin kiểm tra",
                    fund_code, nav_date, existing_nav, nav_fetched
                )
            return 'skipped'

        # ── Manual source ─────────────────────────────────────────────────────
        if existing_source == 'manual':
            if is_prov:
                return 'skipped'  # provisional không ghi đè manual

            if abs(nav_fetched - float(existing_nav)) <= CONFIDENCE_EPSILON:
                # Fetch đồng ý với manual → xác nhận!
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE nav_history SET source='confirmed', pending_nav=NULL, "
                        "confirmed_at=NOW(), fetched_at=NOW() "
                        "WHERE fund_code=%s AND nav_date=%s",
                        (fund_code, nav_date)
                    )
                logger.info("✅ NAV confirmed tự động: %s %s nav=%.0f",
                            fund_code, nav_date, existing_nav)
                return 'confirmed'
            else:
                # Mâu thuẫn → cần admin xác nhận
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE nav_history SET source='pending_confirm', "
                        "pending_nav=%s, fetched_at=NOW() "
                        "WHERE fund_code=%s AND nav_date=%s",
                        (nav_fetched, fund_code, nav_date)
                    )
                logger.warning(
                    "⚠ pending_confirm: %s %s manual=%.0f fetch=%.0f",
                    fund_code, nav_date, existing_nav, nav_fetched
                )
                return 'pending_confirm'

        # ── Pending confirm: update giá trị fetch mới nhất ───────────────────
        if existing_source == 'pending_confirm':
            if not is_prov:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE nav_history SET pending_nav=%s, fetched_at=NOW() "
                        "WHERE fund_code=%s AND nav_date=%s",
                        (nav_fetched, fund_code, nav_date)
                    )
            return 'pending_confirm'

        # ── Auto sources: provisional, tcbs, fmarket ──────────────────────────
        if is_prov and existing_source in ('tcbs', 'fmarket'):
            return 'skipped'  # không downgrade real data → provisional

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE nav_history SET nav=%s, source=%s, fetched_at=NOW() "
                "WHERE fund_code=%s AND nav_date=%s",
                (nav_fetched, effective_source, fund_code, nav_date)
            )
        return 'provisional' if is_prov else 'updated'


def get_pending_confirms() -> list[dict]:
    """Trả danh sách NAV cần admin xác nhận (source='pending_confirm')."""
    if not is_available():
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT fund_code, nav_date::text, nav AS manual_nav,
                       pending_nav AS fetch_nav, fetched_at::text
                FROM nav_history
                WHERE source = 'pending_confirm'
                ORDER BY nav_date DESC, fund_code
            """)
            return [dict(r) for r in cur.fetchall()]


def resolve_nav_confirm(fund_code: str, nav_date_str: str, choice: str, actor_id=None) -> bool:
    """
    Admin xác nhận NAV.
    choice: 'manual' → giữ nav hiện tại (từ user)
            'fetch'  → dùng pending_nav (từ API)
    Returns True nếu thành công.
    """
    if not is_available():
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nav, pending_nav FROM nav_history "
                "WHERE fund_code=%s AND nav_date=%s AND source='pending_confirm'",
                (fund_code, nav_date_str)
            )
            row = cur.fetchone()
        if not row:
            return False
        existing_nav, pending_nav = row
        final_nav = float(existing_nav) if choice == 'manual' else float(pending_nav)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE nav_history SET nav=%s, source='confirmed', pending_nav=NULL, "
                "confirmed_at=NOW() WHERE fund_code=%s AND nav_date=%s",
                (final_nav, fund_code, nav_date_str)
            )
        logger.info("✅ Admin confirmed %s %s choice=%s final=%.0f",
                    fund_code, nav_date_str, choice, final_nav)
    log_audit(actor_id, "nav.confirm", "nav_history", f"{fund_code}:{nav_date_str}",
              before={"manual_nav": float(existing_nav), "fetch_nav": float(pending_nav) if pending_nav else None},
              after={"final_nav": final_nav, "choice": choice})
    return True


def get_nav_series(fund_code: str, days: int = 90) -> list[dict]:
    """Return list of {nav_date, nav} dicts, newest-first."""
    if not is_available():
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT nav_date, nav
                FROM nav_history
                WHERE fund_code = %s
                  AND nav_date >= CURRENT_DATE - %s
                ORDER BY nav_date DESC
            """, (fund_code, days))
            return [dict(r) for r in cur.fetchall()]


# ─── SIGNALS ────────────────────────────────────────────────────────────────

def _ensure_signal_cols(conn) -> None:
    """Add new columns to buy_signals if they don't exist yet (safe to call every startup)."""
    new_cols = [
        ("chg_pct",  "NUMERIC"),
        ("chg7d",    "NUMERIC"),
        ("chg30d",   "NUMERIC"),
        ("details",  "JSONB"),
        ("nav_date", "DATE"),
        ("ma20",     "NUMERIC"),
        ("ma50",     "NUMERIC"),
    ]
    with conn.cursor() as cur:
        for col, typ in new_cols:
            cur.execute(f"""
                ALTER TABLE buy_signals ADD COLUMN IF NOT EXISTS {col} {typ}
            """)


def save_signal(
    fund_code: str,
    signal_date: date,
    strength: str,
    score: int,
    nav_at_signal: float,
    indicators: dict | None = None,
    settlement_rule: str = "T2",
) -> str | None:
    """
    Persist a signal for any strength (buy/hold/reduce/strong_buy/strong_reduce).
    indicators dict keys: rsi, bb_pct, macd_hist, ma20_vs_ma50, ma20, ma50, momentum_30d,
                          chg_pct, chg7d, chg30d, details (list), nav_date (str)
    """
    if not is_available():
        return None
    import json as _json
    ind = indicators or {}
    exec_date = _calc_exec_date(signal_date, settlement_rule)
    nav_date_val = None
    if ind.get("nav_date"):
        try:
            nav_date_val = date.fromisoformat(str(ind["nav_date"]))
        except (ValueError, TypeError):
            pass
    with get_conn() as conn:
        _ensure_signal_cols(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO buy_signals (
                    fund_code, signal_date, strength, score,
                    rsi, bb_pct, macd_hist, ma20_vs_ma50, momentum_30d,
                    nav_at_signal, settlement_rule, est_exec_date,
                    chg_pct, chg7d, chg30d, details, nav_date, ma20, ma50
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (fund_code, signal_date) DO UPDATE SET
                    strength      = EXCLUDED.strength,
                    score         = EXCLUDED.score,
                    rsi           = EXCLUDED.rsi,
                    bb_pct        = EXCLUDED.bb_pct,
                    macd_hist     = EXCLUDED.macd_hist,
                    nav_at_signal = EXCLUDED.nav_at_signal,
                    est_exec_date = EXCLUDED.est_exec_date,
                    chg_pct       = EXCLUDED.chg_pct,
                    chg7d         = EXCLUDED.chg7d,
                    chg30d        = EXCLUDED.chg30d,
                    details       = EXCLUDED.details,
                    nav_date      = EXCLUDED.nav_date,
                    ma20          = EXCLUDED.ma20,
                    ma50          = EXCLUDED.ma50
                RETURNING id
            """, (
                fund_code, signal_date, strength, score,
                ind.get("rsi"), ind.get("bb_pct"), ind.get("macd_hist"),
                int(bool(ind.get("ma20_vs_ma50"))), ind.get("momentum_30d"),
                nav_at_signal, settlement_rule, exec_date,
                ind.get("chg_pct"), ind.get("chg7d"), ind.get("chg30d"),
                _json.dumps(ind.get("details") or []), nav_date_val,
                ind.get("ma20"), ind.get("ma50"),
            ))
            row = cur.fetchone()
            return str(row[0]) if row else None


def backfill_settlement_nav(fund_code: str, signal_date: date, nav_at_settlement: float) -> None:
    """Retroactively fill nav_at_settlement + compute accuracy."""
    if not is_available():
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE buy_signals
                SET nav_at_settlement = %s,
                    signal_accuracy_pct = CASE
                        WHEN nav_at_signal > 0 THEN
                            ROUND(((nav_at_signal - %s) / nav_at_signal * 100)::NUMERIC, 3)
                        ELSE NULL
                    END
                WHERE fund_code = %s AND signal_date = %s
            """, (nav_at_settlement, nav_at_settlement, fund_code, signal_date))


# ─── USERS ──────────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, enc_salt: bytes, auth_hash: bytes) -> str:
    """Return user UUID. Creates user on first call."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE users SET last_active_at = NOW() WHERE telegram_id = %s",
                    (telegram_id,)
                )
                return str(row[0])
            cur.execute("""
                INSERT INTO users (telegram_id, enc_salt, auth_hash)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (telegram_id, psycopg2.Binary(enc_salt), psycopg2.Binary(auth_hash)))
            return str(cur.fetchone()[0])


def get_user_uuid(telegram_id: int) -> str | None:
    if not is_available():
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
            return str(row[0]) if row else None


# ─── HELPERS ────────────────────────────────────────────────────────────────

def _calc_exec_date(signal_date: date, settlement_rule: str) -> date:
    """Add T+N business days (simplified: skips Sat/Sun, not VN holidays)."""
    n = SETTLEMENT_DAYS.get(settlement_rule, 2)
    d = signal_date
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            added += 1
    return d


# ─── USERS (EXTENDED) ───────────────────────────────────────────────────────

def get_user_info(telegram_id: int) -> "dict | None":
    """Return {id: str, enc_salt: bytes} for an existing user, or None."""
    if not is_available():
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, enc_salt FROM users WHERE telegram_id = %s",
                (telegram_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"id": str(row[0]), "enc_salt": bytes(row[1])}


# ─── PORTFOLIOS ─────────────────────────────────────────────────────────────

def get_or_create_portfolio(user_uuid: str, name_enc: bytes) -> str:
    """Return portfolio_id for user. Creates one (with encrypted name) if none exists."""
    with get_conn() as conn:
        set_app_uid(conn, user_uuid)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM portfolios WHERE user_id = %s LIMIT 1",
                (user_uuid,)
            )
            row = cur.fetchone()
            if row:
                return str(row[0])
            cur.execute("""
                INSERT INTO portfolios (user_id, name_enc)
                VALUES (%s, %s)
                RETURNING id
            """, (user_uuid, psycopg2.Binary(name_enc)))
            return str(cur.fetchone()[0])


def get_portfolio_id(user_uuid: str) -> "str | None":
    """Return portfolio_id if it exists, None otherwise (no creation)."""
    if not is_available():
        return None
    with get_conn() as conn:
        set_app_uid(conn, user_uuid)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM portfolios WHERE user_id = %s LIMIT 1",
                (user_uuid,)
            )
            row = cur.fetchone()
            return str(row[0]) if row else None


# ─── TRANSACTIONS ────────────────────────────────────────────────────────────

def add_transaction(
    user_uuid: str,
    portfolio_id: str,
    fund_code: str,
    tx_type: str,
    order_date: date,
    units_enc: bytes,
    amount_enc: bytes,
    nav_at_order: "float | None" = None,
) -> str:
    """Append to immutable transaction ledger. Returns new tx UUID."""
    with get_conn() as conn:
        set_app_uid(conn, user_uuid)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO transactions (
                    portfolio_id, fund_code, tx_type, order_date,
                    nav_at_order, units_enc, amount_enc
                ) VALUES (%s, %s, %s::tx_type, %s, %s, %s, %s)
                RETURNING id
            """, (
                portfolio_id, fund_code, tx_type, order_date,
                nav_at_order,
                psycopg2.Binary(units_enc),
                psycopg2.Binary(amount_enc),
            ))
            return str(cur.fetchone()[0])


# ─── HOLDINGS ────────────────────────────────────────────────────────────────

def upsert_holding(
    user_uuid: str,
    portfolio_id: str,
    fund_code: str,
    units_enc: bytes,
    avg_cost_enc: bytes,
) -> None:
    """Insert or update a holding (caller computes new units/avg_cost before encrypting)."""
    with get_conn() as conn:
        set_app_uid(conn, user_uuid)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO holdings (portfolio_id, fund_code, units_enc, avg_cost_enc)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (portfolio_id, fund_code) DO UPDATE SET
                    units_enc    = EXCLUDED.units_enc,
                    avg_cost_enc = EXCLUDED.avg_cost_enc,
                    updated_at   = NOW()
            """, (
                portfolio_id, fund_code,
                psycopg2.Binary(units_enc),
                psycopg2.Binary(avg_cost_enc),
            ))


def get_holdings_raw(user_uuid: str, portfolio_id: str) -> "list[dict]":
    """Return [{fund_code, units_enc, avg_cost_enc}] — caller decrypts with their key."""
    if not is_available():
        return []
    with get_conn() as conn:
        set_app_uid(conn, user_uuid)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT fund_code,
                       units_enc::bytea    AS units_enc,
                       avg_cost_enc::bytea AS avg_cost_enc
                FROM holdings
                WHERE portfolio_id = %s
                ORDER BY fund_code
            """, (portfolio_id,))
            return [
                {
                    "fund_code":    r["fund_code"],
                    "units_enc":    bytes(r["units_enc"]),
                    "avg_cost_enc": bytes(r["avg_cost_enc"]),
                }
                for r in cur.fetchall()
            ]


# ─── BACKFILL ────────────────────────────────────────────────────────────────

def get_pending_backfill(as_of: date) -> "list[dict]":
    """Signals past est_exec_date whose nav_at_settlement is still NULL."""
    if not is_available():
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT fund_code, signal_date, est_exec_date, settlement_rule
                FROM buy_signals
                WHERE est_exec_date <= %s
                  AND nav_at_settlement IS NULL
                ORDER BY est_exec_date
            """, (as_of,))
            return [dict(r) for r in cur.fetchall()]


def get_nav_on_or_after(fund_code: str, target_date: date) -> "float | None":
    """Find the first nav_history entry on or after target_date (within 7 calendar days)."""
    if not is_available():
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nav FROM nav_history
                WHERE fund_code = %s
                  AND nav_date >= %s
                  AND nav_date <= %s + INTERVAL '7 days'
                ORDER BY nav_date ASC
                LIMIT 1
            """, (fund_code, target_date, target_date))
            row = cur.fetchone()
            return float(row[0]) if row else None


# ─── FUNDS MASTER ────────────────────────────────────────────────────────────

def get_all_active_funds() -> "list[dict]":
    """
    Trả về tất cả quỹ đang active trong funds_master.
    Returns: [{code, name, fmarket_id, tcbs, source}]
    Dùng cho harvest jobs và /navall command.
    """
    if not is_available():
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT code, name, fmarket_id, tcbs, source
                FROM funds_master
                WHERE active = true
                ORDER BY code
            """)
            return [dict(r) for r in cur.fetchall()]


def get_nav_latest(fund_code: str) -> "dict | None":
    """Trả về NAV mới nhất của 1 quỹ: {nav_date, nav}"""
    if not is_available():
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT nav_date, nav
                FROM nav_history
                WHERE fund_code = %s
                ORDER BY nav_date DESC
                LIMIT 1
            """, (fund_code,))
            row = cur.fetchone()
            return dict(row) if row else None


# ─── BOT PROFILES (users registered via /register) ──────────────────────────
# Bảng nhẹ, KHÔNG dùng chung với `users` (bảng đó gắn với hệ mã hoá portfolio,
# auth_hash/enc_salt NOT NULL — không phù hợp cho đăng ký công khai qua /register).

def _ensure_bot_profiles_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_profiles (
                telegram_id   BIGINT PRIMARY KEY,
                name          TEXT NOT NULL,
                is_admin      BOOLEAN NOT NULL DEFAULT false,
                is_active     BOOLEAN NOT NULL DEFAULT true,
                watched_funds TEXT[] NOT NULL DEFAULT '{}',
                monthly_dca   NUMERIC DEFAULT 0,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def _row_to_profile(r: dict) -> dict:
    return {
        "name":          r["name"],
        "telegram_id":   str(r["telegram_id"]),
        "watched_funds": list(r["watched_funds"] or []),
        "monthly_dca":   float(r["monthly_dca"] or 0),
        "is_admin":      bool(r["is_admin"]),
    }


def list_profiles() -> "list[dict]":
    """Tất cả profile đang active. Trả về [] nếu DB chưa sẵn sàng hoặc bảng rỗng."""
    if not is_available():
        return []
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT telegram_id, name, watched_funds, monthly_dca, is_admin
                FROM bot_profiles WHERE is_active = true ORDER BY created_at
            """)
            return [_row_to_profile(r) for r in cur.fetchall()]


def find_profile(telegram_id) -> "dict | None":
    if not is_available():
        return None
    try:
        tg = int(telegram_id)
    except (TypeError, ValueError):
        return None
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT telegram_id, name, watched_funds, monthly_dca, is_admin
                FROM bot_profiles WHERE telegram_id = %s AND is_active = true
            """, (tg,))
            r = cur.fetchone()
            return _row_to_profile(r) if r else None


def create_profile(telegram_id, name: str, watched_funds: "list[str]", is_admin: bool = False) -> dict:
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO bot_profiles (telegram_id, name, watched_funds, is_admin)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    is_active = true, name = EXCLUDED.name, updated_at = NOW()
                RETURNING telegram_id, name, watched_funds, monthly_dca, is_admin
            """, (tg, name, watched_funds, is_admin))
            return _row_to_profile(cur.fetchone())


def delete_profile(telegram_id) -> bool:
    """Soft-delete (is_active=false) — giữ lịch sử, /register có thể tạo lại."""
    if not is_available():
        return False
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE bot_profiles SET is_active = false WHERE telegram_id = %s", (tg,))
            return cur.rowcount > 0


def ensure_watched_funds(telegram_id, name: str, funds: "list[str]", is_admin: bool = False) -> dict:
    """Idempotent: tạo profile nếu chưa có, hoặc merge thêm watched_funds còn thiếu
    (union, KHÔNG xoá quỹ user đã tự thêm). Dùng cho reconcile admin lúc startup."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT watched_funds FROM bot_profiles WHERE telegram_id = %s", (tg,))
            row = cur.fetchone()
            if row is None:
                cur.execute("""
                    INSERT INTO bot_profiles (telegram_id, name, watched_funds, is_admin)
                    VALUES (%s, %s, %s, %s)
                """, (tg, name, funds, is_admin))
                return {"created": True, "changed": True, "watched_funds": funds}
            existing = list(row["watched_funds"] or [])
            merged = existing + [f for f in funds if f not in existing]
            if merged != existing:
                cur.execute(
                    "UPDATE bot_profiles SET watched_funds = %s, updated_at = NOW() WHERE telegram_id = %s",
                    (merged, tg),
                )
                return {"created": False, "changed": True, "watched_funds": merged}
            return {"created": False, "changed": False, "watched_funds": existing}


def set_watched_funds(telegram_id, funds: "list[str]") -> dict:
    """Ghi đè (replace, KHÔNG merge) watched_funds cho user. Dùng khi user tự sửa
    danh sách theo dõi qua Mini App (khác với ensure_watched_funds — union merge)."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE bot_profiles SET watched_funds = %s, updated_at = NOW()
                WHERE telegram_id = %s
                RETURNING telegram_id, name, watched_funds, monthly_dca, is_admin
            """, (funds, tg))
            row = cur.fetchone()
            return _row_to_profile(row) if row else {}


def migrate_profiles_from_config(profiles: "list[dict]", admin_telegram_id: str = "") -> int:
    """One-time migration: nhận list profile dict từ config.json, insert vào bot_profiles
    nếu chưa tồn tại (không ghi đè nếu đã có). Trả về số profile đã insert mới."""
    if not is_available():
        return 0
    inserted = 0
    with get_conn() as conn:
        _ensure_bot_profiles_table(conn)
        with conn.cursor() as cur:
            for p in profiles:
                tg_raw = str(p.get("telegram_id", "")).strip()
                if not tg_raw.lstrip("-").isdigit():
                    continue  # bỏ qua placeholder kiểu "CHUA_CO_ID"
                tg = int(tg_raw)
                name = p.get("name", f"User_{tg}")
                funds = p.get("watched_funds", []) or []
                dca = float(p.get("monthly_dca", 0) or 0)
                is_admin = tg_raw == str(admin_telegram_id).strip()
                cur.execute("""
                    INSERT INTO bot_profiles (telegram_id, name, watched_funds, monthly_dca, is_admin)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (telegram_id) DO NOTHING
                """, (tg, name, funds, dca, is_admin))
                inserted += cur.rowcount
    return inserted


# ─── USER TIERS (freemium gate — GATE-001/002) ───────────────────────────────
# Free = giới hạn watched_funds (xem FREE_FUND_LIMIT trong miniapp_server.py).
# Pro = unlimited + deep analysis + gold + alerts. pro_expires_at NULL = vĩnh viễn
# (vd admin cấp tay); có giá trị = hết hạn tự động downgrade khi get_tier() chạy.

def _ensure_user_tiers_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_tiers (
                telegram_id     BIGINT PRIMARY KEY,
                tier            TEXT NOT NULL DEFAULT 'free',
                pro_expires_at  TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def get_tier(telegram_id) -> dict:
    """Trả {tier, pro_expires_at}. Tự downgrade về 'free' nếu pro đã hết hạn.
    Mặc định 'free' nếu DB chưa sẵn sàng hoặc user chưa có row."""
    if not is_available():
        return {"tier": "free", "pro_expires_at": None}
    try:
        tg = int(telegram_id)
    except (TypeError, ValueError):
        return {"tier": "free", "pro_expires_at": None}
    with get_conn() as conn:
        _ensure_user_tiers_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT tier, pro_expires_at FROM user_tiers WHERE telegram_id = %s", (tg,)
            )
            row = cur.fetchone()
            if not row:
                return {"tier": "free", "pro_expires_at": None}
            if row["tier"] == "pro" and row["pro_expires_at"] and row["pro_expires_at"] < datetime.now(timezone.utc):
                cur.execute("UPDATE user_tiers SET tier = 'free' WHERE telegram_id = %s", (tg,))
                return {"tier": "free", "pro_expires_at": row["pro_expires_at"]}
            return {"tier": row["tier"], "pro_expires_at": row["pro_expires_at"]}


def set_tier(telegram_id, tier: str, pro_expires_at=None, actor_id=None, note: str = None) -> dict:
    """Upsert tier — gọi sau khi thanh toán thành công (Stars/MoMo/VNPay/Stripe).
    actor_id=None → hệ thống tự động (vd webhook thanh toán) ghi vào audit_log."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_user_tiers_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT tier, pro_expires_at FROM user_tiers WHERE telegram_id = %s", (tg,))
            before_row = cur.fetchone()
            cur.execute("""
                INSERT INTO user_tiers (telegram_id, tier, pro_expires_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    tier = EXCLUDED.tier, pro_expires_at = EXCLUDED.pro_expires_at
                RETURNING telegram_id, tier, pro_expires_at
            """, (tg, tier, pro_expires_at))
            result = dict(cur.fetchone())
    log_audit(actor_id, "tier.set", "user_tiers", tg,
              before=dict(before_row) if before_row else None, after=result, note=note)
    return result


def extend_pro(telegram_id, days: int, actor_id=None, note: str = None) -> dict:
    """Cộng thêm `days` ngày Pro — nếu đang Pro và chưa hết hạn thì cộng dồn từ
    pro_expires_at hiện tại (không reset), nếu free/đã hết hạn thì tính từ hôm nay.
    Dùng cho thanh toán, mã giảm giá, và thưởng giới thiệu (referral).
    actor_id=None → hệ thống tự động (thanh toán/redeem) ghi vào audit_log."""
    tg = int(telegram_id)
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        _ensure_user_tiers_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT tier, pro_expires_at FROM user_tiers WHERE telegram_id = %s", (tg,))
            row = cur.fetchone()
            base = now
            if row and row["tier"] == "pro" and row["pro_expires_at"] and row["pro_expires_at"] > now:
                base = row["pro_expires_at"]
            new_expiry = base + timedelta(days=days)
            cur.execute("""
                INSERT INTO user_tiers (telegram_id, tier, pro_expires_at)
                VALUES (%s, 'pro', %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    tier = 'pro', pro_expires_at = EXCLUDED.pro_expires_at
                RETURNING telegram_id, tier, pro_expires_at
            """, (tg, new_expiry))
            result = dict(cur.fetchone())
    log_audit(actor_id, "tier.extend", "user_tiers", tg,
              before=dict(row) if row else None, after=result,
              note=note or f"+{days} ngày")
    return result


# ─── PROMO / REFERRAL CODES ──────────────────────────────────────────────────
# 2 loại code dùng chung 1 cơ chế redeem:
#   kind='admin'    — admin tự tạo (trial cho bạn bè...), giới hạn max_uses tuỳ ý.
#   kind='referral' — mỗi user có 1 code cá nhân cố định (không giới hạn lượt dùng
#                     tổng), ai nhập vào sẽ được +days và NGƯỜI TẠO code (referrer)
#                     cũng được +days — khuyến khích giới thiệu bạn bè thật.
# promo_redemptions.UNIQUE(code, telegram_id) đảm bảo mỗi code chỉ dùng được
# 1 lần/tài khoản, chặn share tràn lan cùng 1 người dùng nhiều lần.

def _ensure_promo_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                code            TEXT PRIMARY KEY,
                kind            TEXT NOT NULL DEFAULT 'admin',
                days            INT  NOT NULL,
                max_uses        INT,
                uses_count      INT  NOT NULL DEFAULT 0,
                created_by      BIGINT,
                active          BOOLEAN NOT NULL DEFAULT true,
                note            TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id              SERIAL PRIMARY KEY,
                code            TEXT NOT NULL REFERENCES promo_codes(code),
                telegram_id     BIGINT NOT NULL,
                redeemed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (code, telegram_id)
            )
        """)


def _gen_promo_code(prefix: str = "") -> str:
    import random, string
    body = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}{body}" if prefix else body


def create_promo_code(days: int, max_uses: "int | None", created_by, note: str = "",
                       code: str = None) -> dict:
    """T2-ADMIN: admin tạo mã trial/giảm giá. code=None → tự sinh mã 8 ký tự ngẫu nhiên."""
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            final_code = (code or _gen_promo_code()).strip().upper()
            cur.execute("""
                INSERT INTO promo_codes (code, kind, days, max_uses, created_by, note)
                VALUES (%s, 'admin', %s, %s, %s, %s)
                RETURNING *
            """, (final_code, days, max_uses, int(created_by) if created_by else None, note))
            result = dict(cur.fetchone())
    log_audit(created_by, "promo.create", "promo_codes", final_code, after=result)
    return result


def list_promo_codes() -> "list[dict]":
    """Tất cả mã admin đã tạo (không gồm code referral cá nhân), mới nhất trước."""
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM promo_codes WHERE kind = 'admin' ORDER BY created_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]


def deactivate_promo_code(code: str, actor_id=None) -> bool:
    code = code.strip().upper()
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE promo_codes SET active = false WHERE code = %s", (code,))
            ok = cur.rowcount > 0
    if ok:
        log_audit(actor_id, "promo.deactivate", "promo_codes", code)
    return ok


def activate_promo_code(code: str, actor_id=None) -> bool:
    code = code.strip().upper()
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE promo_codes SET active = true WHERE code = %s", (code,))
            ok = cur.rowcount > 0
    if ok:
        log_audit(actor_id, "promo.activate", "promo_codes", code)
    return ok


def update_promo_code(code: str, days: int, max_uses: "int | None", note: str, actor_id=None) -> "dict | None":
    """Sửa số ngày/số lượt/ghi chú của 1 mã admin đã tạo (không đổi code, kind, uses_count)."""
    code = code.strip().upper()
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM promo_codes WHERE code = %s", (code,))
            before_row = cur.fetchone()
            cur.execute("""
                UPDATE promo_codes SET days = %s, max_uses = %s, note = %s
                WHERE code = %s
                RETURNING *
            """, (days, max_uses, note, code))
            row = cur.fetchone()
    if row:
        log_audit(actor_id, "promo.edit", "promo_codes", code,
                  before=dict(before_row) if before_row else None, after=dict(row))
    return dict(row) if row else None


def code_exists(code: str) -> bool:
    """Kiểm tra mã đã tồn tại chưa (không phân biệt hoa/thường) — dùng để validate
    real-time trước khi admin tạo mã mới, tránh trùng mã đã dùng/đã tạo trước đó."""
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM promo_codes WHERE code = %s", (code.strip().upper(),))
            return cur.fetchone() is not None


def get_or_create_referral_code(telegram_id) -> str:
    """Mỗi user có đúng 1 mã giới thiệu cá nhân, không hết hạn, không giới hạn
    tổng lượt dùng (mỗi người khác chỉ dùng được 1 lần nhờ UNIQUE(code, telegram_id))."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT code FROM promo_codes WHERE kind = 'referral' AND created_by = %s", (tg,))
            row = cur.fetchone()
            if row:
                return row["code"]
            code = _gen_promo_code(prefix="REF-")
            cur.execute("""
                INSERT INTO promo_codes (code, kind, days, max_uses, created_by, note)
                VALUES (%s, 'referral', 30, NULL, %s, 'auto-generated referral code')
                RETURNING code
            """, (code, tg))
            return cur.fetchone()["code"]


def get_referral_stats(telegram_id) -> dict:
    """Số người đã dùng mã giới thiệu của user này."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT code FROM promo_codes WHERE kind = 'referral' AND created_by = %s", (tg,))
            row = cur.fetchone()
            if not row:
                return {"code": None, "uses_count": 0}
            cur.execute("SELECT COUNT(*) AS n FROM promo_redemptions WHERE code = %s", (row["code"],))
            n = cur.fetchone()["n"]
            return {"code": row["code"], "uses_count": n}


def redeem_promo_code(code: str, telegram_id) -> dict:
    """Áp dụng mã giảm giá/giới thiệu cho telegram_id. Trả {ok, error, days, referrer_bonus_days}."""
    tg = int(telegram_id)
    code = (code or "").strip().upper()
    if not code:
        return {"ok": False, "error": "Vui lòng nhập mã"}
    with get_conn() as conn:
        _ensure_promo_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM promo_codes WHERE code = %s", (code,))
            promo = cur.fetchone()
            if not promo:
                return {"ok": False, "error": "Mã không tồn tại"}
            if not promo["active"]:
                return {"ok": False, "error": "Mã đã bị vô hiệu hoá"}
            if promo["kind"] == "referral" and promo["created_by"] == tg:
                return {"ok": False, "error": "Không thể dùng mã giới thiệu của chính mình"}
            if promo["max_uses"] is not None and promo["uses_count"] >= promo["max_uses"]:
                return {"ok": False, "error": "Mã đã hết lượt sử dụng"}
            cur.execute("SELECT 1 FROM promo_redemptions WHERE code = %s AND telegram_id = %s", (code, tg))
            if cur.fetchone():
                return {"ok": False, "error": "Bạn đã sử dụng mã này rồi"}
            cur.execute(
                "INSERT INTO promo_redemptions (code, telegram_id) VALUES (%s, %s)", (code, tg)
            )
            cur.execute(
                "UPDATE promo_codes SET uses_count = uses_count + 1 WHERE code = %s", (code,)
            )
    # Ngoài transaction ở trên (extend_pro tự mở connection riêng)
    extend_pro(tg, promo["days"], actor_id=tg, note=f"redeem mã {code}")
    referrer_bonus = 0
    if promo["kind"] == "referral" and promo["created_by"]:
        extend_pro(promo["created_by"], promo["days"], actor_id=tg, note=f"referral bonus từ mã {code}")
        referrer_bonus = promo["days"]
    log_audit(tg, "promo.redeem", "promo_codes", code,
              after={"days": promo["days"], "referrer_bonus_days": referrer_bonus, "kind": promo["kind"]})
    return {"ok": True, "days": promo["days"], "referrer_bonus_days": referrer_bonus}


# ─── ALERTS (PRO-004) ────────────────────────────────────────────────────────
# Pro-only: user đặt ngưỡng theo dõi cho 1 quỹ, bot.job_check_alerts() (18:33,
# sau daily harvest) so khớp và gửi Telegram khi điều kiện đạt. Debounce theo
# ngày qua last_triggered — không gửi lặp lại trong cùng 1 ngày.

ALERT_CONDITIONS = ("nav_up", "nav_down", "signal_buy", "signal_sell")


def _ensure_alerts_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id              SERIAL PRIMARY KEY,
                telegram_id     BIGINT NOT NULL,
                fund_code       TEXT NOT NULL,
                condition       TEXT NOT NULL,
                threshold       NUMERIC,
                last_triggered  TIMESTAMPTZ,
                active          BOOLEAN NOT NULL DEFAULT TRUE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(telegram_id) WHERE active")


def create_alert(telegram_id, fund_code: str, condition: str, threshold=None) -> dict:
    if condition not in ALERT_CONDITIONS:
        raise ValueError(f"condition không hợp lệ: {condition}")
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_alerts_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO alerts (telegram_id, fund_code, condition, threshold)
                VALUES (%s, %s, %s, %s)
                RETURNING id, telegram_id, fund_code, condition, threshold, last_triggered, created_at
            """, (tg, fund_code.upper(), condition, threshold))
            return dict(cur.fetchone())


def list_alerts(telegram_id) -> "list[dict]":
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_alerts_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, fund_code, condition, threshold, last_triggered, created_at
                FROM alerts WHERE telegram_id = %s AND active = true
                ORDER BY created_at DESC
            """, (tg,))
            return [dict(r) for r in cur.fetchall()]


def delete_alert(alert_id, telegram_id) -> bool:
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_alerts_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alerts SET active = false WHERE id = %s AND telegram_id = %s",
                (int(alert_id), tg),
            )
            return cur.rowcount > 0


def get_active_alerts() -> "list[dict]":
    """Tất cả alert đang active của mọi user — dùng cho job_check_alerts."""
    with get_conn() as conn:
        _ensure_alerts_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, telegram_id, fund_code, condition, threshold, last_triggered
                FROM alerts WHERE active = true
            """)
            return [dict(r) for r in cur.fetchall()]


def mark_alert_triggered(alert_id) -> None:
    with get_conn() as conn:
        _ensure_alerts_table(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE alerts SET last_triggered = NOW() WHERE id = %s", (int(alert_id),))


# ─── NAV DRAFTS (Pro user local NAV) ─────────────────────────────────────────

def _ensure_nav_drafts_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nav_drafts (
                id              SERIAL PRIMARY KEY,
                telegram_id     BIGINT NOT NULL,
                fund_code       TEXT   NOT NULL,
                nav_date        DATE   NOT NULL,
                nav             FLOAT  NOT NULL,
                status          TEXT   NOT NULL DEFAULT 'pending',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(telegram_id, fund_code, nav_date)
            )
        """)


def save_nav_draft(telegram_id, fund_code: str, nav_date: date, nav: float) -> None:
    """Lưu NAV draft của Pro user — upsert nếu đã có pending draft cùng ngày."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_nav_drafts_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO nav_drafts (telegram_id, fund_code, nav_date, nav, status)
                VALUES (%s, %s, %s, %s, 'pending')
                ON CONFLICT (telegram_id, fund_code, nav_date) DO UPDATE
                    SET nav = EXCLUDED.nav, created_at = NOW()
                    WHERE nav_drafts.status = 'pending'
            """, (tg, fund_code.upper(), nav_date, nav))


def get_nav_drafts(telegram_id, fund_codes: list = None) -> list:
    """Trả danh sách pending drafts của user, filter theo fund_codes nếu có."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_nav_drafts_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if fund_codes:
                ph = ",".join(["%s"] * len(fund_codes))
                cur.execute(
                    f"SELECT fund_code, nav_date::text, nav, status FROM nav_drafts "
                    f"WHERE telegram_id=%s AND fund_code IN ({ph}) AND status='pending' "
                    f"ORDER BY fund_code, nav_date",
                    [tg] + [c.upper() for c in fund_codes]
                )
            else:
                cur.execute(
                    "SELECT fund_code, nav_date::text, nav, status FROM nav_drafts "
                    "WHERE telegram_id=%s AND status='pending' ORDER BY fund_code, nav_date",
                    (tg,)
                )
            return [dict(r) for r in cur.fetchall()]


def unify_nav_drafts(fund_code: str, nav_date: date, api_nav: float,
                     tolerance_pct: float = 0.5) -> int:
    """Sau khi API harvest xác nhận NAV, promote các pending drafts khớp về 'confirmed'.
    Trả số lượng drafts được confirm.
    Tolerance: nếu |draft - api| / api * 100 <= tolerance_pct → khớp.
    """
    confirmed = 0
    with get_conn() as conn:
        _ensure_nav_drafts_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, telegram_id, nav FROM nav_drafts "
                "WHERE fund_code=%s AND nav_date=%s AND status='pending'",
                (fund_code.upper(), nav_date)
            )
            rows = cur.fetchall()
        for row in rows:
            diff_pct = abs(row["nav"] - api_nav) / api_nav * 100 if api_nav else 100
            new_status = "confirmed" if diff_pct <= tolerance_pct else "rejected"
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE nav_drafts SET status=%s WHERE id=%s",
                    (new_status, row["id"])
                )
            if new_status == "confirmed":
                confirmed += 1
                logger.info("nav_draft confirmed: tg=%s %s %s nav=%.4f (api=%.4f)",
                            row["telegram_id"], fund_code, nav_date, row["nav"], api_nav)
            else:
                logger.warning("nav_draft rejected: tg=%s %s %s draft=%.4f api=%.4f diff=%.2f%%",
                               row["telegram_id"], fund_code, nav_date,
                               row["nav"], api_nav, diff_pct)
    return confirmed


# ─── T+2 FORECAST ENGINE — T2-001 ────────────────────────────────────────────

def _ensure_prediction_tables(conn) -> None:
    """T2-001: Tạo nav_predictions + prediction_actuals + model_metrics nếu chưa có."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nav_predictions (
                id               SERIAL PRIMARY KEY,
                fund_code        TEXT        NOT NULL,
                predicted_for_date DATE      NOT NULL,
                predicted_nav    FLOAT       NOT NULL,
                model_version    TEXT        NOT NULL DEFAULT 'arima-v1',
                ci_low           FLOAT,
                ci_high          FLOAT,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (fund_code, predicted_for_date, model_version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prediction_actuals (
                id              SERIAL PRIMARY KEY,
                prediction_id   INT         NOT NULL REFERENCES nav_predictions(id) ON DELETE CASCADE,
                actual_nav      FLOAT       NOT NULL,
                error_pct       FLOAT       NOT NULL,
                logged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS model_metrics (
                id             SERIAL PRIMARY KEY,
                model_version  TEXT        NOT NULL,
                fund_code      TEXT,
                window_days    INT         NOT NULL DEFAULT 30,
                mape           FLOAT       NOT NULL,
                sample_size    INT         NOT NULL,
                evaluated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_navpred_code_date ON nav_predictions (fund_code, predicted_for_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_predact_pred ON prediction_actuals (prediction_id)")


def save_prediction(fund_code: str, predicted_for_date: date, predicted_nav: float,
                    model_version: str = "arima-v1",
                    ci_low: float = None, ci_high: float = None) -> int:
    """Upsert một dự báo NAV. Trả prediction_id."""
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO nav_predictions (fund_code, predicted_for_date, predicted_nav, model_version, ci_low, ci_high)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (fund_code, predicted_for_date, model_version) DO UPDATE SET
                    predicted_nav = EXCLUDED.predicted_nav,
                    ci_low        = EXCLUDED.ci_low,
                    ci_high       = EXCLUDED.ci_high,
                    created_at    = NOW()
                RETURNING id
            """, (fund_code.upper(), predicted_for_date, predicted_nav, model_version, ci_low, ci_high))
            return cur.fetchone()[0]


def score_predictions(target_date: date) -> list:
    """T2-006: Với mỗi prediction có predicted_for_date=target_date, tính error_pct từ NAV thực tế.
    Trả list dict {fund_code, predicted_nav, actual_nav, error_pct, prediction_id}."""
    results = []
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Join với nav_history để lấy NAV thực tế
            cur.execute("""
                SELECT np.id, np.fund_code, np.predicted_nav, np.model_version,
                       nh.nav AS actual_nav
                FROM nav_predictions np
                JOIN nav_history nh ON nh.fund_code = np.fund_code AND nh.nav_date = np.predicted_for_date
                WHERE np.predicted_for_date = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM prediction_actuals pa WHERE pa.prediction_id = np.id
                  )
            """, (target_date,))
            rows = cur.fetchall()
        for row in rows:
            if not row["actual_nav"]:
                continue
            err_pct = (row["actual_nav"] - row["predicted_nav"]) / row["actual_nav"] * 100
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO prediction_actuals (prediction_id, actual_nav, error_pct) VALUES (%s, %s, %s)",
                    (row["id"], row["actual_nav"], err_pct)
                )
            results.append({
                "fund_code": row["fund_code"],
                "model_version": row["model_version"],
                "predicted_nav": row["predicted_nav"],
                "actual_nav": row["actual_nav"],
                "error_pct": err_pct,
                "prediction_id": row["id"],
            })
    return results


def get_predictions(fund_codes: list, target_date: date = None) -> dict:
    """Lấy dự báo mới nhất cho danh sách quỹ. Trả {fund_code: {predicted_nav, ci_low, ci_high, model_version}}."""
    if not fund_codes:
        return {}
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            placeholders = ",".join(["%s"] * len(fund_codes))
            if target_date:
                cur.execute(f"""
                    SELECT DISTINCT ON (fund_code) fund_code, predicted_nav, ci_low, ci_high,
                           model_version, predicted_for_date
                    FROM nav_predictions
                    WHERE fund_code IN ({placeholders}) AND predicted_for_date = %s
                    ORDER BY fund_code, created_at DESC
                """, [c.upper() for c in fund_codes] + [target_date])
            else:
                cur.execute(f"""
                    SELECT DISTINCT ON (fund_code) fund_code, predicted_nav, ci_low, ci_high,
                           model_version, predicted_for_date
                    FROM nav_predictions
                    WHERE fund_code IN ({placeholders})
                    ORDER BY fund_code, predicted_for_date DESC, created_at DESC
                """, [c.upper() for c in fund_codes])
            return {r["fund_code"]: dict(r) for r in cur.fetchall()}


def get_model_mape(model_version: str = None, fund_code: str = None, window_days: int = 30) -> list:
    """Lấy MAPE lịch sử theo model/quỹ/window. Dùng cho T2-010 accuracy dashboard."""
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filters = []
            params = []
            if model_version:
                filters.append("model_version = %s"); params.append(model_version)
            if fund_code:
                filters.append("fund_code = %s"); params.append(fund_code.upper())
            filters.append("window_days = %s"); params.append(window_days)
            where = "WHERE " + " AND ".join(filters) if filters else ""
            cur.execute(f"SELECT * FROM model_metrics {where} ORDER BY evaluated_at DESC LIMIT 100", params)
            return [dict(r) for r in cur.fetchall()]


def get_rolling_error_std(model_version: str, fund_code: str = None,
                           window_days: int = 30, min_samples: int = 5) -> "float | None":
    """T2-005: stdev(error_pct) trong window_days gần nhất cho model_version.
    Ưu tiên per-fund nếu đủ ≥min_samples mẫu, fallback sang toàn bộ quỹ (fund_code=None)
    nếu không đủ. Trả None nếu vẫn không đủ dữ liệu (caller tự áp CI mặc định)."""
    with get_conn() as conn:
        _ensure_prediction_tables(conn)

        def _query(with_fund: bool):
            with conn.cursor() as cur:
                if with_fund:
                    cur.execute("""
                        SELECT STDDEV_SAMP(pa.error_pct), COUNT(*)
                        FROM prediction_actuals pa
                        JOIN nav_predictions np ON np.id = pa.prediction_id
                        WHERE np.model_version = %s AND np.fund_code = %s
                          AND pa.logged_at >= NOW() - (%s || ' days')::interval
                    """, (model_version, fund_code.upper(), window_days))
                else:
                    cur.execute("""
                        SELECT STDDEV_SAMP(pa.error_pct), COUNT(*)
                        FROM prediction_actuals pa
                        JOIN nav_predictions np ON np.id = pa.prediction_id
                        WHERE np.model_version = %s
                          AND pa.logged_at >= NOW() - (%s || ' days')::interval
                    """, (model_version, window_days))
                return cur.fetchone()

        if fund_code:
            std, n = _query(True)
            if n and n >= min_samples and std is not None:
                return float(std)
        std, n = _query(False)
        if n and n >= min_samples and std is not None:
            return float(std)
        return None


def get_daily_mape(model_version: str, days: int = 30) -> "list[dict]":
    """GOV-003: MAPE trung bình theo từng NGÀY (theo prediction_actuals.logged_at::date,
    không phải model_metrics — bảng đó chỉ ghi lúc train XGBoost, không cập nhật hàng ngày)
    cho 1 model, N ngày gần nhất có dữ liệu chấm điểm. Dùng để phát hiện chuỗi ngày MAPE
    vượt ngưỡng liên tiếp."""
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT pa.logged_at::date AS day,
                       AVG(ABS(pa.error_pct)) AS mape,
                       COUNT(*) AS n
                FROM prediction_actuals pa
                JOIN nav_predictions np ON np.id = pa.prediction_id
                WHERE np.model_version = %s
                GROUP BY pa.logged_at::date
                ORDER BY day DESC
                LIMIT %s
            """, (model_version, days))
            return [dict(r) for r in cur.fetchall()]


def get_mape_breach_streak(model_version: str, threshold_pct: float, max_days: int = 30) -> int:
    """GOV-003: đếm số ngày liên tiếp gần nhất (lùi từ hôm nay) có MAPE trung bình ngày
    > threshold_pct — dừng đếm ngay khi gặp 1 ngày MAPE ≤ ngưỡng hoặc hết dữ liệu. Caller
    nên chỉ cảnh báo khi streak == ngưỡng số-ngày mong muốn (không phải mọi lần streak > 0)
    để tránh spam alert lặp lại mỗi ngày sau khi đã báo lần đầu."""
    rows = get_daily_mape(model_version, days=max_days)
    streak = 0
    for r in rows:
        if r["mape"] is not None and float(r["mape"]) > threshold_pct:
            streak += 1
        else:
            break
    return streak


def get_accuracy_summary(fund_code: str) -> "list[dict]":
    """T2-010: MAPE 7d/30d/all-time cho mỗi model_version đã dự báo quỹ này.
    Trả list dict {model_version, mape_7d, n_7d, mape_30d, n_30d, mape_all, n_all}."""
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT np.model_version,
                       ROUND(AVG(ABS(pa.error_pct)) FILTER (
                           WHERE pa.logged_at >= NOW() - INTERVAL '7 days')::numeric, 2)  AS mape_7d,
                       COUNT(*) FILTER (
                           WHERE pa.logged_at >= NOW() - INTERVAL '7 days')               AS n_7d,
                       ROUND(AVG(ABS(pa.error_pct)) FILTER (
                           WHERE pa.logged_at >= NOW() - INTERVAL '30 days')::numeric, 2) AS mape_30d,
                       COUNT(*) FILTER (
                           WHERE pa.logged_at >= NOW() - INTERVAL '30 days')              AS n_30d,
                       ROUND(AVG(ABS(pa.error_pct))::numeric, 2)                          AS mape_all,
                       COUNT(*)                                                           AS n_all
                FROM prediction_actuals pa
                JOIN nav_predictions np ON np.id = pa.prediction_id
                WHERE np.fund_code = %s
                GROUP BY np.model_version
                ORDER BY mape_all
            """, (fund_code.upper(),))
            rows = [dict(r) for r in cur.fetchall()]
            # ROUND(...)::numeric → Decimal (không JSON-serializable) — ép về float
            for r in rows:
                for k in ("mape_7d", "mape_30d", "mape_all"):
                    if r.get(k) is not None:
                        r[k] = float(r[k])
            return rows


def get_accuracy_history(fund_code: str, model_version: str = None, limit: int = 60) -> "list[dict]":
    """T2-010: Lịch sử dự báo vs thực tế cho biểu đồ (predicted_for_date, predicted_nav,
    actual_nav, error_pct, model_version), mới nhất trước. Nếu model_version=None,
    trả model đã dự báo gần nhất mỗi ngày (ưu tiên ensemble > xgb > arima nếu trùng ngày)."""
    with get_conn() as conn:
        _ensure_prediction_tables(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if model_version:
                cur.execute("""
                    SELECT np.predicted_for_date::text AS predicted_for_date,
                           np.predicted_nav, np.model_version,
                           pa.actual_nav, pa.error_pct
                    FROM prediction_actuals pa
                    JOIN nav_predictions np ON np.id = pa.prediction_id
                    WHERE np.fund_code = %s AND np.model_version = %s
                    ORDER BY np.predicted_for_date DESC
                    LIMIT %s
                """, (fund_code.upper(), model_version, limit))
            else:
                cur.execute("""
                    SELECT DISTINCT ON (np.predicted_for_date)
                           np.predicted_for_date::text AS predicted_for_date,
                           np.predicted_nav, np.model_version,
                           pa.actual_nav, pa.error_pct
                    FROM prediction_actuals pa
                    JOIN nav_predictions np ON np.id = pa.prediction_id
                    WHERE np.fund_code = %s
                    ORDER BY np.predicted_for_date DESC,
                             CASE np.model_version
                                 WHEN 'ensemble-v1' THEN 0
                                 WHEN 'xgb-v1'      THEN 1
                                 WHEN 'arima-v1'    THEN 2
                                 ELSE 3
                             END
                    LIMIT %s
                """, (fund_code.upper(), limit))
            return [dict(r) for r in cur.fetchall()]


# ─── ADMIN SUMMARY DASHBOARD (GOV-004) ───────────────────────────────────────

def get_admin_summary() -> dict:
    """GOV-004: tổng hợp 1 lần cho admin dashboard — user theo tier, MAPE model gần nhất,
    quỹ thiếu/lỗi NAV hôm nay, giao dịch thanh toán gần đây. Read-only, mỗi phần độc lập
    (lỗi 1 phần không chặn phần khác — dùng try/except riêng vì đây là dashboard tổng hợp,
    thà thiếu 1 mục còn hơn lỗi cả trang)."""
    if not is_available():
        return {"users": {}, "model_mape": [], "funds_missing_today": [], "recent_payments": []}

    summary: dict = {}

    # ── Users theo tier ──────────────────────────────────────────────────────
    try:
        with get_conn() as conn:
            _ensure_bot_profiles_table(conn)
            _ensure_user_tiers_table(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM bot_profiles WHERE is_active = true")
                total = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(*) FROM user_tiers
                    WHERE tier = 'pro' AND (pro_expires_at IS NULL OR pro_expires_at > NOW())
                """)
                pro = cur.fetchone()[0]
        summary["users"] = {"total": total, "pro": pro, "free": max(total - pro, 0)}
    except Exception as e:
        logger.warning(f"[admin_summary] users: {e}")
        summary["users"] = {}

    # ── MAPE model gần nhất (7 ngày) mỗi model_version đã dự báo ─────────────
    try:
        mape_rows = []
        for mv in ("arima-v1", "xgb-v1", "ensemble-v1"):
            daily = get_daily_mape(mv, days=7)
            if daily:
                vals = [float(r["mape"]) for r in daily if r["mape"] is not None]
                mape_rows.append({
                    "model_version": mv,
                    "mape_7d": round(sum(vals) / len(vals), 2) if vals else None,
                    "last_day": str(daily[0]["day"]),
                    "last_day_mape": round(float(daily[0]["mape"]), 2) if daily[0]["mape"] is not None else None,
                })
        summary["model_mape"] = mape_rows
    except Exception as e:
        logger.warning(f"[admin_summary] model_mape: {e}")
        summary["model_mape"] = []

    # ── Quỹ chưa có NAV hôm nay (active trong funds_master, không có row nav_history hôm nay) ──
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT m.code, m.name,
                           (SELECT MAX(nav_date) FROM nav_history WHERE fund_code = m.code)::text AS last_nav_date
                    FROM funds_master m
                    WHERE m.active = true
                      AND NOT EXISTS (
                          SELECT 1 FROM nav_history h
                          WHERE h.fund_code = m.code AND h.nav_date = CURRENT_DATE
                      )
                    ORDER BY m.code
                """)
                summary["funds_missing_today"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"[admin_summary] funds_missing_today: {e}")
        summary["funds_missing_today"] = []

    # ── Giao dịch thanh toán gần đây ──────────────────────────────────────────
    try:
        with get_conn() as conn:
            _ensure_payment_dedup_table(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT provider, charge_id, telegram_id, created_at::text
                    FROM processed_payments
                    ORDER BY created_at DESC LIMIT 20
                """)
                summary["recent_payments"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"[admin_summary] recent_payments: {e}")
        summary["recent_payments"] = []

    return summary


# ─── POOL ────────────────────────────────────────────────────────────────────

def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL pool closed")
