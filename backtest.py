#!/usr/bin/env python3
# ============================================================
#  AutoTrader — backtest.py
#  Tests your signal rules against 6 months of real price data
#  Zero API calls — pure maths only
#  Run: python3 backtest.py
#  Run specific ticker: python3 backtest.py --ticker AAPL
#  Run all tickers: python3 backtest.py --all
# ============================================================

import os
import sys
import json
import argparse
from agents.learning import run_learning_agent
from datetime import datetime, timezone, timedelta
sys.path.append(os.path.dirname(__file__))

try:
    import yfinance as yf
except ImportError:
    print("⚠  yfinance not installed. Run: pip install yfinance")
    raise

from config.settings import WATCHLIST, OBSIDIAN_VAULT

# ============================================================
#  Signal rules — must match crew.py exactly
# ============================================================
RSI_OVERSOLD    = 40    # adjusted from backtest results
RSI_OVERBOUGHT  = 65    # adjusted from backtest results
STOP_LOSS_PCT   = 0.03  # -3%
LOOKBACK_DAYS   = 180   # 6 months of history


# ============================================================
#  Pure maths — no AI, no API
# ============================================================
def calculate_rsi(prices: list, period: int = 14) -> list:
    """Returns RSI value for each price point."""
    rsi_values = [None] * period
    for i in range(period, len(prices)):
        window  = prices[i-period:i]
        deltas  = [window[j] - window[j-1] for j in range(1, len(window))]
        gains   = [d for d in deltas if d > 0]
        losses  = [-d for d in deltas if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 1e-10
        rs  = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_values.append(round(rsi, 2))
    return rsi_values


def calculate_macd(prices: list) -> list:
    """Returns MACD crossover signal for each price point."""
    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for p in data[1:]:
            result.append(p * k + result[-1] * (1 - k))
        return result

    if len(prices) < 35:
        return [False] * len(prices)

    ema12     = ema(prices, 12)
    ema26     = ema(prices, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(ema26))]
    signal    = ema(macd_line, 9)

    crossovers = [False] * len(prices)
    for i in range(1, len(macd_line)):
        if macd_line[i-1] < signal[i-1] and macd_line[i] > signal[i]:
            crossovers[i] = True

    return crossovers


def get_historical_data(ticker: str, days: int = LOOKBACK_DAYS) -> dict:
    """Pull historical OHLCV data from Yahoo Finance."""
    data = yf.Ticker(ticker)
    hist = data.history(period=f"{days + 30}d")

    if hist.empty:
        raise ValueError(f"No data for {ticker}")

    closes  = [round(float(c), 6) for c in hist["Close"].tolist()]
    volumes = [int(v) for v in hist["Volume"].tolist()]
    dates   = [str(d)[:10] for d in hist.index.tolist()]

    return {
        "ticker":  ticker,
        "closes":  closes,
        "volumes": volumes,
        "dates":   dates,
    }



def calculate_trend_filter(closes: list, i: int) -> dict:
    """MA5/MA10/MA20 trend filter — matches broker.py logic."""
    if i < 20:
        return {"safe_to_buy": True, "safe_to_sell": True}
    window  = closes[max(0, i-20):i+1]
    ma20    = sum(window[-20:]) / 20
    ma10    = sum(window[-10:]) / 10
    ma5     = sum(window[-5:])  / 5
    current = closes[i]
    if ma5 < ma10 < ma20:
        direction = "downtrend"
    elif ma5 > ma10 > ma20:
        direction = "uptrend"
    else:
        direction = "sideways"
    pct_from_ma20 = ((current - ma20) / ma20) * 100
    if abs(pct_from_ma20) > 5:
        strength = "strong"
    elif abs(pct_from_ma20) > 2:
        strength = "moderate"
    else:
        strength = "weak"
    momentum_5d   = ((closes[i] - closes[max(0,i-5)]) / closes[max(0,i-5)]) * 100
    safe_to_buy   = not (direction == "downtrend" and strength in ("strong", "moderate"))
    safe_to_sell  = not (direction == "uptrend" and strength == "strong" and momentum_5d > 2)
    return {"safe_to_buy": safe_to_buy, "safe_to_sell": safe_to_sell}


