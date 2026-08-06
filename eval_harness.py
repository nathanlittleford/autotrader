# ============================================================
#  AutoTrader — eval_harness.py
#  Standalone evaluation script: scores the agent pipeline's
#  decisions against real trade outcomes.
#
#  Usage:
#      python3 eval_harness.py
#
#  Reads:  autotrader.db (trades table only — agent_log is
#          currently unused by crew.py, so this works entirely
#          off columns already written on every closed trade).
#
#  Each eval_* function both prints its section (unchanged CLI
#  behavior) and returns a stats dict, so generate_eval_report.py
#  can import this module and build reports off the same numbers
#  without re-parsing console output.
# ============================================================

import re
import sqlite3
import sys
import os
from collections import defaultdict

sys.path.append(os.path.dirname(__file__))

try:
    from config.settings import DB_PATH
except Exception:
    DB_PATH = "autotrader.db"  # fallback if run outside the project structure


# Fixed prefixes each close_reason string starts with in main.py —
# the rest (percentages, RSI values, day counts) is dynamic per-trade,
# so group by prefix rather than the raw string.
CLOSE_REASON_CATEGORIES = [
    ("Stop-loss hit", "Stop-loss hit"),
    ("Profit lock triggered", "Profit lock"),
    ("RSI exhausted", "RSI exhausted"),
    ("Chandelier exit", "Chandelier exit"),
    ("Trend reversed", "Trend reversal"),
    ("Max hold time reached", "Max hold"),
]


def categorize_close_reason(close_reason: str) -> str:
    for marker, label in CLOSE_REASON_CATEGORIES:
        if marker in close_reason:
            return label
    return "Other"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_closed_trades(conn):
    c = conn.cursor()
    c.execute("""
        SELECT ticker, direction, entry_price, exit_price, profit_loss,
               profit_pct, signal_confidence, rsi_at_entry, agent_reasoning,
               stop_hit, target_hit, close_reason, opened_at, closed_at
        FROM trades
        WHERE status = 'CLOSED'
    """)
    return [dict(row) for row in c.fetchall()]


def extract_lessons_applied(agent_reasoning: str) -> int:
    """Pull the 'Lessons: N applied' count out of the free-text reasoning field."""
    if not agent_reasoning:
        return 0
    match = re.search(r"Lessons:\s*(\d+)\s*applied", agent_reasoning)
    return int(match.group(1)) if match else 0


def win_rate(trades: list) -> dict:
    if not trades:
        return {"n": 0, "wins": 0, "win_rate": None}
    wins = sum(1 for t in trades if (t["profit_loss"] or 0) > 0)
    return {
        "n": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades) * 100, 1),
    }


def eval_precision_by_direction(trades: list) -> dict:
    print("\n=== 1. Precision by direction ===")
    result = {}
    for direction in ("BUY", "SELL"):
        subset = [t for t in trades if t["direction"] == direction]
        stats = win_rate(subset)
        if stats["n"] == 0:
            print(f"  {direction}: no closed trades")
            result[direction] = {**stats, "avg_pnl": None}
            continue
        avg_pnl = round(sum(t["profit_pct"] or 0 for t in subset) / stats["n"], 2)
        print(f"  {direction}: {stats['wins']}/{stats['n']} win ({stats['win_rate']}%), "
              f"avg P&L {avg_pnl}%")
        result[direction] = {**stats, "avg_pnl": avg_pnl}
    return result


def eval_confidence_calibration(trades: list) -> dict:
    print("\n=== 2. Confidence calibration ===")
    buckets = [(60, 70), (70, 80), (80, 90), (90, 101)]
    rows = []
    for lo, hi in buckets:
        subset = [t for t in trades
                   if t["signal_confidence"] is not None
                   and lo <= t["signal_confidence"] < hi]
        stats = win_rate(subset)
        label = f"{lo}-{hi if hi <= 100 else 100}%"
        rows.append((label, stats))
        if stats["n"] == 0:
            print(f"  {label} confidence: no trades")
        else:
            print(f"  {label} confidence: {stats['wins']}/{stats['n']} win "
                  f"({stats['win_rate']}%)")

    rates = [r[1]["win_rate"] for r in rows if r[1]["win_rate"] is not None]
    monotonic = None
    if len(rates) >= 2:
        monotonic = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
        print(f"  → Monotonically increasing with confidence: {monotonic}")
        if not monotonic:
            print("  → FINDING: confidence score is not well-calibrated — "
                  "higher stated confidence doesn't reliably mean higher win rate.")

    return {"buckets": rows, "monotonic": monotonic}


