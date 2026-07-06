-- ============================================================
-- Fund Tracker Pro — PostgreSQL Schema
-- Target: Railway PostgreSQL / Supabase / Neon
-- Run: psql $DATABASE_URL -f schema.sql
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid(), pgp_sym_encrypt
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- fuzzy search on fund names

-- ============================================================
-- ENUMS
-- ============================================================
DO $$ BEGIN
    CREATE TYPE fund_type       AS ENUM ('bond','equity','balanced','money_market','etf');
    CREATE TYPE data_src        AS ENUM ('fmarket','tcbs','vfm','dcvfm','ssiam','manual');
    CREATE TYPE settlement_t    AS ENUM ('T1','T2','T3');
    CREATE TYPE signal_strength AS ENUM ('strong_buy','buy','hold','reduce','strong_reduce');
    CREATE TYPE tx_type         AS ENUM ('buy','sell','dividend_reinvest','fee','adjustment');
    CREATE TYPE capital_evt     AS ENUM ('injection','reduction','dividend','fee_charge');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================================================
-- DOMAIN 1: FUND UNIVERSE
-- ============================================================
CREATE TABLE IF NOT EXISTS funds (
    code              VARCHAR(20)   PRIMARY KEY,
    name              VARCHAR(200)  NOT NULL,
    fund_type         fund_type     NOT NULL DEFAULT 'bond',
    fund_company      VARCHAR(100),
    inception_date    DATE,
    fmarket_id        INTEGER       UNIQUE,
    tcbs_tradeable    BOOLEAN       DEFAULT FALSE,
    settlement_rule   settlement_t  DEFAULT 'T2',
    expense_ratio     DECIMAL(5,4),
    min_investment    BIGINT,
    active            BOOLEAN       DEFAULT TRUE,
    created_at        TIMESTAMPTZ   DEFAULT NOW()
);

-- ============================================================
-- DOMAIN 2: NAV HISTORY (partitioned by year)
-- ============================================================
CREATE TABLE IF NOT EXISTS nav_history (
    fund_code   VARCHAR(20)   NOT NULL,
    nav_date    DATE          NOT NULL,
    nav         DECIMAL(14,4) NOT NULL CHECK (nav > 0),
    source      data_src      NOT NULL DEFAULT 'fmarket',
    verified    BOOLEAN       DEFAULT FALSE,
    fetched_at  TIMESTAMPTZ   DEFAULT NOW(),
    PRIMARY KEY (fund_code, nav_date),
    FOREIGN KEY (fund_code) REFERENCES funds(code)
) PARTITION BY RANGE (nav_date);

-- Partitions: 2013 → 2027
CREATE TABLE IF NOT EXISTS nav_2013 PARTITION OF nav_history FOR VALUES FROM ('2013-01-01') TO ('2014-01-01');
CREATE TABLE IF NOT EXISTS nav_2014 PARTITION OF nav_history FOR VALUES FROM ('2014-01-01') TO ('2015-01-01');
CREATE TABLE IF NOT EXISTS nav_2015 PARTITION OF nav_history FOR VALUES FROM ('2015-01-01') TO ('2016-01-01');
CREATE TABLE IF NOT EXISTS nav_2016 PARTITION OF nav_history FOR VALUES FROM ('2016-01-01') TO ('2017-01-01');
CREATE TABLE IF NOT EXISTS nav_2017 PARTITION OF nav_history FOR VALUES FROM ('2017-01-01') TO ('2018-01-01');
CREATE TABLE IF NOT EXISTS nav_2018 PARTITION OF nav_history FOR VALUES FROM ('2018-01-01') TO ('2019-01-01');
CREATE TABLE IF NOT EXISTS nav_2019 PARTITION OF nav_history FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
CREATE TABLE IF NOT EXISTS nav_2020 PARTITION OF nav_history FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE IF NOT EXISTS nav_2021 PARTITION OF nav_history FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE IF NOT EXISTS nav_2022 PARTITION OF nav_history FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE IF NOT EXISTS nav_2023 PARTITION OF nav_history FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE IF NOT EXISTS nav_2024 PARTITION OF nav_history FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE IF NOT EXISTS nav_2025 PARTITION OF nav_history FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS nav_2026 PARTITION OF nav_history FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE IF NOT EXISTS nav_2027 PARTITION OF nav_history FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');

CREATE INDEX IF NOT EXISTS idx_nav_fund_date ON nav_history (fund_code, nav_date DESC);

-- ============================================================
-- DOMAIN 3: DATA SOURCE CONFIG
-- ============================================================
CREATE TABLE IF NOT EXISTS data_source_config (
    id                  SERIAL        PRIMARY KEY,
    source              data_src      NOT NULL,
    fund_code           VARCHAR(20)   REFERENCES funds(code),
    api_endpoint        TEXT,
    last_fetched_at     TIMESTAMPTZ,
    last_nav_date       DATE,
    fetch_interval_h    SMALLINT      DEFAULT 24,
    consecutive_errors  SMALLINT      DEFAULT 0,
    last_error          TEXT,
    active              BOOLEAN       DEFAULT TRUE,
    UNIQUE (source, fund_code)
);

