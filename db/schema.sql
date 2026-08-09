-- AutoTrader Postgres schema (Supabase project, eu-north-1)
-- Hand-migrated from the SQLite `trades` table in autotrader.db as a Postgres/pgvector
-- fluency exercise. NOT wired into main.py — SQLite remains the live datastore.
--
-- Key type-mapping decisions vs. the SQLite source:
--   - id:               SQLite AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
--   - money/price cols:  SQLite REAL (float) -> NUMERIC, to avoid binary float
--                        representation error on exact financial values
--   - status/direction: SQLite free TEXT -> Postgres ENUM (status_type, trade_direction)
--   - stop_hit/target_hit: SQLite 0/1 INTEGER -> BOOLEAN
--   - opened_at/closed_at: SQLite ISO8601 TEXT -> TIMESTAMPTZ
--
-- Column sizing was checked against real data in autotrader.db, not guessed:
--   - price columns: NUMERIC(14,8) — real entry_price ranges from 1.518e-05 (micro-cap
--     crypto) to ~1931.20; scale 8 preserves sub-cent precision, precision 14 leaves
--     headroom well past any realistic single-unit price.
--   - profit_pct: NUMERIC(5,2) — real range is -4.68 to 3.90, matching the 2-decimal
--     precision already used for signal_confidence/rsi_at_entry.
--   - shares: NUMERIC(16,6) — real range is 5.9e-05 to 4,524,965.63 (low-priced tokens
--     bought with a fixed dollar amount produce large share counts); an initial
--     NUMERIC(10,6) overflowed on real data and was widened.

create type status_type as enum ('OPEN', 'CLOSED', 'CANCELLED');
create type trade_direction as enum ('BUY', 'SELL');

create table trades (
    id                 integer        generated always as identity primary key,
    trade_id           text           unique not null,
    ticker             text           not null,
    direction          trade_direction not null,
    entry_price        numeric(14, 8),
    exit_price         numeric(14, 8),
    profit_loss        numeric(14, 8),
    profit_pct         numeric(5, 2),
    stop_loss_price    numeric(14, 8),
    target_price       numeric(14, 8),
    signal_confidence  numeric(5, 2),
    rsi_at_entry       numeric(5, 2),
    shares             numeric(16, 6),
    status             status_type default 'OPEN',
    opened_at          timestamptz    not null,
    closed_at          timestamptz,
    duration_mins      real,
    target_hit         boolean default false,
    stop_hit           boolean default false,
    agent_reasoning    text,
    alpaca_order_id    text,
    close_reason       text
);

-- Sample rows migrated from real closed trades in autotrader.db, used to prove the
-- schema holds against real data rather than migrating all 266 historical rows.

insert into trades (trade_id, ticker, direction, entry_price, exit_price, profit_loss, profit_pct, status, opened_at, closed_at, stop_hit, target_hit, shares, signal_confidence, rsi_at_entry)
values ('T-20260602141521-ADA-USD', 'ADA-USD', 'BUY', 0.222, 0.21520001, -30.5855586255712, -3.06305855855856, 'CLOSED', '2026-06-02T14:15:21.596653+00:00', '2026-06-02T15:31:38.358629+00:00', true, false, 4497.882883, 80.0, NULL);

insert into trades (trade_id, ticker, direction, entry_price, exit_price, profit_loss, profit_pct, status, opened_at, closed_at, stop_hit, target_hit, shares, signal_confidence, rsi_at_entry)
values ('T-20260602141644-NEAR-USD', 'NEAR-USD', 'SELL', 2.67899, 2.630011, 18.2606073859186, 1.829032916035061, 'CLOSED', '2026-06-02T14:16:44.140074+00:00', '2026-06-02T14:33:41.840074+00:00', true, true, 372.667054, 80.0, NULL);

insert into trades (trade_id, ticker, direction, entry_price, exit_price, profit_loss, profit_pct, status, opened_at, closed_at, stop_hit, target_hit, shares, signal_confidence, rsi_at_entry)
values ('T-20260602141656-ARB-USD', 'ARB-USD', 'SELL', 0.00075706, 0.00075706, 0.0, 0.0, 'CLOSED', '2026-06-02T14:16:56.401963+00:00', '2026-06-02T14:33:45.567658+00:00', true, true, 1450920.66679, 80.0, NULL);
