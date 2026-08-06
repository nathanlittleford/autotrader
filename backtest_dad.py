# ============================================================
#  Dad's 12h BTC Trend Rider Strategy Backtest
#  Based on Eric Crown's strategy from the video
#  Tests on BTC-USD using 12-hour candles
# ============================================================

import sys
import math
from datetime import datetime, timezone
sys.path.append('.')

try:
    import yfinance as yf
except ImportError:
    print("pip install yfinance")
    raise

STARTING_CAPITAL = 10_000
RISK_PER_TRADE   = 0.01     # 1% account risk per trade
ATR_MULTIPLIER   = 3.0      # Chandelier exit
PARTIAL_EXIT_R   = 2.0      # Close 30% at 2R
TICKER           = "BTC-USD"
INTERVAL         = "1h"     # Yahoo Finance doesn't do 12h, using 1h and grouping


def ema(data, period):
    k      = 2 / (period + 1)
    result = [data[0]]
    for p in data[1:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def atr(closes, period=14):
    trs = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
    atrs = []
    for i in range(len(trs)):
        if i < period:
            atrs.append(sum(trs[:i+1]) / (i+1))
        else:
            atrs.append(sum(trs[i-period+1:i+1]) / period)
    return atrs


def rsi(closes, period=3):
    results = [50.0] * period
    for i in range(period, len(closes)):
        deltas = [closes[j] - closes[j-1] for j in range(i-period+1, i+1)]
        gains  = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        ag     = sum(gains) / period if gains else 0
        al     = sum(losses) / period if losses else 1e-10
        rs     = ag / al
        results.append(round(100 - (100 / (1 + rs)), 2))
    return results


def atr_percentile(atr_values, current_idx, lookback=100):
    start     = max(0, current_idx - lookback)
    window    = sorted(atr_values[start:current_idx+1])
    n         = len(window)
    if n < 10:
        return 50
    rank      = window.index(atr_values[current_idx])
    return round((rank / n) * 100, 1)


def run_backtest():
    print(f"\n{'='*55}")
    print(f"  DAD'S 12H BTC TREND RIDER — BACKTEST")
    print(f"  Ticker: {TICKER} | Interval: 1h (2 bars = 12h approx)")
    print(f"  Capital: ${STARTING_CAPITAL:,} | Risk: {RISK_PER_TRADE*100}% per trade")
    print(f"{'='*55}\n")

    # Pull 2 years of hourly data
    print("Fetching BTC hourly data (2 years)...")
    data  = yf.Ticker(TICKER)
    hist  = data.history(period="2y", interval="1h")

    if hist.empty:
        print("No data returned — trying daily instead")
        hist = data.history(period="2y", interval="1d")

    closes    = [float(c) for c in hist["Close"].tolist()]
    dates     = hist.index.tolist()
    print(f"Got {len(closes)} candles from {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}\n")

    if len(closes) < 60:
        print("Not enough data")
        return

    # Calculate indicators
    ema5_vals  = ema(closes, 5)
    ema21_vals = ema(closes, 21)
    ema55_vals = ema(closes, 55)
    atr_vals   = atr(closes, 14)
    rsi3_vals  = rsi(closes, 3)

    capital    = STARTING_CAPITAL
    position   = None
    trades     = []
    wins = losses = 0

    for i in range(60, len(closes)):
        price    = closes[i]
        date     = dates[i]
        is_friday = date.weekday() == 4

        # Skip Fridays
        if is_friday:
            continue

        # ── Check exit if in position ──
        if position:
            entry      = position["entry"]
            shares     = position["shares"]
            stop       = position["stop"]
            partial_done = position.get("partial_done", False)

            # Chandelier trailing stop
            highest    = max(closes[position["entry_idx"]:i+1])
            chan_stop  = highest - ATR_MULTIPLIER * atr_vals[i]

            # Update stop to higher of original or chandelier
            position["stop"] = max(stop, chan_stop)

            # Partial exit at 2R
            if not partial_done:
                r_size    = entry - position["original_stop"]
                target_2r = entry + PARTIAL_EXIT_R * r_size
                if price >= target_2r:
                    partial_shares = round(shares * 0.30, 6)
                    partial_pnl    = partial_shares * (price - entry)
                    capital       += partial_shares * price
                    position["shares"]       -= partial_shares
                    position["partial_done"]  = True
                    position["stop"]          = entry  # move to breakeven

            # Check stop
            if price <= position["stop"]:
                pnl    = position["shares"] * (price - entry)
                if position.get("partial_done"):
                    pnl += position.get("partial_pnl", 0)
                capital += position["shares"] * price
                result  = "WIN" if pnl > 0 else "LOSS"
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades.append({
                    "date":   date.strftime("%Y-%m-%d"),
                    "entry":  round(entry, 2),
                    "exit":   round(price, 2),
                    "pnl":    round(pnl, 2),
                    "result": result,
                })
                position = None
                continue

        # ── Check entry ──
        if position:
            continue

        # 1. EMA trend: EMA21 > EMA55 and EMA55 rising
        if not (ema21_vals[i] > ema55_vals[i]):
            continue
        ema55_rising = ema55_vals[i] > ema55_vals[i-5]
        if not ema55_rising:
            continue

        # 2. ATR percentile 20-80
        atr_pct = atr_percentile(atr_vals, i)
        if not (20 <= atr_pct <= 80):
            continue

        # 3. RSI(3) > 50 and higher than 5 bars ago
        if not (rsi3_vals[i] > 50 and rsi3_vals[i] > rsi3_vals[i-5]):
            continue

        # 4. Price crossed above EMA5
        crossed_above = closes[i] > ema5_vals[i] and closes[i-1] < ema5_vals[i-1]
        if not crossed_above:
            continue

        # All conditions met — calculate position size
        lowest_low  = min(closes[i-5:i])
        stop_price  = lowest_low - 0.25 * atr_vals[i]
        risk_per_share = price - stop_price

        if risk_per_share <= 0:
            continue

        risk_amount = capital * RISK_PER_TRADE
        shares      = risk_amount / risk_per_share
        cost        = shares * price

        if cost > capital:
            shares = capital / price
            cost   = capital

        capital  -= cost
        position  = {
            "entry":         price,
            "entry_idx":     i,
            "shares":        shares,
            "stop":          stop_price,
            "original_stop": stop_price,
            "partial_done":  False,
            "partial_pnl":   0,
        }

    # Close any open position at last price
    if position:
        pnl     = position["shares"] * (closes[-1] - position["entry"])
        capital += position["shares"] * closes[-1]

    # Results
    total_trades = wins + losses
    win_rate     = round(wins / total_trades * 100, 1) if total_trades > 0 else 0
    total_pnl    = round(capital - STARTING_CAPITAL, 2)
    pct_return   = round((capital / STARTING_CAPITAL - 1) * 100, 2)

    avg_win  = round(sum(t["pnl"] for t in trades if t["pnl"] > 0) / wins, 2) if wins else 0
    avg_loss = round(abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)) / losses, 2) if losses else 1
    pf       = round(avg_win / avg_loss * (wins / losses), 2) if losses else 0

    print(f"{'='*55}")
    print(f"  RESULTS")
    print(f"{'='*55}")
    print(f"  Total trades  : {total_trades}")
    print(f"  Wins          : {wins}")
    print(f"  Losses        : {losses}")
    print(f"  Win rate      : {win_rate}%")
    print(f"  Avg win       : ${avg_win}")
    print(f"  Avg loss      : ${avg_loss}")
    print(f"  Profit factor : {pf}")
    print(f"  Net P&L       : ${total_pnl:+,.2f}")
    print(f"  Return        : {pct_return:+.1f}%")
    print(f"  Final capital : ${capital:,.2f}")
    print(f"\n  Last 5 trades:")
    for t in trades[-5:]:
        icon = "✅" if t["result"] == "WIN" else "❌"
        print(f"  {icon} {t['date']} | entry ${t['entry']:,.0f} | exit ${t['exit']:,.0f} | P&L ${t['pnl']:+,.2f}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    run_backtest()
