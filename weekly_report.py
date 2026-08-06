#!/usr/bin/env python3
# ============================================================
#  AutoTrader — weekly_report.py
#  Generates a full weekly summary in your Obsidian vault.
#  Run manually anytime: python3 weekly_report.py
#  Or it auto-runs every Sunday when you have --loop running.
# ============================================================

import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
sys.path.append(os.path.dirname(__file__))
from config.settings import OBSIDIAN_VAULT, DB_PATH
from core.database import get_all_stats, get_connection

DB_PATH = os.path.join(os.path.dirname(__file__), "autotrader.db")


def get_weekly_trades() -> list:
    """Pull all trades closed in the last 7 days."""
    conn = get_connection()
    c = conn.cursor()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    c.execute("""
        SELECT * FROM trades
        WHERE status = 'CLOSED'
        AND closed_at >= ?
        ORDER BY closed_at DESC
    """, (week_ago,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_all_trades() -> list:
    """Pull every closed trade ever."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE status='CLOSED' ORDER BY closed_at DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_ticker_breakdown() -> list:
    """Best and worst performers by ticker, all time."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT
            ticker,
            COUNT(*) as total_trades,
            SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins,
            SUM(profit_loss) as total_pnl,
            MAX(profit_loss) as best_trade,
            MIN(profit_loss) as worst_trade,
            AVG(profit_pct) as avg_return_pct
        FROM trades
        WHERE status = 'CLOSED'
        GROUP BY ticker
        ORDER BY total_pnl DESC
    """)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def generate_weekly_report():
    """Write the full weekly report to Obsidian."""
    now        = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_end   = now.strftime("%Y-%m-%d")
    filename   = f"Week-{week_start}.md"
    folder     = os.path.join(OBSIDIAN_VAULT, "Weekly Summaries")
    filepath   = os.path.join(folder, filename)
    os.makedirs(folder, exist_ok=True)

    weekly_trades = get_weekly_trades()
    all_stats     = get_all_stats()
    ticker_stats  = get_ticker_breakdown()

    # Weekly numbers
    w_total  = len(weekly_trades)
    w_wins   = sum(1 for t in weekly_trades if (t.get("profit_loss") or 0) > 0)
    w_losses = w_total - w_wins
    w_pnl    = sum((t.get("profit_loss") or 0) for t in weekly_trades)
    w_rate   = round((w_wins / w_total * 100) if w_total > 0 else 0, 1)

    best_week  = max(weekly_trades, key=lambda t: t.get("profit_loss") or 0, default=None)
    worst_week = min(weekly_trades, key=lambda t: t.get("profit_loss") or 0, default=None)
    best_week_str  = (best_week["ticker"] + " $" + f"{(best_week.get('profit_loss') or 0):+.2f}") if best_week else "—"
    worst_week_str = (worst_week["ticker"] + " $" + f"{(worst_week.get('profit_loss') or 0):+.2f}") if worst_week else "—" 

    # Emoji indicators
    pnl_emoji = "📈" if w_pnl >= 0 else "📉"
    wr_emoji  = "🟢" if w_rate >= 55 else "🟡" if w_rate >= 45 else "🔴"
    verdict   = (
        "✅ Profitable week — system is performing well."
        if w_pnl > 0 and w_rate >= 55 else
        "⚠️ Mixed week — monitor signals closely next week."
        if w_pnl > 0 or w_rate >= 45 else
        "❌ Tough week — review signal rules before continuing."
        if w_total > 0 else
        "😴 No trades closed this week — market may have been quiet or mostly HOLD signals."
    )

    # Build weekly trades table
    if weekly_trades:
        trade_rows = "\n".join([
            f"| {(t.get('closed_at') or '')[:10]} "
            f"| {t['ticker']} "
            f"| {t['direction']} "
            f"| ${t.get('entry_price', 0):.2f} "
            f"| ${t.get('exit_price', 0):.2f} "
            f"| ${(t.get('profit_loss') or 0):+.2f} "
            f"| {(t.get('profit_pct') or 0):+.1f}% "
            f"| {'✅' if (t.get('profit_loss') or 0) >= 0 else '❌'} |"
            for t in weekly_trades
        ])
    else:
        trade_rows = "| — | — | — | — | — | — | — | — |"

    # Build ticker breakdown table
    if ticker_stats:
        ticker_rows = "\n".join([
            f"| {t['ticker']} "
            f"| {t['total_trades']} "
            f"| {t['wins']}/{t['total_trades']} "
            f"| ${(t['total_pnl'] or 0):+.2f} "
            f"| ${(t['best_trade'] or 0):+.2f} "
            f"| ${(t['worst_trade'] or 0):+.2f} "
            f"| {(t['avg_return_pct'] or 0):+.1f}% |"
            for t in ticker_stats
        ])
    else:
        ticker_rows = "| — | — | — | — | — | — | — |"

    # Advice section based on performance
    if w_rate >= 60 and w_pnl > 0:
        advice = """- System is performing well — no changes needed
- Consider expanding watchlist with similar signal-quality stocks
- If this continues for 4 weeks, you're ready to consider going live"""
    elif w_rate >= 45:
        advice = """- Win rate is borderline — watch closely next week
- Review which tickers are causing losses and consider removing them
- Don't change signal rules yet — need more data"""
    else:
        advice = """- Win rate is below target — system needs review
- Check if losses are happening at market open (volatile) — consider delaying first scan to 10am ET
- Review the HOLD confidence threshold — may need to raise minimum confidence to 70%"""

    content = f"""---
week: {week_start}
generated: {now.strftime("%Y-%m-%d %H:%M UTC")}
trades: {w_total}
net_pnl: {w_pnl:+.2f}
win_rate: {w_rate}
tags: [weekly, summary, trading]
---

# {pnl_emoji} Weekly report — {week_start} to {week_end}
*Auto-generated by AutoTrader on {now.strftime("%Y-%m-%d at %H:%M UTC")}*

---

## This week at a glance

| Metric | This week | All time |
|---|---|---|
| Trades | {w_total} | {all_stats.get('total_trades', 0)} |
| Wins | {w_wins} | {all_stats.get('wins', 0)} |
| Losses | {w_losses} | {all_stats.get('losses', 0)} |
| {wr_emoji} Win rate | {w_rate}% | {all_stats.get('win_rate', 0)}% |
| {pnl_emoji} Net P&L | ${w_pnl:+.2f} | ${all_stats.get('total_pnl', 0):+.2f} |
| Best trade | {best_week_str} | {all_stats.get('best_profit_ticker', '—')} ${all_stats.get('best_profit', 0):+.2f} |
| Worst trade | {worst_week_str} | {all_stats.get('worst_loss_ticker', '—')} ${all_stats.get('worst_loss', 0):.2f} |

---

## Verdict
{verdict}

---

## All trades this week

| Date | Ticker | Direction | Entry | Exit | P&L | Return | Result |
|---|---|---|---|---|---|---|---|
{trade_rows}

---

## All-time ticker breakdown

| Ticker | Trades | Win/Total | Total P&L | Best trade | Worst trade | Avg return |
|---|---|---|---|---|---|---|
{ticker_rows}

---

## Agent system notes
{advice}

---

## Go-live checklist
- {'✅' if all_stats.get('win_rate', 0) >= 55 else '❌'} Win rate above 55% ({all_stats.get('win_rate', 0)}%)
- {'✅' if all_stats.get('total_trades', 0) >= 30 else '❌'} At least 30 trades completed ({all_stats.get('total_trades', 0)}/30)
- {'✅' if (all_stats.get('worst_loss', 0) or 0) > -200 else '❌'} No single loss over $200 (worst: ${all_stats.get('worst_loss', 0):.2f})

*All three boxes green = you're ready to go live with real money* 🚀

---
[[DASHBOARD]] | [[Daily Notes]] | [[Weekly Summaries]]
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n{'='*50}")
    print(f"  Weekly report generated!")
    print(f"  File: Weekly Summaries/{filename}")
    print(f"  Trades this week : {w_total}")
    print(f"  Win rate         : {w_rate}%")
    print(f"  Net P&L          : ${w_pnl:+.2f}")
    print(f"  Verdict          : {verdict}")
    print(f"{'='*50}\n")
    return filepath


if __name__ == "__main__":
    print("\nGenerating weekly report...")
    generate_weekly_report()

    # Also run consistency scores
    print("\nCalculating consistency scores...")
    from core.consistency import score_all_tickers, auto_demote_check, write_consistency_to_obsidian
    from agents.learning import load_lessons
    from config.settings import OBSIDIAN_VAULT
    import os
    lessons  = load_lessons()
    scores   = score_all_tickers(lessons)
    settings = os.path.join(os.path.dirname(__file__), "config", "settings.py")
    demoted  = auto_demote_check(lessons, settings)
    write_consistency_to_obsidian(scores, OBSIDIAN_VAULT, demoted)
    print("Done — open Obsidian to see your Weekly Summaries and Performance folders.")
