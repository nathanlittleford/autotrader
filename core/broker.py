# ============================================================
#  AutoTrader — core/broker.py
#  Yahoo Finance + local paper trading simulation
#  Supports: fractional shares, short selling, full crypto
# ============================================================

import json
import os
import sys
from datetime import datetime, timezone
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import (
    STARTING_CAPITAL, MAX_LOSS_PCT, TARGET_GAIN_PCT,
    PORTFOLIO_PATH, POSITION_TIERS, CASH_RESERVE_PCT, HIGH_CONVICTION
)

try:
    import yfinance as yf
except ImportError:
    print("⚠  yfinance not installed. Run: pip install yfinance")
    raise


def _load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_PATH):
        with open(PORTFOLIO_PATH, "r") as f:
            return json.load(f)
    default = {
        "cash":      STARTING_CAPITAL,
        "equity":    STARTING_CAPITAL,
        "positions": {},
        "shorts":    {},   # tracks short positions separately
        "orders":    [],
    }
    _save_portfolio(default)
    return default


def _save_portfolio(portfolio: dict):
    with open(PORTFOLIO_PATH, "w") as f:
        json.dump(portfolio, f, indent=2)


class Broker:
    def __init__(self):
        self.portfolio = _load_portfolio()
        # Ensure shorts key exists for older portfolio files
        if "shorts" not in self.portfolio:
            self.portfolio["shorts"] = {}
            _save_portfolio(self.portfolio)
        print(f"  Portfolio loaded — Cash: R{self.portfolio['cash']:,.2f}")

    # ----------------------------------------------------------
    #  Account
    # ----------------------------------------------------------
    def get_account(self) -> dict:
        self._refresh_equity()
        return {
            "cash":            round(self.portfolio["cash"], 2),
            "portfolio_value": round(self.portfolio["equity"], 2),
            "buying_power":    round(self.portfolio["cash"], 2),
            "equity":          round(self.portfolio["equity"], 2),
        }

    def get_portfolio_value(self) -> float:
        self._refresh_equity()
        return round(self.portfolio["equity"], 2)

    def _refresh_equity(self):
        total = self.portfolio["cash"]
        for ticker, pos in self.portfolio["positions"].items():
            try:
                price = self.get_latest_price(ticker)
                total += price * pos["shares"]
            except Exception:
                total += pos["avg_entry"] * pos["shares"]
        # Subtract unrealised loss on shorts
        for ticker, pos in self.portfolio.get("shorts", {}).items():
            try:
                price = self.get_latest_price(ticker)
                total -= (price - pos["avg_entry"]) * pos["shares"]
            except Exception:
                pass
        self.portfolio["equity"] = round(total, 2)
        _save_portfolio(self.portfolio)

    # ----------------------------------------------------------
    #  Market data
    # ----------------------------------------------------------
    def get_latest_price(self, ticker: str) -> float:
        data  = yf.Ticker(ticker)
        info  = data.fast_info
        price = getattr(info, 'last_price', None)
        if not price or price == 0:
            hist = data.history(period="5d")
            if hist.empty:
                raise ValueError(f"No price data for {ticker}")
            price = float(hist["Close"].iloc[-1])
        return round(float(price), 8)

    def get_price_history(self, ticker: str, days: int = 40) -> list:
        data = yf.Ticker(ticker)
        hist = data.history(period="60d")
        if hist.empty:
            raise ValueError(f"No price history for {ticker}")
        closes = [round(float(c), 8) for c in hist["Close"].tolist()]
        return closes[-days:] if len(closes) >= days else closes

    def is_market_open(self) -> bool:
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        market_open  = now.replace(hour=14, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=21, minute=0,  second=0, microsecond=0)
        return market_open <= now <= market_close

    def has_position(self, ticker: str) -> bool:
        """Check if we have a long position in ticker."""
        return ticker in self.portfolio["positions"]

    def has_short(self, ticker: str) -> bool:
        """Check if we have a short position in ticker."""
        return ticker in self.portfolio.get("shorts", {})

    # ----------------------------------------------------------
    #  Position sizing — supports fractional shares for crypto
    # ----------------------------------------------------------
    def calculate_position(self, ticker: str, price: float, confidence: int = 80) -> dict:
        if price <= 0:
            return {"approved": False, "reason": "Invalid price"}

        portfolio_value = self.get_portfolio_value()
        cash            = self.portfolio["cash"]
        reserve         = portfolio_value * CASH_RESERVE_PCT

        # Cash reserve check — block trades if below reserve unless high conviction
        if cash < reserve and confidence < HIGH_CONVICTION:
            return {
                "approved": False,
                "reason": f"Cash reserve protection — only {confidence}% confidence (need {HIGH_CONVICTION}%+ to use reserve). Cash: ${cash:.2f}, Reserve: ${reserve:.2f}"
            }

        # Tiered position size based on confidence
        position_pct = POSITION_TIERS[60]   # default to lowest tier
        for threshold in sorted(POSITION_TIERS.keys(), reverse=True):
            if confidence >= threshold:
                position_pct = POSITION_TIERS[threshold]
                break

        max_spend = portfolio_value * position_pct

        # Cap spend to available cash minus reserve (unless high conviction)
        if confidence < HIGH_CONVICTION:
            available_cash = max(0, cash - reserve)
        else:
            available_cash = cash   # high conviction can use reserve

        max_spend = min(max_spend, available_cash)

        if max_spend <= 0:
            return {"approved": False, "reason": f"No available cash outside reserve (confidence: {confidence}%)"}

        # Fractional shares for crypto and high-price assets
        # Crypto always fractional; stocks above $200 also get fractional
        is_crypto    = "-USD" in ticker
        is_expensive = price > 200

        if is_crypto or is_expensive:
            shares = round(max_spend / price, 6)
        else:
            shares = int(max_spend / price)

        if shares <= 0 or (not is_crypto and not is_expensive and shares < 1):
            return {
                "approved": False,
                "reason": f"Price too high for {position_pct*100:.0f}% allocation (${max_spend:.2f} at ${price:.2f})"
            }

        actual_spend    = round(shares * price, 2)
        stop_loss_price = round(price * (1 - MAX_LOSS_PCT), 8)
        target_price    = round(price * (1 + TARGET_GAIN_PCT), 8)

        return {
            "approved":          True,
            "shares":            shares,
            "spend":             actual_spend,
            "stop_loss_price":   stop_loss_price,
            "target_price":      target_price,
            "pct_of_portfolio":  round((actual_spend / portfolio_value) * 100, 2),
            "fractional":        is_crypto or is_expensive,
            "confidence_tier":   f"{position_pct*100:.0f}% allocation at {confidence}% confidence",
            "reserve_used":      confidence >= HIGH_CONVICTION and cash < reserve,
        }

    # ----------------------------------------------------------
    #  LONG positions (BUY then sell to close)
    # ----------------------------------------------------------
    def place_market_buy(self, ticker: str, shares: float) -> dict:
        price = self.get_latest_price(ticker)
        cost  = round(price * shares, 2)

        if self.portfolio["cash"] < cost:
            raise ValueError(f"Not enough cash. Need ${cost:.2f}, have ${self.portfolio['cash']:.2f}")

        self.portfolio["cash"] = round(self.portfolio["cash"] - cost, 2)

        if ticker in self.portfolio["positions"]:
            pos          = self.portfolio["positions"][ticker]
            total_shares = pos["shares"] + shares
            avg_entry    = round(((pos["avg_entry"] * pos["shares"]) + cost) / total_shares, 8)
            self.portfolio["positions"][ticker] = {"shares": total_shares, "avg_entry": avg_entry}
        else:
            self.portfolio["positions"][ticker] = {"shares": shares, "avg_entry": price}

        order_id = f"SIM-BUY-{ticker}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        self.portfolio["orders"].append({
            "order_id": order_id, "ticker": ticker, "side": "BUY",
            "shares": shares, "price": price, "total": cost,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_portfolio(self.portfolio)
        print(f"  [Broker] BUY {shares} {ticker} @ ${price:.4f} = ${cost:.2f}")
        return {"alpaca_order_id": order_id, "status": "filled", "ticker": ticker, "shares": shares}

    def place_market_sell(self, ticker: str, shares: float) -> dict:
        """Close a long position."""
        if ticker not in self.portfolio["positions"]:
            raise ValueError(f"No long position in {ticker} to sell.")

        pos      = self.portfolio["positions"][ticker]
        shares   = min(shares, pos["shares"])
        price    = self.get_latest_price(ticker)
        proceeds = round(price * shares, 2)

        remaining = round(pos["shares"] - shares, 8)
        if remaining <= 0.000001:
            del self.portfolio["positions"][ticker]
        else:
            self.portfolio["positions"][ticker]["shares"] = remaining

        self.portfolio["cash"] = round(self.portfolio["cash"] + proceeds, 2)

        order_id = f"SIM-SELL-{ticker}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        self.portfolio["orders"].append({
            "order_id": order_id, "ticker": ticker, "side": "SELL",
            "shares": shares, "price": price, "total": proceeds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_portfolio(self.portfolio)
        print(f"  [Broker] SELL {shares} {ticker} @ ${price:.4f} = ${proceeds:.2f}")
        return {"alpaca_order_id": order_id, "status": "filled", "ticker": ticker, "shares": shares}

    # ----------------------------------------------------------
    #  SHORT positions (SELL first, buy back to close)
    # ----------------------------------------------------------
    def place_short_sell(self, ticker: str, shares: float) -> dict:
        """Open a short position — bet price will fall."""
        price    = self.get_latest_price(ticker)
        proceeds = round(price * shares, 2)

        # Reserve margin (we hold proceeds as collateral)
        if self.portfolio["cash"] < proceeds * 0.5:
            raise ValueError(f"Not enough cash for short margin. Need ${proceeds*0.5:.2f}")

        # Track the short
        if ticker in self.portfolio.get("shorts", {}):
            pos          = self.portfolio["shorts"][ticker]
            total_shares = pos["shares"] + shares
            avg_entry    = round(((pos["avg_entry"] * pos["shares"]) + (price * shares)) / total_shares, 8)
            self.portfolio["shorts"][ticker] = {"shares": total_shares, "avg_entry": avg_entry}
        else:
            self.portfolio["shorts"][ticker] = {"shares": shares, "avg_entry": price}

        # Add proceeds to cash (we receive money when shorting)
        self.portfolio["cash"] = round(self.portfolio["cash"] + proceeds, 2)

        order_id = f"SIM-SHORT-{ticker}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        self.portfolio["orders"].append({
            "order_id": order_id, "ticker": ticker, "side": "SHORT",
            "shares": shares, "price": price, "total": proceeds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_portfolio(self.portfolio)
        print(f"  [Broker] SHORT {shares} {ticker} @ ${price:.4f} = ${proceeds:.2f} received")
        return {"alpaca_order_id": order_id, "status": "filled", "ticker": ticker, "shares": shares}

    def cover_short(self, ticker: str) -> dict:
        """Close a short position by buying back."""
        if ticker not in self.portfolio.get("shorts", {}):
            raise ValueError(f"No short position in {ticker} to cover.")

        pos      = self.portfolio["shorts"][ticker]
        price    = self.get_latest_price(ticker)
        cost     = round(price * pos["shares"], 2)

        # P&L = what we sold for - what we buy back for
        sold_for = round(pos["avg_entry"] * pos["shares"], 2)
        pnl      = sold_for - cost

        self.portfolio["cash"] = round(self.portfolio["cash"] - cost, 2)
        del self.portfolio["shorts"][ticker]

        order_id = f"SIM-COVER-{ticker}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        self.portfolio["orders"].append({
            "order_id": order_id, "ticker": ticker, "side": "COVER",
            "shares": pos["shares"], "price": price, "total": cost,
            "pnl": pnl,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _save_portfolio(self.portfolio)
        print(f"  [Broker] COVER SHORT {pos['shares']} {ticker} @ ${price:.4f} — P&L: ${pnl:+.2f}")
        return {"alpaca_order_id": order_id, "status": "filled", "ticker": ticker, "pnl": pnl}

    # ----------------------------------------------------------
    #  Position management
    # ----------------------------------------------------------
    def get_open_positions(self) -> list:
        positions = []

        # Long positions
        for ticker, pos in self.portfolio["positions"].items():
            try:
                current_price   = self.get_latest_price(ticker)
                unrealized_pnl  = round((current_price - pos["avg_entry"]) * pos["shares"], 2)
                pnl_pct         = round(((current_price - pos["avg_entry"]) / pos["avg_entry"]) * 100, 2)
            except Exception:
                current_price, unrealized_pnl, pnl_pct = pos["avg_entry"], 0, 0
            positions.append({
                "ticker":         ticker,
                "direction":      "LONG",
                "shares":         pos["shares"],
                "entry_price":    pos["avg_entry"],
                "current_price":  current_price,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct":        pnl_pct,
            })

        # Short positions
        for ticker, pos in self.portfolio.get("shorts", {}).items():
            try:
                current_price   = self.get_latest_price(ticker)
                unrealized_pnl  = round((pos["avg_entry"] - current_price) * pos["shares"], 2)
                pnl_pct         = round(((pos["avg_entry"] - current_price) / pos["avg_entry"]) * 100, 2)
            except Exception:
                current_price, unrealized_pnl, pnl_pct = pos["avg_entry"], 0, 0
            positions.append({
                "ticker":         ticker,
                "direction":      "SHORT",
                "shares":         pos["shares"],
                "entry_price":    pos["avg_entry"],
                "current_price":  current_price,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct":        pnl_pct,
            })

        return positions

    def close_position(self, ticker: str) -> dict:
        if ticker in self.portfolio["positions"]:
            shares = self.portfolio["positions"][ticker]["shares"]
            return self.place_market_sell(ticker, shares)
        elif ticker in self.portfolio.get("shorts", {}):
            return self.cover_short(ticker)
        else:
            raise ValueError(f"No position in {ticker}")

    # ----------------------------------------------------------
    #  Technical indicators
    # ----------------------------------------------------------
    def calculate_rsi(self, prices: list, period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas   = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains    = [d for d in deltas[-period:] if d > 0]
        losses   = [-d for d in deltas[-period:] if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 1e-10
        rs       = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)


    def get_volume_history(self, ticker: str, days: int = 40) -> list:
        data = yf.Ticker(ticker)
        hist = data.history(period="60d")
        if hist.empty:
            raise ValueError(f"No volume history for {ticker}")
        volumes = [int(v) for v in hist["Volume"].tolist()]
        return volumes[-days:] if len(volumes) >= days else volumes

    def calculate_volume_spike(self, volumes: list, period: int = 20) -> dict:
        if len(volumes) < period + 1:
            return {"ratio": 1.0, "is_spike": False, "is_dead": False,
                    "reason": "Insufficient volume history — passing"}
        avg_volume   = sum(volumes[-period-1:-1]) / period   # 20-day avg excluding today
        today_volume = volumes[-1]
        if avg_volume == 0:
            return {"ratio": 1.0, "is_spike": False, "is_dead": False,
                    "reason": "Zero average volume — passing"}
        ratio    = round(today_volume / avg_volume, 2)
        is_spike = ratio >= 1.5
        is_dead  = ratio < 0.7
        if is_spike:
            reason = f"Volume spike: {ratio}x avg ({today_volume:,} vs avg {int(avg_volume):,})"
        elif is_dead:
            reason = f"Volume dead: {ratio}x avg ({today_volume:,} vs avg {int(avg_volume):,})"
        else:
            reason = f"Volume normal: {ratio}x avg ({today_volume:,} vs avg {int(avg_volume):,})"
        return {"ratio": ratio, "is_spike": is_spike, "is_dead": is_dead, "reason": reason}

    def calculate_atr(self, prices: list, period: int = 14) -> dict:
        """
        Average True Range — measures market volatility.
        Returns ATR value and whether volatility is in a tradeable range.
        Normal range: 20th-80th percentile of recent ATR values.
        Too quiet = no momentum. Too wild = unpredictable.
        """
        if len(prices) < period + 1:
            return {"atr": 0, "tradeable": True, "reason": "insufficient data"}

        # Calculate true ranges (simplified — using close-to-close since we only have closes)
        true_ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]

        # Current ATR (last period)
        current_atr = sum(true_ranges[-period:]) / period

        # ATR percentile over last 100 candles
        if len(true_ranges) >= 50:
            sorted_trs  = sorted(true_ranges[-100:])
            n           = len(sorted_trs)
            p20         = sorted_trs[int(n * 0.20)]
            p80         = sorted_trs[int(n * 0.80)]

            if current_atr < p20:
                tradeable = False
                reason    = f"Volatility too low (ATR {current_atr:.4f} below 20th percentile {p20:.4f}) — no momentum"
            elif current_atr > p80:
                tradeable = False
                reason    = f"Volatility too high (ATR {current_atr:.4f} above 80th percentile {p80:.4f}) — too unpredictable"
            else:
                tradeable = True
                reason    = f"Volatility normal (ATR {current_atr:.4f} in 20th-80th percentile range)"
        else:
            tradeable = True
            reason    = "Insufficient history for percentile check — passing"
            p20, p80  = 0, 0

        return {
            "atr":       round(current_atr, 6),
            "tradeable": tradeable,
            "reason":    reason,
            "p20":       round(p20, 6) if p20 else 0,
            "p80":       round(p80, 6) if p80 else 0,
        }

    def calculate_chandelier_exit(self, prices: list, position_pnl_pct: float,
                                   direction: str, entry_price: float,
                                   period: int = 14, multiplier: float = 3.0) -> dict:
        """
        Chandelier Exit — trailing stop that follows price up (for longs) or down (for shorts).
        Stop = highest high over period - ATR * multiplier (for longs)
        Stop = lowest low over period + ATR * multiplier (for shorts)
        Much smarter than fixed % stop — lets winners run while protecting profits.
        """
        if len(prices) < period:
            return {"should_close": False, "stop_price": 0, "reason": "insufficient data"}

        true_ranges  = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        atr          = sum(true_ranges[-period:]) / period
        current      = prices[-1]

        if direction == "LONG":
            highest_high = max(prices[-period:])
            stop_price   = highest_high - (multiplier * atr)
            should_close = current < stop_price
            reason       = f"Chandelier stop at ${stop_price:.4f} (highest ${highest_high:.4f} - {multiplier}×ATR)"
        else:  # SHORT
            lowest_low   = min(prices[-period:])
            stop_price   = lowest_low + (multiplier * atr)
            should_close = current > stop_price
            reason       = f"Chandelier stop at ${stop_price:.4f} (lowest ${lowest_low:.4f} + {multiplier}×ATR)"

        return {
            "should_close": should_close,
            "stop_price":   round(stop_price, 6),
            "atr":          round(atr, 6),
            "reason":       reason,
        }

    def calculate_sma200(self, ticker: str) -> dict:
        """
        Calculates 200-period SMA and determines:
        1. Where price is relative to SMA200 (above/below and by how much)
        2. Whether the move was FAST (mean reversion likely) or SLOW (trend continuation likely)
        3. Trading bias based on SMA200 context
        """
        try:
            # Need 200+ days of data
            data = yf.Ticker(ticker)
            hist = data.history(period="300d")
            if hist.empty or len(hist) < 200:
                return {"available": False}

            closes = [round(float(c), 6) for c in hist["Close"].tolist()]
            sma200 = sum(closes[-200:]) / 200
            current = closes[-1]

            # How far is price from SMA200
            pct_from_sma = ((current - sma200) / sma200) * 100

            # Speed of move — compare 5-day move vs 20-day move
            # Fast move: price moved a lot in last 5 days relative to last 20
            move_5d  = ((closes[-1] - closes[-5])  / closes[-5])  * 100 if len(closes) >= 5  else 0
            move_20d = ((closes[-1] - closes[-20]) / closes[-20]) * 100 if len(closes) >= 20 else 0

            # If 5-day move is >60% of the total 20-day move, it was fast
            is_fast_move = abs(move_5d) > abs(move_20d) * 0.6 if move_20d != 0 else False

            # Determine bias
            # Price well above SMA200 — overbought
            if pct_from_sma > 8:
                if is_fast_move:
                    bias = "strong_sell"  # sharp pump, likely to mean revert
                    reason = f"Price {pct_from_sma:.1f}% above SMA200 — fast move, mean reversion likely"
                else:
                    bias = "weak_sell"  # slow grind up, SMA may catch up
                    reason = f"Price {pct_from_sma:.1f}% above SMA200 — slow move, trend may continue"

            elif pct_from_sma > 3:
                bias = "mild_sell"
                reason = f"Price {pct_from_sma:.1f}% above SMA200 — mild overbought"

            # Price well below SMA200 — oversold
            elif pct_from_sma < -8:
                if is_fast_move:
                    bias = "strong_buy"  # sharp dump, likely to mean revert
                    reason = f"Price {pct_from_sma:.1f}% below SMA200 — fast drop, bounce likely"
                else:
                    bias = "weak_buy"  # slow grind down, SMA may catch up
                    reason = f"Price {pct_from_sma:.1f}% below SMA200 — slow decline, trend may continue"

            elif pct_from_sma < -3:
                bias = "mild_buy"
                reason = f"Price {pct_from_sma:.1f}% below SMA200 — mild oversold"

            # Price near SMA200 — neutral zone
            else:
                bias = "neutral"
                reason = f"Price {pct_from_sma:.1f}% from SMA200 — neutral zone"

            # Crossing detection — price just crossed SMA200
            prev_above = closes[-2] > sma200
            curr_above = current > sma200
            crossed_above = not prev_above and curr_above
            crossed_below = prev_above and not curr_above

            if crossed_above:
                bias   = "bullish_cross"
                reason = "Price just crossed ABOVE SMA200 — strong bullish signal"
            elif crossed_below:
                bias   = "bearish_cross"
                reason = "Price just crossed BELOW SMA200 — strong bearish signal"

            return {
                "available":      True,
                "sma200":         round(sma200, 4),
                "current_price":  round(current, 4),
                "pct_from_sma":   round(pct_from_sma, 2),
                "bias":           bias,
                "reason":         reason,
                "is_fast_move":   is_fast_move,
                "move_5d":        round(move_5d, 2),
                "move_20d":       round(move_20d, 2),
                "price_above":    current > sma200,
                "crossed_above":  crossed_above,
                "crossed_below":  crossed_below,
            }

        except Exception as e:
            return {"available": False, "error": str(e)}

    def calculate_trend(self, prices: list) -> dict:
        """
        Calculates trend context — tells the system WHY RSI is low or high.
        Returns trend direction, strength, and whether it's safe to trade.
        """
        if len(prices) < 20:
            return {"direction": "unknown", "strength": "weak", "safe_to_buy": True, "safe_to_sell": True}

        # 20-day moving average
        ma20 = sum(prices[-20:]) / 20

        # 10-day moving average
        ma10 = sum(prices[-10:]) / 10

        # 5-day moving average
        ma5  = sum(prices[-5:]) / 5

        current = prices[-1]

        # Trend direction
        if ma5 > ma10 > ma20:
            direction = "uptrend"
        elif ma5 < ma10 < ma20:
            direction = "downtrend"
        else:
            direction = "sideways"

        # How far price is from 20-day MA (strength)
        pct_from_ma20 = ((current - ma20) / ma20) * 100

        if abs(pct_from_ma20) > 5:
            strength = "strong"
        elif abs(pct_from_ma20) > 2:
            strength = "moderate"
        else:
            strength = "weak"

        # Price momentum over last 5 days
        momentum_5d = ((prices[-1] - prices[-5]) / prices[-5]) * 100

        # Safety rules:
        # BUY — block in ANY downtrend (strong OR moderate) to prevent buying falling knives
        # SELL — only block in strong uptrends (allow shorting moderate uptrends)
        safe_to_buy  = not (direction == "downtrend" and strength in ("strong", "moderate"))
        safe_to_sell = not (direction == "uptrend"   and strength == "strong" and momentum_5d > 2)

        if not safe_to_buy:
            if strength == "strong":
                reason_buy = "Strong downtrend — RSI low because price is dumping, not bouncing"
            else:
                reason_buy = "Moderate downtrend — avoiding BUY until trend stabilises"
        else:
            reason_buy = "Trend supports BUY"

        reason_sell = "Strong uptrend — RSI high because price is rising, not reversing" if not safe_to_sell else "Trend supports SELL"

        return {
            "direction":    direction,
            "strength":     strength,
            "ma5":          round(ma5, 4),
            "ma10":         round(ma10, 4),
            "ma20":         round(ma20, 4),
            "pct_from_ma20": round(pct_from_ma20, 2),
            "momentum_5d":  round(momentum_5d, 2),
            "safe_to_buy":  safe_to_buy,
            "safe_to_sell": safe_to_sell,
            "reason_buy":   reason_buy,
            "reason_sell":  reason_sell,
        }


    def calculate_ema_trend(self, prices: list) -> dict:
        """
        EMA21 vs EMA55 trend confirmation (from dad's strategy).
        BUY bias: EMA21 > EMA55 (short-term above medium-term)
        SELL bias: EMA21 < EMA55 (short-term below medium-term)
        """
        if len(prices) < 55:
            return {"available": False, "reason": "Insufficient data for EMA55"}

        def ema(data, period):
            k      = 2 / (period + 1)
            result = [data[0]]
            for p in data[1:]:
                result.append(p * k + result[-1] * (1 - k))
            return result

        ema21 = ema(prices, 21)[-1]
        ema55 = ema(prices, 55)[-1]
        pct_gap = round(((ema21 - ema55) / ema55) * 100, 2)

        bullish = ema21 > ema55
        reason  = (
            f"EMA21 ${ema21:.2f} > EMA55 ${ema55:.2f} ({pct_gap:+.2f}%) — bullish alignment"
            if bullish else
            f"EMA21 ${ema21:.2f} < EMA55 ${ema55:.2f} ({pct_gap:+.2f}%) — bearish alignment"
        )

        return {
            "available": True,
            "ema21":     round(ema21, 4),
            "ema55":     round(ema55, 4),
            "pct_gap":   pct_gap,
            "bullish":   bullish,
            "reason":    reason,
        }

    def calculate_macd(self, prices: list) -> dict:
        def ema(data, period):
            k      = 2 / (period + 1)
            result = [data[0]]
            for p in data[1:]:
                result.append(p * k + result[-1] * (1 - k))
            return result

        if len(prices) < 26:
            return {"macd": 0, "signal": 0, "histogram": 0, "crossover": False}

        ema12     = ema(prices, 12)
        ema26     = ema(prices, 26)
        macd_line = [ema12[i] - ema26[i] for i in range(len(ema26))]
        signal    = ema(macd_line, 9)
        histogram = macd_line[-1] - signal[-1]
        crossover = (macd_line[-2] < signal[-2]) and (macd_line[-1] > signal[-1])

        return {
            "macd":      round(macd_line[-1], 6),
            "signal":    round(signal[-1], 6),
            "histogram": round(histogram, 6),
            "crossover": crossover,
        }
