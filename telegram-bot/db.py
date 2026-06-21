"""
PostgreSQL connection layer — Fund Tracker Pro
ThreadedConnectionPool: safe cho bot.py multi-thread (scheduler + long-polling).
Usage:
    from db import db_conn, set_app_uid, upsert_nav, save_signal
"""
import os
import logging
from contextlib import contextmanager
from datetime import date, timedelta

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None

SETTLEMENT_DAYS = {"T1": 1, "T2": 2, "T3": 3}


def init_pool(min_conn: int = 1, max_conn: int = 5) -> None:
    global _pool
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set — PostgreSQL disabled")
        return
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
                    SET nav = EXCLUDED.nav,
                        source = EXCLUDED.source,
                        fetched_at = NOW()
            """, (fund_code, nav_date, nav, source))
    logger.debug("upsert_nav %s %s %.4f", fund_code, nav_date, nav)


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
    Persist a buy signal. Returns signal UUID or None if DB unavailable.
    indicators dict keys: rsi, bb_pct, macd_hist, ma20_vs_ma50, momentum_30d
    """
    if not is_available():
        return None
    ind = indicators or {}
    exec_date = _calc_exec_date(signal_date, settlement_rule)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO buy_signals (
                    fund_code, signal_date, strength, score,
                    rsi, bb_pct, macd_hist, ma20_vs_ma50, momentum_30d,
                    nav_at_signal, settlement_rule, est_exec_date
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (fund_code, signal_date) DO UPDATE SET
                    strength = EXCLUDED.strength,
                    score = EXCLUDED.score,
                    rsi = EXCLUDED.rsi,
                    bb_pct = EXCLUDED.bb_pct,
                    macd_hist = EXCLUDED.macd_hist,
                    nav_at_signal = EXCLUDED.nav_at_signal,
                    est_exec_date = EXCLUDED.est_exec_date
                RETURNING id
            """, (
                fund_code, signal_date, strength, score,
                ind.get("rsi"), ind.get("bb_pct"), ind.get("macd_hist"),
                ind.get("ma20_vs_ma50"), ind.get("momentum_30d"),
                nav_at_signal, settlement_rule, exec_date,
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


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL pool closed")