def calculate_volume_filter(volumes: list, i: int, period: int = 20) -> dict:
    """Volume dead check — matches broker.py logic."""
    if i < period + 1:
        return {"is_dead": False}
    avg_volume   = sum(volumes[i-period-1:i-1]) / period
    today_volume = volumes[i]
    if avg_volume == 0:
        return {"is_dead": False}
    ratio    = today_volume / avg_volume
    is_dead  = ratio < 0.7
    return {"is_dead": is_dead, "ratio": round(ratio, 2)}


def calculate_ema_filter(closes: list, i: int) -> dict:
    """EMA21/55 alignment — matches broker.py logic."""
    if i < 55:
        return {"available": False}
    window = closes[:i+1]
    def ema(data, period):
        k      = 2 / (period + 1)
        result = [data[0]]
        for p in data[1:]:
            result.append(p * k + result[-1] * (1 - k))
        return result
    ema21   = ema(window, 21)[-1]
    ema55   = ema(window, 55)[-1]
    bullish = ema21 > ema55
    return {"available": True, "bullish": bullish}


# ============================================================
#  Backtester
# ============================================================
def backtest_ticker(ticker: str, starting_capital: float = 10_000, use_filters: bool = True) -> dict:
    """
    Simulates trading one ticker over 6 months.
    Returns full performance stats.
    use_filters=True  → applies trend + volume + EMA21/55 filters (matches live system)
    use_filters=False → RSI + MACD only (baseline)
    """
    try:
        data = get_historical_data(ticker)
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}

    closes  = data["closes"]
    volumes = data["volumes"]
    dates   = data["dates"]

    if len(closes) < 50:
        return {"ticker": ticker, "error": "Not enough historical data"}

    rsi_values  = calculate_rsi(closes)
    macd_cross  = calculate_macd(closes)

    trades      = []
    capital     = starting_capital
    position    = None   # current open position

    for i in range(14, len(closes)):
        price = closes[i]
        rsi   = rsi_values[i]
        cross = macd_cross[i]
        date  = dates[i]

        if rsi is None:
            continue

        # Check open position for stop/target
        if position:
            pnl_pct = ((price - position["entry"]) / position["entry"]) * 100
            if position["direction"] == "SELL":
                pnl_pct = -pnl_pct

            stop_hit   = pnl_pct <= -STOP_LOSS_PCT * 100

            # Chandelier Exit simulation
            lookback   = closes[max(0, i-14):i+1]
            true_ranges = [abs(lookback[j] - lookback[j-1]) for j in range(1, len(lookback))]
            atr        = sum(true_ranges) / len(true_ranges) if true_ranges else 0
            multiplier = 3.0 if "-USD" in ticker else 4.5
            if position["direction"] == "BUY":
                highest_high = max(lookback)
                chandelier_stop = highest_high - (multiplier * atr)
                target_hit = price < chandelier_stop
            else:
                lowest_low = min(lookback)
                chandelier_stop = lowest_low + (multiplier * atr)
                target_hit = price > chandelier_stop

            if stop_hit or target_hit:
                shares     = position["shares"]
                pnl        = (price - position["entry"]) * shares
                if position["direction"] == "SELL":
                    pnl = -pnl

                capital   += pnl
                result     = "WIN" if pnl > 0 else "LOSS"
                trades.append({
                    "ticker":      ticker,
                    "direction":   position["direction"],
                    "entry_date":  position["entry_date"],
                    "exit_date":   date,
                    "entry_price": position["entry"],
                    "exit_price":  price,
                    "shares":      shares,
                    "pnl":         round(pnl, 2),
                    "pnl_pct":     round(pnl_pct, 2),
                    "result":      result,
                    "stop_hit":    stop_hit,
                    "target_hit":  target_hit,
                    "rsi_at_entry": position["rsi"],
                    "capital_after": round(capital, 2),
                })
                position = None

        # Look for new entry if no open position
        if not position:
            # BUY signal: RSI oversold + MACD bullish crossover
            _buy_ok = rsi < RSI_OVERSOLD and cross
            if _buy_ok and use_filters:
                trend = calculate_trend_filter(closes, i)
                vol   = calculate_volume_filter(volumes, i)
                ema_t = calculate_ema_filter(closes, i)
                if not trend["safe_to_buy"]:
                    _buy_ok = False
                elif vol.get("is_dead"):
                    _buy_ok = False
                elif ema_t["available"] and not ema_t["bullish"]:
                    _buy_ok = False
            if _buy_ok:
                max_spend = capital * 0.10
                shares    = min(int(max_spend / price), 500)
                if shares >= 1:
                    position = {
                        "direction":  "BUY",
                        "entry":      price,
                        "entry_date": date,
                        "shares":     shares,
                        "rsi":        rsi,
                    }

            # SELL signal: RSI overbought
            _sell_ok = rsi > RSI_OVERBOUGHT and not _buy_ok
            if _sell_ok:
                price_5d_ago = closes[max(0, i-5)]
                change_5d    = ((price - price_5d_ago) / price_5d_ago) * 100
                if change_5d <= 3:
                    _sell_ok = False
            if _sell_ok and use_filters:
                trend = calculate_trend_filter(closes, i)
                vol   = calculate_volume_filter(volumes, i)
                ema_t = calculate_ema_filter(closes, i)
                if not trend["safe_to_sell"]:
                    _sell_ok = False
                elif vol.get("is_dead"):
                    _sell_ok = False
                elif ema_t["available"] and ema_t["bullish"]:
                    _sell_ok = False
            if _sell_ok:
                max_spend = capital * 0.10
                shares    = min(int(max_spend / price), 500)
                if shares >= 1:
                    position = {
                        "direction":  "SELL",
                        "entry":      price,
                        "entry_date": date,
                        "shares":     shares,
                        "rsi":        rsi,
                    }

    # Close any open position at end of period
    if position:
        price  = closes[-1]
        pnl    = (price - position["entry"]) * position["shares"]
        if position["direction"] == "SELL":
            pnl = -pnl
        capital += pnl

    # Calculate stats
    if not trades:
        return {
            "ticker":        ticker,
            "total_trades":  0,
            "win_rate":      0,
            "net_pnl":       0,
            "total_return":  0,
            "best_trade":    0,
            "worst_trade":   0,
            "trades":        [],
            "verdict":       "NO SIGNALS — RSI never crossed threshold in 6 months",
        }

    wins      = [t for t in trades if t["result"] == "WIN"]
    losses    = [t for t in trades if t["result"] == "LOSS"]
    net_pnl   = sum(t["pnl"] for t in trades)
    win_rate  = round(len(wins) / len(trades) * 100, 1)
    best      = max(trades, key=lambda t: t["pnl"])
    worst     = min(trades, key=lambda t: t["pnl"])
    total_ret = round(((capital - starting_capital) / starting_capital) * 100, 2)

    if win_rate >= 55 and net_pnl > 0:
        verdict = "✅ PROFITABLE — good signal quality on this ticker"
    elif win_rate >= 45 or net_pnl > 0:
        verdict = "⚠️  MIXED — borderline, monitor closely"
    else:
        verdict = "❌ UNPROFITABLE — consider removing from watchlist"

    return {
        "ticker":          ticker,
        "total_trades":    len(trades),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        win_rate,
        "net_pnl":         round(net_pnl, 2),
        "total_return":    total_ret,
        "best_trade":      round(best["pnl"], 2),
        "best_trade_date": best["entry_date"],
        "worst_trade":     round(worst["pnl"], 2),
        "worst_trade_date":worst["entry_date"],
        "final_capital":   round(capital, 2),
        "verdict":         verdict,
        "trades":          trades,
    }


