#!/usr/bin/env python3
# ============================================================
#  AutoTrader — main.py
#  Tiered watchlist: stocks (market hours) + crypto (24/7)
#  Tier 1: trade + learn | Tier 2: learn only | Tier 3: crypto trade
# ============================================================

import sys, os, time, argparse
from datetime import datetime, timezone

sys.path.append(os.path.dirname(__file__))
from config.settings import (
    get_stocks, get_crypto, get_learn_only, get_tradeable,
    TOTAL_TICKERS, TOTAL_TRADEABLE, TOTAL_LEARN_ONLY
)
from core.database import init_db, log_trade, close_trade, get_all_stats, get_connection
from core.broker import Broker
from agents.crew import run_supervisor
from agents.learning import run_learning_agent, print_learning_stats
from obsidian.vault_writer import (
    init_vault, write_trade_note, write_daily_note,
    update_trade_note_on_close, append_trade_to_daily, update_dashboard
)


def is_stock_market_open(broker: Broker) -> bool:
    return broker.is_market_open()


def check_and_close_positions(broker: Broker, dry_run: bool = False):
    """
    Dynamic position management — signal-based exits with hard stop-loss safety net.

    Exit conditions:
    1. HARD STOP: -3% loss — exits immediately no matter what
    2. PROFIT LOCK: if up >3%, stop moves to breakeven — never give back a win
    3. RSI EXHAUSTED: signal that opened trade is no longer valid
       - BUY opened on RSI<40 → close when RSI recovers above 55
       - SELL opened on RSI>65 → close when RSI drops below 50
    4. TREND REVERSAL: trend flips against position direction
    5. MAX HOLD: 5 days — nothing gets stuck forever
    """
    open_positions = broker.get_open_positions()
    if not open_positions:
        return

    conn = get_connection()
    c    = conn.cursor()

    for pos in open_positions:
        ticker        = pos["ticker"]
        current_price = pos["current_price"]
        direction     = pos.get("direction", "LONG")
        pnl_pct       = pos.get("pnl_pct", 0)

        c.execute(
            "SELECT * FROM trades WHERE ticker=? AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
            (ticker,)
        )
        row = c.fetchone()
        if not row:
            continue

        trade      = dict(row)
        stop_loss  = trade.get("stop_loss_price") or 0
        trade_id   = trade["trade_id"]
        opened_at  = trade.get("opened_at", "")

        should_close = False
        close_reason = ""
        stop_hit     = False

        # --------------------------------------------------------
        # 1. HARD STOP-LOSS — always fires, no exceptions
        # --------------------------------------------------------
        if direction == "SHORT":
            hard_stop = current_price >= stop_loss and stop_loss > 0
        else:
            hard_stop = current_price <= stop_loss and stop_loss > 0

        if hard_stop:
            should_close = True
            close_reason = "🛑 Stop-loss hit"
            stop_hit     = True

        # --------------------------------------------------------
        # 2. PROFIT LOCK — up >3%? Move stop to breakeven
        # --------------------------------------------------------
        elif pnl_pct >= 3.0 and not should_close:
            entry = trade.get("entry_price", current_price)
            # Tighten stop to entry price (breakeven)
            if direction == "SHORT":
                new_stop = entry * 1.005   # tiny buffer above entry for short
            else:
                new_stop = entry * 0.995   # tiny buffer below entry for long

            if direction == "SHORT" and current_price >= new_stop:
                should_close = True
                close_reason = f"🔒 Profit lock triggered — protecting +{pnl_pct:.1f}%"
            elif direction == "LONG" and current_price <= new_stop:
                should_close = True
                close_reason = f"🔒 Profit lock triggered — protecting +{pnl_pct:.1f}%"

        # --------------------------------------------------------
        # 3. RSI EXHAUSTED — signal no longer valid
        # --------------------------------------------------------
        if not should_close:
            try:
                prices     = broker.get_price_history(ticker, 40)
                rsi        = broker.calculate_rsi(prices)
                trend      = broker.calculate_trend(prices)
                entry      = trade.get("entry_price", current_price)
                # Use wider multiplier for stocks (4.5) vs crypto (3.0)
                is_crypto  = "-USD" in ticker
                multiplier = 3.0 if is_crypto else 4.5
                chandelier = broker.calculate_chandelier_exit(
                    prices, pnl_pct, direction, entry, multiplier=multiplier
                )

                if direction == "LONG" and rsi > 55:
                    should_close = True
                    close_reason = f"📊 RSI exhausted — signal done (RSI now {rsi}, was oversold)"
                elif direction == "SHORT" and rsi < 50:
                    should_close = True
                    close_reason = f"📊 RSI exhausted — signal done (RSI now {rsi}, was overbought)"

                # 3b. CHANDELIER EXIT — smarter trailing stop
                if not should_close and chandelier.get("should_close"):
                    should_close = True
                    close_reason = f"🕯️ Chandelier exit — {chandelier['reason']}"

                # 4. TREND REVERSAL
                if not should_close:
                    trend_dir = trend.get("direction", "sideways")
                    if direction == "LONG" and trend_dir == "downtrend" and trend.get("strength") == "strong":
                        should_close = True
                        close_reason = f"📉 Trend reversed against LONG position — strong downtrend detected"
                    elif direction == "SHORT" and trend_dir == "uptrend" and trend.get("strength") == "strong":
                        should_close = True
                        close_reason = f"📈 Trend reversed against SHORT position — strong uptrend detected"

            except Exception:
                pass   # if we can't get data, don't close

        # --------------------------------------------------------
        # 5. MAX HOLD — 5 days safety net
        # --------------------------------------------------------
        if not should_close and opened_at:
            try:
                from datetime import datetime, timezone
                opened  = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                days_held = (datetime.now(timezone.utc) - opened).days
                if days_held >= 5:
                    should_close = True
                    close_reason = f"⏰ Max hold time reached ({days_held} days)"
            except Exception:
                pass

        # --------------------------------------------------------
        # Execute close if any condition triggered
        # --------------------------------------------------------
        if should_close:
            print(f"\n  {close_reason}: {ticker} @ ${current_price:.4f} | P&L: {pnl_pct:+.1f}%")

            if not dry_run:
                try:
                    broker.close_position(ticker)
                except Exception as e:
                    print(f"  ⚠ Error closing {ticker}: {e}")
                    continue

            profit_loss, profit_pct_final = close_trade(
                trade_id, current_price,
                stop_hit=stop_hit, target_hit=False, close_reason=close_reason
            )
            closed = {
                **trade,
                "profit_loss": profit_loss, "profit_pct": profit_pct_final,
                "exit_price": current_price, "stop_hit": stop_hit, "target_hit": False
            }
            update_trade_note_on_close(closed)
            append_trade_to_daily(closed)
            run_learning_agent(closed, {"rsi": trade.get("rsi_at_entry"), "macd_crossover": trade.get("macd_crossover", False)})

            result = "WIN ✅" if profit_loss > 0 else "LOSS ❌"
            print(f"  {result} ${profit_loss:+.2f} ({profit_pct_final:+.1f}%)")

    conn.close()


