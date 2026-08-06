# ============================================================
#  AutoTrader — core/database.py
#  Sets up SQLite. Run once, works forever.
# ============================================================

import sqlite3
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets you access columns by name
    return conn


def init_db():
    """Create all tables if they don't exist yet."""
    conn = get_connection()
    c = conn.cursor()

    # Every single trade ever made
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id         TEXT UNIQUE,
            ticker           TEXT NOT NULL,
            direction        TEXT NOT NULL,       -- BUY or SELL
            entry_price      REAL,
            exit_price       REAL,
            shares           REAL,
            profit_loss      REAL,
            profit_pct       REAL,
            status           TEXT DEFAULT 'OPEN', -- OPEN, CLOSED, CANCELLED
            stop_loss_price  REAL,
            target_price     REAL,
            signal_confidence REAL,
            agent_reasoning  TEXT,
            alpaca_order_id  TEXT,
            opened_at        TEXT,
            closed_at        TEXT,
            duration_mins    REAL,
            stop_hit         INTEGER DEFAULT 0,   -- 1 if stop-loss triggered
            target_hit       INTEGER DEFAULT 0    -- 1 if take-profit triggered
        )
    """)

    # Daily performance snapshot
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT UNIQUE,
            trades_opened   INTEGER DEFAULT 0,
            trades_closed   INTEGER DEFAULT 0,
            wins            INTEGER DEFAULT 0,
            losses          INTEGER DEFAULT 0,
            gross_profit    REAL DEFAULT 0,
            gross_loss      REAL DEFAULT 0,
            net_pnl         REAL DEFAULT 0,
            best_trade_pct  REAL DEFAULT 0,
            worst_trade_pct REAL DEFAULT 0,
            portfolio_value REAL DEFAULT 0
        )
    """)

    # Agent decision log — every agent call recorded
    c.execute("""
        CREATE TABLE IF NOT EXISTS agent_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id    TEXT,
            agent_name  TEXT,
            input_data  TEXT,
            output_data TEXT,
            tokens_used INTEGER,
            timestamp   TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("✓ Database ready at:", os.path.abspath(DB_PATH))


def log_trade(trade_data: dict) -> str:
    """Insert a new trade. Returns the trade_id."""
    import uuid
    from datetime import datetime, timezone

    trade_id = f"T-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{trade_data['ticker']}"
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO trades
        (trade_id, ticker, direction, entry_price, shares, status,
         stop_loss_price, target_price, signal_confidence, agent_reasoning,
         alpaca_order_id, opened_at, rsi_at_entry)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade_id,
        trade_data["ticker"],
        trade_data["direction"],
        trade_data["entry_price"],
        trade_data["shares"],
        "OPEN",
        trade_data.get("stop_loss_price"),
        trade_data.get("target_price"),
        trade_data.get("signal_confidence"),
        trade_data.get("agent_reasoning"),
        trade_data.get("alpaca_order_id"),
        datetime.now(timezone.utc).isoformat(),
        trade_data.get("rsi_at_entry"),
    ))
    conn.commit()
    conn.close()
    return trade_id


def close_trade(trade_id: str, exit_price: float, stop_hit=False, target_hit=False, close_reason=None):
    """Mark a trade closed and calculate P&L."""
    from datetime import datetime, timezone

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
    trade = dict(c.fetchone())

    shares = trade["shares"]
    entry  = trade["entry_price"]
    direction = trade["direction"]

    if direction == "BUY":
        profit_loss = (exit_price - entry) * shares
        profit_pct  = ((exit_price - entry) / entry) * 100
    else:
        profit_loss = (entry - exit_price) * shares
        profit_pct  = ((entry - exit_price) / entry) * 100

    opened_at = datetime.fromisoformat(trade["opened_at"])
    closed_at = datetime.now(timezone.utc)
    duration  = (closed_at - opened_at).total_seconds() / 60

    c.execute("""
        UPDATE trades SET
            exit_price   = ?,
            profit_loss  = ?,
            profit_pct   = ?,
            status       = 'CLOSED',
            closed_at    = ?,
            duration_mins= ?,
            stop_hit     = ?,
            target_hit   = ?,
            close_reason = ?
        WHERE trade_id = ?
    """, (exit_price, profit_loss, profit_pct,
          closed_at.isoformat(), duration,
          int(stop_hit), int(target_hit), close_reason, trade_id))
    conn.commit()
    conn.close()
    return profit_loss, profit_pct


def get_all_stats() -> dict:
    """Pull the headline stats for the dashboard."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM trades WHERE status='CLOSED'")
    total_trades = c.fetchone()[0]

    c.execute("SELECT SUM(profit_loss) FROM trades WHERE status='CLOSED'")
    total_pnl = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*) FROM trades WHERE status='CLOSED' AND profit_loss > 0")
    wins = c.fetchone()[0]

    c.execute("SELECT MAX(profit_loss), ticker FROM trades WHERE status='CLOSED'")
    row = c.fetchone()
    best_profit, best_ticker = (row[0] or 0), (row[1] or "—")

    c.execute("SELECT MIN(profit_loss), ticker FROM trades WHERE status='CLOSED'")
    row = c.fetchone()
    worst_loss, worst_ticker = (row[0] or 0), (row[1] or "—")

    c.execute("""
        SELECT ticker, SUM(profit_loss) as total
        FROM trades WHERE status='CLOSED'
        GROUP BY ticker ORDER BY total DESC LIMIT 1
    """)
    row = c.fetchone()
    best_stock = row[1] if row else "—"
    best_stock_ticker = row[0] if row else "—"

    conn.close()
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    return {
        "total_trades":       total_trades,
        "total_pnl":          round(total_pnl, 2),
        "wins":               wins,
        "losses":             total_trades - wins,
        "win_rate":           round(win_rate, 1),
        "best_profit":        round(best_profit, 2),
        "best_profit_ticker": best_ticker,
        "worst_loss":         round(worst_loss, 2),
        "worst_loss_ticker":  worst_ticker,
        "best_stock_ticker":  best_stock_ticker,
        "best_stock_total":   round(best_stock, 2) if best_stock != "—" else 0,
    }


if __name__ == "__main__":
    init_db()