def eval_rsi_extremity(trades: list) -> dict:
    print("\n=== 3. RSI-at-entry vs outcome ===")
    subset = [t for t in trades if t["rsi_at_entry"] is not None]
    if not subset:
        print("  No trades with rsi_at_entry recorded.")
        return {"n": 0, "less_extreme": None, "more_extreme": None}
    for t in subset:
        t["_rsi_extremity"] = abs(t["rsi_at_entry"] - 50)
    subset.sort(key=lambda t: t["_rsi_extremity"])
    midpoint = len(subset) // 2
    less_extreme, more_extreme = subset[:midpoint], subset[midpoint:]
    lo_stats = win_rate(less_extreme)
    hi_stats = win_rate(more_extreme)
    print(f"  Less extreme RSI (closer to 50): {lo_stats['wins']}/{lo_stats['n']} "
          f"win ({lo_stats['win_rate']}%)")
    print(f"  More extreme RSI (further from 50): {hi_stats['wins']}/{hi_stats['n']} "
          f"win ({hi_stats['win_rate']}%)")
    return {"n": len(subset), "less_extreme": lo_stats, "more_extreme": hi_stats}


def eval_lessons_influence(trades: list) -> dict:
    print("\n=== 4. Lessons-influenced vs not ===")
    with_lessons, without_lessons = [], []
    for t in trades:
        n = extract_lessons_applied(t["agent_reasoning"])
        (with_lessons if n > 0 else without_lessons).append(t)
    ws = win_rate(with_lessons)
    wo = win_rate(without_lessons)
    print(f"  With lessons applied:    {ws['wins']}/{ws['n']} win ({ws['win_rate']}%)")
    print(f"  Without lessons applied: {wo['wins']}/{wo['n']} win ({wo['win_rate']}%)")
    return {"with_lessons": ws, "without_lessons": wo}


def eval_stop_target_hit_rate(trades: list) -> dict:
    print("\n=== 5. Stop/target hit rate ===")
    n = len(trades)
    if n == 0:
        print("  No closed trades.")
        return {"n": 0, "stop_hit": 0, "target_hit": 0, "neither": 0}
    stop_hits = sum(1 for t in trades if t["stop_hit"])
    target_hits = sum(1 for t in trades if t["target_hit"])
    neither = n - stop_hits - target_hits
    print(f"  Stop hit:   {stop_hits}/{n} ({round(stop_hits/n*100, 1)}%)")
    print(f"  Target hit: {target_hits}/{n} ({round(target_hits/n*100, 1)}%)")
    print(f"  Closed some other way (manual/EOD/etc): {neither}/{n} "
          f"({round(neither/n*100, 1)}%)")
    return {"n": n, "stop_hit": stop_hits, "target_hit": target_hits, "neither": neither}


def eval_close_reason_breakdown(trades: list) -> dict:
    print("\n=== 6. Win rate / avg P&L by close reason ===")
    subset = [t for t in trades if t.get("close_reason")]
    result = {"n": len(subset), "buckets": {}}
    if not subset:
        print("  No trades with close_reason recorded yet — this field is forward-only")
        print("  (added after the existing closed trades), so it populates as new")
        print("  trades close going forward.")
        return result

    grouped = defaultdict(list)
    for t in subset:
        grouped[categorize_close_reason(t["close_reason"])].append(t)

    for label, group in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        stats = win_rate(group)
        avg_pnl = round(sum(t["profit_pct"] or 0 for t in group) / stats["n"], 2)
        result["buckets"][label] = {**stats, "avg_pnl": avg_pnl}
        print(f"  {label}: {stats['wins']}/{stats['n']} win ({stats['win_rate']}%), "
              f"avg P&L {avg_pnl}%")

    return result


def main() -> dict:
    conn = get_connection()
    trades = fetch_closed_trades(conn)
    conn.close()

    print(f"AutoTrader Eval Harness — {len(trades)} closed trades loaded\n")
    print("NOTE: agent_log table is currently empty (crew.py never writes to it),")
    print("so this harness works off outcome data already stored on each trade")
    print("row. This means precision is measurable but recall (opportunities the")
    print("system silently HOLD'd on) is not — that would require logging")
    print("pre-filter HOLDs going forward.")

    results = {
        "n_trades": len(trades),
        "precision_by_direction": eval_precision_by_direction(trades),
        "confidence_calibration": eval_confidence_calibration(trades),
        "rsi_extremity": eval_rsi_extremity(trades),
        "lessons_influence": eval_lessons_influence(trades),
        "stop_target_hit_rate": eval_stop_target_hit_rate(trades),
        "close_reason_breakdown": eval_close_reason_breakdown(trades),
    }

    print("\n=== Done ===")
    return results


if __name__ == "__main__":
    main()