def scan_batch(items: list, broker: Broker, dry_run: bool, learn_only: bool = False) -> int:
    """
    Scan a list of watchlist items.
    learn_only=True  → run full pipeline but skip order placement
    learn_only=False → run full pipeline and place orders if approved
    """
    trades = 0
    for item in items:
        ticker = item["ticker"]
        label  = item.get("label", ticker)
        tier   = item["tier"]
        try:
            decision = run_supervisor(ticker, broker)

            if decision["action"] in ("BUY", "SELL"):
                # Tier 2 = learn only — log lesson but skip order
                if learn_only or tier == 2:
                    print(f"  📚 LEARN ONLY — {decision['action']} signal on {label} logged, no order placed")
                    continue

                trade_data = {
                    "ticker":            ticker,
                    "direction":         decision["action"],
                    "entry_price":       decision["entry_price"],
                    "shares":            decision["shares"],
                    "stop_loss_price":   decision["stop_loss_price"],
                    "target_price":      decision["target_price"],
                    "signal_confidence": decision["signal_confidence"],
                    "rsi_at_entry":      decision.get("entry_market_data", {}).get("rsi"),
                    "agent_reasoning":   decision["agent_reasoning"],
                    "alpaca_order_id":   "DRY-RUN" if dry_run else None,
                }

                if not dry_run:
                    if decision["action"] == "BUY":
                        order = broker.place_market_buy(ticker, decision["shares"])
                    else:
                        # SELL = open a short position
                        order = broker.place_short_sell(ticker, decision["shares"])
                    trade_data["alpaca_order_id"] = order["alpaca_order_id"]

                trade_id = log_trade(trade_data)
                trade_data["trade_id"] = trade_id
                write_trade_note(trade_data)
                trades += 1

                print(f"\n  ✅ TRADE: {decision['action']} {label}")
                print(f"     {decision['shares']} shares @ ${decision['entry_price']:.2f}")
                print(f"     Stop: ${decision['stop_loss_price']} | Target: ${decision['target_price']}")
            else:
                print(f"  → {label}: {decision['action']}")

        except Exception as e:
            print(f"  ⚠ Error on {ticker}: {e}")
            continue

    return trades