-- ============================================================
-- DOMAIN 4: USERS
-- Sensitive fields encrypted at app layer (AES-256-GCM)
-- enc_salt: per-user, never stored with key
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id       BIGINT      UNIQUE NOT NULL,
    display_name_enc  BYTEA,
    auth_hash         BYTEA       NOT NULL,
    enc_salt          BYTEA       NOT NULL,
    is_admin          BOOLEAN     DEFAULT FALSE,
    is_active         BOOLEAN     DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    last_active_at    TIMESTAMPTZ
);

-- ============================================================
-- DOMAIN 5: PORTFOLIOS — strict sandbox
-- ============================================================
CREATE TABLE IF NOT EXISTS portfolios (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name_enc        BYTEA       NOT NULL,
    currency        CHAR(3)     DEFAULT 'VND',
    risk_profile    VARCHAR(20) DEFAULT 'moderate',
    monthly_dca_enc BYTEA,
    dca_day         SMALLINT    DEFAULT 1 CHECK (dca_day BETWEEN 1 AND 28),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS portfolio_isolation ON portfolios;
CREATE POLICY portfolio_isolation ON portfolios
    USING (user_id = NULLIF(current_setting('app.uid', TRUE), '')::UUID);

-- ============================================================
-- DOMAIN 6: HOLDINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS holdings (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id      UUID        NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    fund_code         VARCHAR(20) NOT NULL REFERENCES funds(code),
    units_enc         BYTEA       NOT NULL,
    avg_cost_enc      BYTEA       NOT NULL,
    target_alloc_pct  DECIMAL(5,2) CHECK (target_alloc_pct BETWEEN 0 AND 100),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (portfolio_id, fund_code)
);

ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS holdings_isolation ON holdings;
CREATE POLICY holdings_isolation ON holdings
    USING (portfolio_id IN (
        SELECT id FROM portfolios
        WHERE user_id = NULLIF(current_setting('app.uid', TRUE), '')::UUID
    ));

-- ============================================================
-- DOMAIN 7: TRANSACTIONS — immutable ledger
-- No UPDATE/DELETE. Corrections via 'adjustment' tx type.
-- ============================================================
CREATE TABLE IF NOT EXISTS transactions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        UUID        NOT NULL REFERENCES portfolios(id),
    fund_code           VARCHAR(20) NOT NULL REFERENCES funds(code),
    tx_type             tx_type     NOT NULL,
    order_date          DATE        NOT NULL,
    settlement_date     DATE,
    nav_at_order        DECIMAL(14,4),
    nav_at_settlement   DECIMAL(14,4),
    nav_slippage_pct    DECIMAL(6,3),
    units_enc           BYTEA       NOT NULL,
    amount_enc          BYTEA       NOT NULL,
    fee_enc             BYTEA,
    note_enc            BYTEA,
    signal_id           UUID,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tx_isolation ON transactions;
CREATE POLICY tx_isolation ON transactions
    USING (portfolio_id IN (
        SELECT id FROM portfolios
        WHERE user_id = NULLIF(current_setting('app.uid', TRUE), '')::UUID
    ));

-- Prevent UPDATE/DELETE on committed transactions
CREATE OR REPLACE RULE no_update_tx AS ON UPDATE TO transactions DO INSTEAD NOTHING;
CREATE OR REPLACE RULE no_delete_tx AS ON DELETE TO transactions DO INSTEAD NOTHING;

-- ============================================================
-- DOMAIN 8: BUY SIGNALS — T+1/T+3 aware
-- ============================================================
CREATE TABLE IF NOT EXISTS buy_signals (
    id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_code           VARCHAR(20)   NOT NULL REFERENCES funds(code),
    signal_date         DATE          NOT NULL,
    strength            signal_strength NOT NULL,
    score               SMALLINT      NOT NULL,
    rsi                 DECIMAL(6,2),
    bb_pct              DECIMAL(6,2),
    macd_hist           DECIMAL(12,6),
    ma20_vs_ma50        DECIMAL(8,6),
    momentum_30d        DECIMAL(6,3),
    nav_at_signal       DECIMAL(14,4) NOT NULL,
    settlement_rule     settlement_t  NOT NULL DEFAULT 'T2',
    est_exec_date       DATE          NOT NULL,
    nav_lower_est       DECIMAL(14,4),
    nav_upper_est       DECIMAL(14,4),
    nav_at_settlement   DECIMAL(14,4),
    signal_accuracy_pct DECIMAL(6,3),
    created_at          TIMESTAMPTZ   DEFAULT NOW(),
    UNIQUE (fund_code, signal_date)
);

CREATE INDEX IF NOT EXISTS idx_signals_date ON buy_signals (signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_strength ON buy_signals (strength, signal_date DESC);

-- ============================================================
-- DOMAIN 9: DCA SCHEDULES
-- ============================================================
CREATE TABLE IF NOT EXISTS dca_schedules (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id    UUID        NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    fund_code       VARCHAR(20) NOT NULL REFERENCES funds(code),
    monthly_amt_enc BYTEA       NOT NULL,
    alloc_pct       DECIMAL(5,2) NOT NULL CHECK (alloc_pct BETWEEN 0 AND 100),
    start_date      DATE        NOT NULL,
    end_date        DATE,
    active          BOOLEAN     DEFAULT TRUE,
    last_executed   DATE,
    next_scheduled  DATE,
    UNIQUE (portfolio_id, fund_code)
);

-- ============================================================
-- DOMAIN 10: CAPITAL EVENTS — rebalance trigger
-- ============================================================
CREATE TABLE IF NOT EXISTS capital_events (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        UUID            NOT NULL REFERENCES portfolios(id),
    event_date          DATE            NOT NULL,
    event_type          capital_evt     NOT NULL,
    amount_enc          BYTEA           NOT NULL,
    rebalance_triggered BOOLEAN         DEFAULT FALSE,
    rebalance_suggestion JSONB,
    -- {"deltas":[{"fund_code":"TCBF","delta_units":12.5,"delta_vnd":250000}],
    --  "rationale":"Inject 5M: 60% TCBF score+5, 40% SSISCA score+3"}
    note_enc            BYTEA,
    created_at          TIMESTAMPTZ     DEFAULT NOW()
);

ALTER TABLE capital_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS capital_isolation ON capital_events;
CREATE POLICY capital_isolation ON capital_events
    USING (portfolio_id IN (
        SELECT id FROM portfolios
        WHERE user_id = NULLIF(current_setting('app.uid', TRUE), '')::UUID
    ));

-- ============================================================
-- SEED: Fund universe (19 funds from config.example.json)
-- ============================================================
INSERT INTO funds (code, name, fund_type, fmarket_id, tcbs_tradeable, settlement_rule) VALUES
    ('TCBF',    'Quỹ Trái Phiếu Techcombank',           'bond',     NULL, TRUE,  'T2'),
    ('TCFF',    'Quỹ Linh Hoạt Techcombank',             'balanced', NULL, TRUE,  'T2'),
    ('TCGF',    'Quỹ Tăng Trưởng Techcombank',           'equity',   NULL, TRUE,  'T3'),
    ('VCBFTBF', 'Quỹ TPDN Có Bảo Đảm VCB Fund',         'bond',     31,   FALSE, 'T2'),
    ('VCBFBCF', 'Quỹ Trái Phiếu Bền Vững VCB Fund',     'bond',     32,   FALSE, 'T2'),
    ('VCBFEF',  'Quỹ Cổ Phiếu Việt Nam VCB Fund',       'equity',   28,   FALSE, 'T3'),
    ('SSISCA',  'Quỹ Tích Lũy Bền Vững SSI',            'equity',   11,   FALSE, 'T3'),
    ('MAFPF1',  'Quỹ Tích Lũy Hưu Trí Manulife',        'bond',     45,   FALSE, 'T2'),
    ('MAFEQI',  'Quỹ Cổ Phiếu Manulife',                'equity',   34,   FALSE, 'T3'),
    ('MBBF',    'Quỹ Trái Phiếu MB Capital',             'bond',     40,   FALSE, 'T2'),
    ('MBVF',    'Quỹ Cổ Phiếu MB Capital',              'equity',   35,   FALSE, 'T3'),
    ('ESSCF',   'Quỹ Cổ Phiếu Eastspring VN',           'equity',   47,   FALSE, 'T3'),
    ('ESBF',    'Quỹ Trái Phiếu Eastspring VN',         'bond',     46,   FALSE, 'T2'),
    ('BVPF',    'Quỹ Tăng Trưởng Bảo Việt',             'balanced', 20,   FALSE, 'T2'),
    ('MIRAEF',  'Quỹ Cổ Phiếu Mirae Asset VN',          'equity',   38,   FALSE, 'T3'),
    ('VNDAF',   'Quỹ Cổ Phiếu Năng Động VinaCapital',   'equity',   1,    FALSE, 'T3'),
    ('VNDBF',   'Quỹ Trái Phiếu VinaCapital',           'bond',     2,    FALSE, 'T2'),
    ('DCDS',    'Quỹ Tăng Trưởng Dragon Capital',        'equity',   6,    FALSE, 'T3'),
    ('DCBF',    'Quỹ Trái Phiếu Dragon Capital',         'bond',     5,    FALSE, 'T2')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    fund_type = EXCLUDED.fund_type,
    fmarket_id = EXCLUDED.fmarket_id,
    tcbs_tradeable = EXCLUDED.tcbs_tradeable,
    settlement_rule = EXCLUDED.settlement_rule;

-- ============================================================
-- VERIFICATION QUERY
-- ============================================================
-- SELECT count(*) FROM funds;           -- expect 19
-- SELECT count(*) FROM nav_history;     -- 0 until backfill
-- \d+ nav_history                       -- check partitions