# ============================================================
#  Obsidian report writer
# ============================================================
def write_backtest_to_obsidian(results: list):
    """Writes full backtest report to Obsidian."""
    folder   = os.path.join(OBSIDIAN_VAULT, "Backtests")
    os.makedirs(folder, exist_ok=True)

    now      = datetime.now(timezone.utc)
    filename = f"Backtest-{now.strftime('%Y-%m-%d')}.md"
    filepath = os.path.join(folder, filename)

    # Filter out errors
    valid   = [r for r in results if "error" not in r and r.get("total_trades", 0) > 0]
    errored = [r for r in results if "error" in r]
    no_sig  = [r for r in results if "error" not in r and r.get("total_trades", 0) == 0]

    profitable  = [r for r in valid if r["net_pnl"] > 0]
    losing      = [r for r in valid if r["net_pnl"] <= 0]

    total_pnl   = sum(r["net_pnl"] for r in valid)
    avg_win_rate= round(sum(r["win_rate"] for r in valid) / len(valid), 1) if valid else 0

    best_ticker  = max(valid, key=lambda r: r["net_pnl"], default=None)
    worst_ticker = min(valid, key=lambda r: r["net_pnl"], default=None)

    # Build results table
    rows = "\n".join([
        f"| {r['ticker']} | {r['total_trades']} | {r['win_rate']}% | "
        f"${r['net_pnl']:+.2f} | {r['total_return']:+.1f}% | {r['verdict'].split('—')[0].strip()} |"
        for r in sorted(valid, key=lambda x: x["net_pnl"], reverse=True)
    ])

    content = f"""---
date: {now.strftime("%Y-%m-%d")}
period: Last 6 months
tickers_tested: {len(results)}
tags: [backtest, trading]
---

# 📊 Backtest report — {now.strftime("%Y-%m-%d")}
*6 months of historical data | Pure RSI + MACD signals | No AI involved*

---

## Overall summary
| Metric | Value |
|---|---|
| Tickers tested | {len(results)} |
| Tickers with signals | {len(valid)} |
| Profitable tickers | {len(profitable)} |
| Losing tickers | {len(losing)} |
| Average win rate | {avg_win_rate}% |
| Combined P&L | ${total_pnl:+.2f} |
| Best ticker | {best_ticker['ticker'] if best_ticker else '—'} (${best_ticker['net_pnl']:+.2f}) |
| Worst ticker | {worst_ticker['ticker'] if worst_ticker else '—'} (${worst_ticker['net_pnl']:+.2f}) |

---

## Verdict
{'✅ Overall profitable — signal rules are working well across the watchlist.' if total_pnl > 0 and avg_win_rate >= 50 else '⚠️ Mixed results — consider tightening RSI thresholds or removing losing tickers.' if total_pnl > 0 else '❌ Overall unprofitable — signal rules need adjustment before going live.'}

---

## Results by ticker
| Ticker | Trades | Win rate | Net P&L | Return | Verdict |
|---|---|---|---|---|---|
{rows}

---

## Tickers with no signals ({len(no_sig)})
These tickers never crossed RSI thresholds in 6 months — consider replacing them:
{', '.join(r['ticker'] for r in no_sig) or 'None'}

## Errors ({len(errored)})
These tickers had data issues:
{', '.join(r['ticker'] + ': ' + r.get('error','?') for r in errored) or 'None'}

---

## What this means for your live system
- Tickers marked ✅ are your strongest signal generators — prioritise these
- Tickers marked ❌ consider moving to learn-only (Tier 2) or removing
- Win rate above 55% = ready to trade live on that ticker
- Win rate below 45% = needs more data or rule adjustment

---
[[DASHBOARD]] | [[Weekly Summaries]] | [[Learning/lessons]]
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n  ✓ Backtest report saved to Obsidian: Backtests/{filename}")
    return filepath


# ============================================================
#  Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Backtest signal rules on historical data")
    parser.add_argument("--ticker", type=str, help="Test a single ticker e.g. --ticker AAPL")
    parser.add_argument("--all",    action="store_true", help="Test entire watchlist")
    parser.add_argument("--tier",   type=int, help="Test specific tier only e.g. --tier 1")
    parser.add_argument("--seed-lessons", action="store_true", help="Generate lessons from backtest trades")
    parser.add_argument("--no-filters", action="store_true", help="Run without trend/volume/EMA filters (baseline)")
    args = parser.parse_args()

    use_filters = not args.no_filters

    print("\n" + "="*55)
    print("  AutoTrader Backtester")
    print(f"  Mode: {'WITH filters (trend + volume + EMA21/55)' if use_filters else 'BASELINE (RSI + MACD only)'}")
    print(f"  Stop-loss: -{STOP_LOSS_PCT*100:.0f}% | Exit: Chandelier Exit (dynamic)\n")
    print("="*55)

    if args.ticker:
        tickers = [args.ticker.upper()]
    elif args.tier:
        tickers = [w["ticker"] for w in WATCHLIST if w["tier"] == args.tier]
    else:
        tickers = [w["ticker"] for w in WATCHLIST]

    print(f"\n  Testing {len(tickers)} ticker(s)...")
    print(f"  Signal rules: BUY when RSI<{RSI_OVERSOLD} + MACD cross | SELL when RSI>{RSI_OVERBOUGHT}")
    print(f"  Filters: {'trend + volume + EMA21/55 active' if use_filters else 'none (baseline mode)'}")
    print(f"  Stop-loss: -{STOP_LOSS_PCT*100:.0f}% | Exit: Chandelier Exit (dynamic)\n")

    results = []
    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i}/{len(tickers)}] {ticker}...", end=" ", flush=True)
        result = backtest_ticker(ticker, use_filters=use_filters)
        results.append(result)

        if "error" in result:
            print(f"ERROR — {result['error']}")
        elif result["total_trades"] == 0:
            print(f"no signals in 6 months")
        else:
            print(f"{result['total_trades']} trades | {result['win_rate']}% win rate | ${result['net_pnl']:+.2f} P&L | {result['verdict'].split('—')[0].strip()}")

    # Summary
    valid = [r for r in results if "error" not in r and r.get("total_trades", 0) > 0]
    if valid:
        total_pnl = sum(r["net_pnl"] for r in valid)
        avg_wr    = round(sum(r["win_rate"] for r in valid) / len(valid), 1)
        profitable = len([r for r in valid if r["net_pnl"] > 0])

        print(f"\n{'='*55}")
        print(f"  BACKTEST COMPLETE")
        print(f"{'='*55}")
        print(f"  Tickers with signals : {len(valid)}/{len(tickers)}")
        print(f"  Profitable tickers   : {profitable}/{len(valid)}")
        print(f"  Average win rate     : {avg_wr}%")
        print(f"  Combined P&L         : ${total_pnl:+.2f}")
        print(f"  Verdict              : {'✅ Profitable' if total_pnl > 0 else '❌ Unprofitable'}")

        # Write to Obsidian
        write_backtest_to_obsidian(results)

        # Show top 5 and bottom 5
        sorted_valid = sorted(valid, key=lambda r: r["net_pnl"], reverse=True)
        print(f"\n  Top 5 tickers:")
        for r in sorted_valid[:5]:
            print(f"    {r['ticker']:12} {r['win_rate']}% win rate  ${r['net_pnl']:+.2f}")
        print(f"\n  Bottom 5 tickers:")
        for r in sorted_valid[-5:]:
            print(f"    {r['ticker']:12} {r['win_rate']}% win rate  ${r['net_pnl']:+.2f}")

        # Seed lessons from backtest trades
        if args.seed_lessons:
            all_trades = [t for r in results if "trades" in r for t in r["trades"]]
            print(f"\n  Seeding {len(all_trades)} lessons from backtest trades...")
            for i, trade in enumerate(all_trades, 1):
                print(f"  [{i}/{len(all_trades)}] {trade['ticker']} {trade['direction']} {trade['result']}...", end=" ", flush=True)
                try:
                    run_learning_agent(
                        trade={
                            "trade_id":        f"BACKTEST-{trade['ticker']}-{trade['entry_date']}",
                            "ticker":          trade["ticker"],
                            "direction":       trade["direction"],
                            "profit_loss":     trade["pnl"],
                            "profit_pct":      trade["pnl_pct"],
                            "stop_hit":        trade.get("stop_hit", False),
                            "target_hit":      trade.get("target_hit", False),
                            "signal_confidence": 70,
                            "agent_reasoning": "Backtest trade",
                            "source":          "backtest",
                        },
                        entry_data={"rsi": trade.get("rsi_at_entry"), "macd_crossover": False}
                    )
                    print("✅")
                except Exception as e:
                    print(f"❌ {e}")
            print(f"  Lesson seeding complete!")

    else:
        print("\n  No valid results — check your watchlist tickers.")


if __name__ == "__main__":
    main()
