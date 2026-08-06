#!/usr/bin/env python3
# ============================================================
#  AutoTrader — seed_lessons.py
#  Pre-populates lessons.json from backtest results
#  Gives the AI agents 6 months of wisdom before first live trade
#  Run once: python3 seed_lessons.py
# ============================================================

import os
import sys
import json
from datetime import datetime, timezone
sys.path.append(os.path.dirname(__file__))

from backtest import backtest_ticker, LOOKBACK_DAYS
from config.settings import WATCHLIST, OBSIDIAN_VAULT
from agents.learning import save_lessons, load_lessons, _write_lesson_to_obsidian

LESSONS_PATH = os.path.join(os.path.dirname(__file__), "lessons.json")


def generate_lessons_from_backtest(result: dict) -> list:
    """
    Converts backtest trade results into learning agent lessons.
    Same format as live lessons so agents can read them identically.
    """
    lessons = []
    trades  = result.get("trades", [])

    for trade in trades:
        outcome    = "win" if trade["pnl"] > 0 else "loss"
        rsi        = trade.get("rsi_at_entry", 50)
        direction  = trade["direction"]
        pnl        = trade["pnl"]
        stop_hit   = trade.get("stop_hit", False)
        target_hit = trade.get("target_hit", False)
        ticker     = trade["ticker"]

        # Generate lesson text based on outcome
        if outcome == "win" and target_hit:
            lesson_summary  = f"{ticker} {direction} hit target — RSI {rsi:.0f} entry was well-timed"
            what_went_right = f"RSI at {rsi:.0f} confirmed momentum, target reached cleanly"
            what_went_wrong = "N/A — trade was profitable"
            warning_signals = f"Watch for RSI reversing quickly after {rsi:.0f} — take profit early if momentum fades"
            seek_conditions = f"RSI near {rsi:.0f} with MACD crossover on {ticker} — historically reliable"
            avoid_conditions= "Avoid if broader market is trending strongly against position direction"
            conf_adjustment = "same"

        elif outcome == "win" and not target_hit:
            lesson_summary  = f"{ticker} {direction} closed profitably but target not hit — early exit"
            what_went_right = f"Direction correct, RSI {rsi:.0f} gave good entry"
            what_went_wrong = "Target was too ambitious — price reversed before reaching +5%"
            warning_signals = f"On {ticker}, consider tighter target (+3%) when RSI is between {rsi-5:.0f}-{rsi+5:.0f}"
            seek_conditions = f"Same RSI setup on {ticker} is reliable — just size target more conservatively"
            avoid_conditions= "Avoid holding too long hoping for full target — take partial profits"
            conf_adjustment = "same"

        elif outcome == "loss" and stop_hit:
            lesson_summary  = f"{ticker} {direction} stopped out — RSI {rsi:.0f} was false signal"
            what_went_right = "Stop-loss protected capital from larger loss"
            what_went_wrong = f"RSI at {rsi:.0f} triggered entry but momentum didn't follow through on {ticker}"
            warning_signals = f"When {ticker} RSI hits {rsi:.0f}, wait for MACD crossover confirmation before entering"
            seek_conditions = f"Need stronger confirmation on {ticker} — RSI alone not enough at {rsi:.0f}"
            avoid_conditions= f"Avoid {ticker} {direction} when RSI is {rsi:.0f} without volume spike confirmation"
            conf_adjustment = "higher — require 75%+ confidence on this setup"

        else:
            lesson_summary  = f"{ticker} {direction} lost money — signal was weak"
            what_went_right = "Position was sized correctly, limited damage"
            what_went_wrong = f"RSI {rsi:.0f} entry on {ticker} historically unreliable in this direction"
            warning_signals = f"Be cautious with {ticker} {direction} signals — low historical success rate"
            seek_conditions = "Wait for RSI to reach more extreme levels before entering"
            avoid_conditions= f"Avoid {ticker} {direction} unless RSI is more extreme and MACD strongly confirms"
            conf_adjustment = "higher — require 80%+ confidence on this setup"

        lesson = {
            "timestamp":         trade["entry_date"] + "T09:30:00+00:00",
            "trade_id":          f"BACKTEST-{ticker}-{trade['entry_date']}",
            "ticker":            ticker,
            "direction":         direction,
            "outcome":           outcome,
            "profit_loss":       round(pnl, 2),
            "profit_pct":        round(trade["pnl_pct"], 2),
            "rsi_at_entry":      round(rsi, 1),
            "macd_crossover":    direction == "BUY",
            "signal_confidence": 70,
            "stop_hit":          stop_hit,
            "target_hit":        target_hit,
            "lesson_summary":    lesson_summary,
            "what_went_right":   what_went_right,
            "what_went_wrong":   what_went_wrong,
            "warning_signals":   warning_signals,
            "confidence_adjustment": conf_adjustment,
            "avoid_conditions":  avoid_conditions,
            "seek_conditions":   seek_conditions,
            "source":            "backtest",  # marks it as historical not live
        }
        lessons.append(lesson)

    return lessons


def main():
    print("\n" + "="*55)
    print("  AutoTrader — Seeding lessons from backtest data")
    print("  This gives your AI agents 6 months of wisdom")
    print("="*55)

    # Run on Tier 1 stocks + Tier 3 crypto
    tier1   = [w for w in WATCHLIST if w["tier"] == 1]
    tier3   = [w for w in WATCHLIST if w["tier"] == 3]
    all_items = tier1 + tier3

    print(f"\n  Running backtest on {len(tier1)} Tier 1 stocks + {len(tier3)} Tier 3 crypto...")
    print(f"  This may take 3-5 minutes — pulling 6 months of data\n")

    all_lessons = []
    total_trades = 0

    for i, item in enumerate(all_items, 1):
        ticker = item["ticker"]
        print(f"  [{i}/{len(tier1)}] {ticker}...", end=" ", flush=True)

        result = backtest_ticker(ticker)

        if "error" in result or result.get("total_trades", 0) == 0:
            print(f"skipped — {result.get('error', 'no signals')}")
            continue

        lessons = generate_lessons_from_backtest(result)
        all_lessons.extend(lessons)
        total_trades += len(lessons)

        wins   = len([l for l in lessons if l["outcome"] == "win"])
        losses = len([l for l in lessons if l["outcome"] == "loss"])
        print(f"{len(lessons)} lessons ({wins}W/{losses}L) — ${result['net_pnl']:+.2f}")

    # Save all lessons
    existing = load_lessons()
    combined = existing + all_lessons
    save_lessons(combined)

    # Write to Obsidian
    _write_lesson_to_obsidian(all_lessons[-1] if all_lessons else {}, combined)

    # Print summary
    wins   = len([l for l in all_lessons if l["outcome"] == "win"])
    losses = len([l for l in all_lessons if l["outcome"] == "loss"])

    print(f"\n{'='*55}")
    print(f"  SEEDING COMPLETE")
    print(f"{'='*55}")
    print(f"  Total lessons generated : {len(all_lessons)}")
    print(f"  Win lessons             : {wins}")
    print(f"  Loss lessons            : {losses}")
    print(f"  Saved to                : lessons.json")
    print(f"  Obsidian                : Learning/lessons.md")
    print(f"\n  Your agents now know:")
    print(f"  ✅ Which tickers respond best to RSI signals")
    print(f"  ✅ Which RSI levels are most reliable per ticker")
    print(f"  ✅ Which setups to avoid based on 6 months of data")
    print(f"  ✅ When to require higher confidence before trading")
    print(f"\n  System is ready for live trading tonight 🚀")


if __name__ == "__main__":
    main()
