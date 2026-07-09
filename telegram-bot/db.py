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
    """Thêm 'manual' và 'fixed' vào enum data_src nếu chưa có.
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
            for val in ('manual', 'fixed'):
                try:
                    cur.execute(f"ALTER TYPE data_src ADD VALUE IF NOT EXISTS '{val}'")
                    logger.info("Migrated data_src enum: added '%s'", val)
                except Exception as e:
                    logger.debug("data_src enum '%s' skip: %s", val, e)
        conn.close()
    except Exception as e:
        logger.warning("_migrate_data_src_enum failed (non-fatal): %s", e)


def init_pool(min_conn: int = 1, max_conn: int = 5) -> None:
    global _pool
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set — PostgreSQL disabled")
        return
    _migrate_data_src_enum()  # Chạy trước khi mở pool
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
                    SET nav        = EXCLUDED.nav,
                        source     = CASE
                            WHEN nav_history.source = 'fixed'  THEN 'fixed'
                            WHEN nav_history.source = 'manual' THEN 'fixed'
                            ELSE EXCLUDED.source
                        END,
                        fetched_at = NOW()
                WHERE nav_history.source != 'fixed'
            """, (fund_code, nav_date, nav, source))
    logger.debug("upsert_nav %s %s %.4f src=%s", fund_code, nav_date, nav, source)
    # Sau khi API data confirmed → unify pending Pro drafts nếu khớp
    try:
        unify_nav_drafts(fund_code, nav_date, nav)
    except Exception as e:
        logger.debug("unify_nav_drafts skip: %s", e)


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
    indicators dict keys: rsi, bb_pct, macd_hist, ma20_vs_ma50, momentum_30d,
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
                    chg_pct, chg7d, chg30d, details, nav_date
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s
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
                    nav_date      = EXCLUDED.nav_date
                RETURNING id
            """, (
                fund_code, signal_date, strength, score,
                ind.get("rsi"), ind.get("bb_pct"), ind.get("macd_hist"),
                int(bool(ind.get("ma20_vs_ma50"))), ind.get("momentum_30d"),
                nav_at_signal, settlement_rule, exec_date,
                ind.get("chg_pct"), ind.get("chg7d"), ind.get("chg30d"),
                _json.dumps(ind.get("details") or []), nav_date_val,
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


def set_tier(telegram_id, tier: str, pro_expires_at=None) -> dict:
    """Upsert tier — gọi sau khi thanh toán thành công (Stars/MoMo/VNPay/Stripe)."""
    tg = int(telegram_id)
    with get_conn() as conn:
        _ensure_user_tiers_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO user_tiers (telegram_id, tier, pro_expires_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    tier = EXCLUDED.tier, pro_expires_at = EXCLUDED.pro_expires_at
                RETURNING telegram_id, tier, pro_expires_at
            """, (tg, tier, pro_expires_at))
            return dict(cur.fetchone())


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


# ─── POOL ────────────────────────────────────────────────────────────────────

def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL pool closed")