def scan_and_trade(broker: Broker, dry_run: bool = False, crypto_only: bool = False):
    """Full scan — stocks during market hours, crypto always, learn-only always."""
    now = datetime.now(timezone.utc)
    stock_market_open = is_stock_market_open(broker)
    is_friday = now.weekday() == 4   # 0=Mon … 4=Fri

    print(f"\n{'='*55}")
    print(f"  Scan: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'PAPER TRADING'}")
    print(f"  Stock market: {'OPEN 🟢' if stock_market_open else 'CLOSED 🔴'}")
    if is_friday:
        print(f"  ⚠️  Friday — no new stock entries (gap risk)")
    print(f"  Watchlist: {TOTAL_TICKERS} tickers ({TOTAL_TRADEABLE} tradeable, {TOTAL_LEARN_ONLY} learn-only)")
    print(f"{'='*55}")

    write_daily_note()
    check_and_close_positions(broker, dry_run)
    total_trades = 0

    # --- Tier 1: S&P stocks — only during market hours, never on Friday ---
    if stock_market_open and not crypto_only:
        stocks = get_stocks()
        if is_friday:
            print(f"\n  📈 Scanning {len(stocks)} stocks (Friday — learn only, no new entries)...")
            total_trades += scan_batch(stocks, broker, dry_run, learn_only=True)
        else:
            print(f"\n  📈 Scanning {len(stocks)} stocks (market open)...")
            total_trades += scan_batch(stocks, broker, dry_run, learn_only=False)
    elif not crypto_only:
        print(f"\n  📈 Stock market closed — skipping {len(get_stocks())} stocks")

    # --- Tier 2: Learn-only — always runs (stocks + crypto) ---
    learn = get_learn_only()
    print(f"\n  📚 Scanning {len(learn)} learn-only tickers...")
    scan_batch(learn, broker, dry_run, learn_only=True)

    # --- Tier 3: Crypto — always runs 24/7 ---
    from config.settings import get_tier
    crypto_tradeable = get_tier(3)
    print(f"\n  ₿ Scanning {len(crypto_tradeable)} crypto tickers (24/7)...")
    total_trades += scan_batch(crypto_tradeable, broker, dry_run, learn_only=False)

    # Update dashboard
    stats     = get_all_stats()
    positions = broker.get_open_positions()
    update_dashboard(stats, positions)

    print(f"\n  ✓ Scan complete — {total_trades} trades executed")
    return total_trades


def run_loop(broker: Broker, interval_mins: int = 15):
    from weekly_report import generate_weekly_report
    print(f"\nAutoTrader running — {TOTAL_TICKERS} tickers across 3 tiers")
    print(f"  Stocks: scan during US market hours (3:30pm-10pm SA time)")
    print(f"  Crypto: scan 24/7")
    print(f"  Learn-only: always scanning, never trading")
    print(f"\nPress Ctrl+C to stop.\n")

    last_report_date  = None
    last_summary_date = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            scan_and_trade(broker)

            # Sunday weekly report
            if now.weekday() == 6 and now.hour >= 21:
                today = now.strftime("%Y-%m-%d")
                if last_report_date != today:
                    print("\n  📊 Sunday — generating weekly report + consistency scores...")
                    generate_weekly_report()
                    from core.consistency import score_all_tickers, auto_demote_check, write_consistency_to_obsidian
                    from agents.learning import load_lessons as ll
                    import os as _os
                    _lessons  = ll()
                    _scores   = score_all_tickers(_lessons)
                    _settings = _os.path.join(_os.path.dirname(__file__), "config", "settings.py")
                    _demoted  = auto_demote_check(_lessons, _settings)
                    from config.settings import OBSIDIAN_VAULT as _vault
                    write_consistency_to_obsidian(_scores, _vault, _demoted)
                    if _demoted:
                        print(f"  🔻 Auto-demoted: {', '.join(_demoted)}")
                    last_report_date = today

            time.sleep(interval_mins * 60)

        except KeyboardInterrupt:
            print("\n\nStopped. Refreshing dashboard...")
            update_dashboard(get_all_stats(), broker.get_open_positions())
            print_learning_stats()
            print("Done. Check Obsidian.")
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop",      action="store_true", help="Run every 15 mins")
    parser.add_argument("--test",      action="store_true", help="Dry run")
    parser.add_argument("--dashboard", action="store_true", help="Refresh dashboard only")
    parser.add_argument("--setup",     action="store_true", help="First time setup")
    parser.add_argument("--learn",     action="store_true", help="Show learning stats")
    parser.add_argument("--crypto",    action="store_true", help="Scan crypto only")
    args = parser.parse_args()

    print("\n" + "="*55)
    print("  AutoTrader — AI-powered paper trading")
    print("="*55)

    if args.setup:
        print("\nRunning first-time setup...")
        init_db()
        init_vault()
        from config.settings import OBSIDIAN_VAULT
        os.makedirs(os.path.join(OBSIDIAN_VAULT, "Learning"), exist_ok=True)
        print(f"\n  Watchlist summary:")
        print(f"  Total tickers   : {TOTAL_TICKERS}")
        print(f"  Tradeable       : {TOTAL_TRADEABLE}")
        print(f"  Learn-only      : {TOTAL_LEARN_ONLY}")
        print(f"\n✓ Setup complete!")
        return

    if args.learn:
        print_learning_stats()
        return

    init_db()
    init_vault()
    broker = Broker()
    acct   = broker.get_account()
    print(f"\n  Portfolio : R{acct['portfolio_value']:,.2f}")
    print(f"  Cash      : R{acct['cash']:,.2f}")
    print(f"  Tickers   : {TOTAL_TICKERS} ({TOTAL_TRADEABLE} tradeable, {TOTAL_LEARN_ONLY} learn-only)")

    if args.dashboard:
        update_dashboard(get_all_stats(), broker.get_open_positions())
        print("  Dashboard refreshed.")
        return

    if args.loop:
        run_loop(broker)
    else:
        scan_and_trade(broker, dry_run=args.test, crypto_only=args.crypto)


if __name__ == "__main__":
    main()
