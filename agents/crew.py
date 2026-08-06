# ============================================================
#  AutoTrader — agents/crew.py
#  Groq API with RSI pre-filter to save tokens
#  Pre-filter: only tickers with RSI <35 or >70 get full pipeline
#  Everything else = instant HOLD (no API call)
# ============================================================

import json
import os
import re
import sys
from datetime import datetime, timezone
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import GROQ_API_KEY

try:
    from groq import Groq
except ImportError:
    print("⚠  groq not installed. Run: pip install groq")
    raise

from agents.learning import get_relevant_lessons, format_lessons_for_prompt
from agents.news import run_news_agent

client     = Groq(api_key=GROQ_API_KEY)
MODEL_FAST  = "llama-3.1-8b-instant"    # research, signal, risk (cheap)
MODEL_SMART = "llama-3.3-70b-versatile" # auditor only (smart)

# RSI thresholds for pre-filter
RSI_OVERSOLD   = 40 
RSI_OVERBOUGHT = 65   


# --- Fallback state ---
_using_ollama   = False   # tracks which backend is active
_ollama_url     = "http://localhost:11434/api/chat"
_ollama_model   = "llama3.1:8b"


def _call_ollama(system: str, user: str) -> str:
    """Call local Ollama — no token limits."""
    import urllib.request
    payload = json.dumps({
        "model":    _ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream":  False,
        "options": {"temperature": 0.1, "num_predict": 600},
    }).encode("utf-8")
    req = urllib.request.Request(
        _ollama_url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"].strip()


def _call_groq(system: str, user: str, model: str = MODEL_FAST) -> str:
    """
    Smart fallback — tries Groq first, falls back to Ollama on rate limit.
    Automatically switches back to Groq when tokens reset.
    """
    global _using_ollama

    # If already on Ollama, try Groq first to see if tokens reset
    if _using_ollama:
        try:
            response = client.chat.completions.create(
                model=MODEL_FAST,
                messages=[
                    {"role": "system", "content": "ping"},
                    {"role": "user",   "content": "ok"},
                ],
                max_tokens=5,
            )
            # Groq worked — switch back
            _using_ollama = False
            print("  🔄 Groq tokens restored — switching back from Ollama")
        except Exception:
            pass   # still rate limited, stay on Ollama

    if _using_ollama:
        return _call_ollama(system, user)

    # Try Groq
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.1,
            max_tokens=600,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            # Rate limited — switch to Ollama
            _using_ollama = True
            print("  ⚠️  Groq rate limit hit — switching to local Ollama")
            try:
                return _call_ollama(system, user)
            except Exception as ollama_err:
                print(f"  ⚠️  Ollama also failed: {ollama_err}")
                print("  💡 Start Ollama: open a new Terminal and run 'ollama serve'")
                raise
        raise


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON: {text[:200]}")


# ----------------------------------------------------------
#  PRE-FILTER — pure maths, zero API calls
#  Returns True if ticker is worth a full agent analysis
# ----------------------------------------------------------
def pre_filter(ticker: str, broker) -> tuple:
    """
    Fast RSI + trend + volume + EMA21/55 check — no API call, pure maths.
    Returns (should_analyse, rsi, macd, trend, reason)
    """
    try:
        prices   = broker.get_price_history(ticker, 60)
        rsi      = broker.calculate_rsi(prices)
        macd     = broker.calculate_macd(prices)
        trend    = broker.calculate_trend(prices)
        volumes  = broker.get_volume_history(ticker, 40)
        vol      = broker.calculate_volume_spike(volumes)
        ema_trend = broker.calculate_ema_trend(prices)

        if rsi < RSI_OVERSOLD:
            if not trend["safe_to_buy"]:
                return False, rsi, macd, trend, f"RSI oversold at {rsi} BUT {trend['reason_buy']} — skipping"
            if vol["is_dead"]:
                return False, rsi, macd, trend, f"RSI oversold at {rsi} BUT {vol['reason']} — skipping"
            if ema_trend["available"] and not ema_trend["bullish"]:
                return False, rsi, macd, trend, f"RSI oversold at {rsi} BUT {ema_trend['reason']} — skipping"
            return True, rsi, macd, trend, f"RSI oversold at {rsi} | {vol['reason']} | {ema_trend.get('reason','EMA N/A')} — trend: {trend['direction']}"
        elif rsi > RSI_OVERBOUGHT:
            if not trend["safe_to_sell"]:
                return False, rsi, macd, trend, f"RSI overbought at {rsi} BUT {trend['reason_sell']} — skipping"
            if vol["is_dead"]:
                return False, rsi, macd, trend, f"RSI overbought at {rsi} BUT {vol['reason']} — skipping"
            if ema_trend["available"] and ema_trend["bullish"]:
                return False, rsi, macd, trend, f"RSI overbought at {rsi} BUT {ema_trend['reason']} — skipping"
            return True, rsi, macd, trend, f"RSI overbought at {rsi} | {vol['reason']} | {ema_trend.get('reason','EMA N/A')} — trend: {trend['direction']}"
        else:
            return False, rsi, macd, trend, f"RSI neutral at {rsi} — skipping"
    except Exception as e:
        return False, 50, {}, {}, f"Pre-filter error: {e}"


# ----------------------------------------------------------
#  Agent 1 — Research agent
# ----------------------------------------------------------
def research_agent(ticker: str, broker, rsi: float, macd: dict, trend: dict = None) -> dict:
    print(f"  [Research] Deep analysis on {ticker}...")

    price           = broker.get_latest_price(ticker)
    prices          = broker.get_price_history(ticker, 40)
    prices_clean = [p for p in prices if p is not None]
    price_change_5d = round(((prices_clean[-1] - prices_clean[-5]) / prices_clean[-5]) * 100, 2) if len(prices_clean) >= 5 else 0

    trend  = trend or {}
    sma200 = broker.calculate_sma200(ticker)
    sma200_line = f"SMA200: ${sma200.get('sma200',0):.2f} | Price is {sma200.get('pct_from_sma',0):+.1f}% from SMA200 | Bias: {sma200.get('bias','unknown')} | {sma200.get('reason','')}" if sma200.get("available") else "SMA200: insufficient data"

    market_data = {
        "ticker":          ticker,
        "current_price":   price,
        "rsi_14":          rsi,
        "macd":            macd.get("macd", 0),
        "macd_signal":     macd.get("signal", 0),
        "macd_crossover":  macd.get("crossover", False),
        "price_5d_change": price_change_5d,
        "price_history":   prices_clean[-5:],
        "trend_direction": trend.get("direction", "unknown"),
        "trend_strength":  trend.get("strength", "unknown"),
        "momentum_5d":     trend.get("momentum_5d", 0),
        "ma20_pct":        trend.get("pct_from_ma20", 0),
        "sma200_bias":     sma200.get("bias", "unknown"),
        "sma200_pct":      sma200.get("pct_from_sma", 0),
        "sma200_fast_move":sma200.get("is_fast_move", False),
    }

    lessons      = get_relevant_lessons(ticker, rsi, "BUY")
    lessons_text = format_lessons_for_prompt(lessons)

    system = """You are a stock market research agent. Summarise market data and flag risks.
Respond ONLY in valid JSON:
{"summary": "string", "signals": ["string"], "risk_flags": ["string"]}"""

    user = (
        f"Analyse {ticker}:\n{json.dumps(market_data, indent=2)}\n\n"
        f"SMA200 CONTEXT: {sma200_line}\n\n"
        f"{lessons_text}"
    )
    response = _parse_json(_call_groq(system, user))
    return {**market_data, "research_summary": response, "lessons_applied": len(lessons)}


# ----------------------------------------------------------
#  Agent 2 — Signal agent
# ----------------------------------------------------------
def signal_agent(research: dict) -> dict:
    ticker = research["ticker"]
    rsi    = research["rsi_14"]
    print(f"  [Signal] Generating signal for {ticker}...")

    buy_lessons  = get_relevant_lessons(ticker, rsi, "BUY")
    sell_lessons = get_relevant_lessons(ticker, rsi, "SELL")
    lessons_text = format_lessons_for_prompt(buy_lessons + sell_lessons)

    if buy_lessons or sell_lessons:
        print(f"  [Signal] 🧠 Applying {len(buy_lessons)+len(sell_lessons)} past lessons")

    system = """You are a trading signal agent. Output a trading signal based on data and past lessons.
Respond ONLY in valid JSON:
{"signal": "BUY or SELL or HOLD", "confidence": 0-100, "reasoning": "one sentence", "key_factors": ["factor1", "factor2"], "lessons_influenced": true or false}

Rules:
- BUY only if RSI < 35 AND MACD shows bullish crossover
- SELL only if RSI > 70 AND 5d price change > 3%
- HOLD for everything else
- Past lessons warning against this setup = lower confidence or HOLD"""

    trend_line  = f"Trend: {research.get('trend_direction','?')} ({research.get('trend_strength','?')}) | Momentum 5d: {research.get('momentum_5d',0):+.1f}%"
    sma200_line = f"SMA200 bias: {research.get('sma200_bias','?')} | {research.get('sma200_pct',0):+.1f}% from SMA200 | Fast move: {research.get('sma200_fast_move','?')}"

    user = f"""Ticker: {research['ticker']}
Price: ${research['current_price']:.4f}
RSI(14): {research['rsi_14']}
MACD crossover: {research['macd_crossover']}
5-day change: {research['price_5d_change']}%
{trend_line}
{sma200_line}
Summary: {research['research_summary'].get('summary','')}
Risk flags: {research['research_summary'].get('risk_flags',[])}

SMA200 RULES (your dad's system):
- Price fast drop below SMA200 (strong_buy bias) → lean BUY — mean reversion likely
- Price slow grind below SMA200 (weak_buy bias) → be cautious — trend may continue down
- Price fast pump above SMA200 (strong_sell bias) → lean SELL — mean reversion likely  
- Price slow grind above SMA200 (weak_sell bias) → be cautious — trend may continue up
- Price crossed SMA200 (bullish/bearish_cross) → strong directional signal

{lessons_text}"""

    response = _parse_json(_call_groq(system, user))
    if response.get("lessons_influenced"):
        print(f"  [Signal] 🧠 Past lessons influenced this decision")
    print(f"  [Signal] → {response['signal']} ({response['confidence']}% confidence)")
    return response


# ----------------------------------------------------------
#  Agent 3 — Risk manager
# ----------------------------------------------------------
def risk_manager_agent(ticker: str, signal: dict, broker) -> dict:
    print(f"  [Risk] Sizing position for {ticker}...")

    price      = broker.get_latest_price(ticker)
    confidence = signal.get("confidence", 80)
    position   = broker.calculate_position(ticker, price, confidence)

    if not position["approved"]:
        return {"approved": False, "reason": position["reason"]}
    if signal["confidence"] < 60:
        return {"approved": False, "reason": f"Confidence too low ({signal['confidence']}%)."}

    open_positions = broker.get_open_positions()
    if len(open_positions) >= 8:
        return {"approved": False, "reason": "Max 8 concurrent positions reached."}

    system = """You are a risk manager. Protect capital.
Respond ONLY in valid JSON:
{"approved": true or false, "reason": "one sentence"}"""

    user = f"""Trade: {signal['signal']} {ticker} at {signal['confidence']}% confidence
Shares: {position['shares']} (${position['spend']:.2f}, {position['pct_of_portfolio']:.1f}% of portfolio)
Stop: ${position['stop_loss_price']} | Target: ${position['target_price']}
Open positions: {len(open_positions)}/5"""

    response = _parse_json(_call_groq(system, user))
    return {**response, **position, "entry_price": price}


# ----------------------------------------------------------
#  Agent 4 — Head auditor (smart model)
# ----------------------------------------------------------
def head_auditor_agent(ticker: str, signal: dict, risk: dict, research: dict) -> dict:
    print(f"  [Auditor] Final review for {ticker}...")

    system = """You are the head auditor. Last line of defence before a trade executes.
Approve trades that meet risk rules even with zero past lessons — lessons are a bonus not a requirement.
Only reject if: bad risk/reward, confidence below 60%, or a specific past lesson warns against this exact setup.
Respond ONLY in valid JSON:
{"approved": true or false, "reason": "one sentence", "notes": "any observations"}"""

    user = f"""Final audit:
TICKER: {ticker}
SIGNAL: {signal['signal']} — {signal['confidence']}% confidence
REASONING: {signal['reasoning']}
RISK APPROVED: {risk.get('approved')}
POSITION: {risk.get('shares')} shares @ ${risk.get('entry_price',0):.4f}
SPEND: ${risk.get('spend',0):.2f} ({risk.get('pct_of_portfolio',0):.1f}% of portfolio)
STOP: ${risk.get('stop_loss_price',0):.4f} | TARGET: ${risk.get('target_price',0):.4f}
RISK FLAGS: {research.get('research_summary',{}).get('risk_flags',[])}
LESSONS APPLIED: {research.get('lessons_applied',0)}"""

    response = _parse_json(_call_groq(system, user, model=MODEL_SMART))
    print(f"  [Auditor] → {'APPROVED ✅' if response['approved'] else 'REJECTED ❌'}: {response['reason']}")
    return response


# ----------------------------------------------------------
#  Supervisor — pre-filter first, full pipeline only if needed
# ----------------------------------------------------------
def run_supervisor(ticker: str, broker) -> dict:
    print(f"\n{'='*50}")
    print(f"  Supervisor: {ticker}")
    print(f"{'='*50}")

    try:
        # Step 1 — Pre-filter (no API call, pure maths)
        worthy, rsi, macd, trend, reason = pre_filter(ticker, broker)

        if not worthy:
            print(f"  ⚡ Pre-filter: HOLD — {reason}")
            return {"action": "HOLD", "ticker": ticker, "reason": reason}

        print(f"  ⚡ Pre-filter: PASS — {reason} — running full pipeline")

        # Step 2 — Full agent pipeline
        research = research_agent(ticker, broker, rsi, macd, trend)
        signal = signal_agent(research)

        # Hard RSI sanity check — prevent AI buying overbought or selling oversold
        if signal["signal"] == "BUY" and rsi > RSI_OVERBOUGHT:
            print(f"  Hard block: RSI {rsi:.1f} overbought — cannot BUY")
            return {"action": "HOLD", "ticker": ticker, "signal": signal}
        if signal["signal"] == "SELL" and rsi < RSI_OVERSOLD:
            print(f"  Hard block: RSI {rsi:.1f} oversold — cannot SELL")
            return {"action": "HOLD", "ticker": ticker, "signal": signal}

        if signal["signal"] == "HOLD":
            print(f"  Supervisor: HOLD — {ticker}")
            return {"action": "HOLD", "ticker": ticker, "signal": signal}

        risk = risk_manager_agent(ticker, signal, broker)
        if not risk.get("approved"):
            print(f"  Supervisor: Risk REJECTED — {risk.get('reason')}")
            return {"action": "REJECTED", "ticker": ticker, "signal": signal, "risk": risk}

        # Hard confidence check in code — no AI confusion possible
        if signal["confidence"] < 60:
            print(f"  Supervisor: Confidence too low ({signal['confidence']}%) — skipping auditor")
            return {"action": "REJECTED", "ticker": ticker, "signal": signal, "risk": risk,
                    "reason": f"Confidence {signal['confidence']}% below 60% minimum"}

        # News agent — only runs when a trade is actually about to execute (saves tokens)
        print(f"  [News] Scanning headlines for {ticker}...")
        news = run_news_agent(ticker)
        if news.get("avoid_trade"):
            print(f"  🚨 News: AVOID — {news.get('trade_impact','High risk news detected')}")
            return {"action": "REJECTED", "ticker": ticker, "signal": signal,
                    "reason": f"News risk: {news.get('trade_impact','')}"}
        if news.get("risk_level") in ("high", "critical"):
            print(f"  ⚠️  News: High risk — {news.get('trade_impact','')} — reducing confidence")
            signal["confidence"] = max(60, signal["confidence"] - 20)

        # Don't add to a losing position — only add if existing position is profitable
        existing = broker.get_open_positions()
        for pos in existing:
            if pos["ticker"] == ticker:
                if pos["unrealized_pnl"] < 0:
                    print(f"  Supervisor: Position exists in {ticker} and is in the red (${pos['unrealized_pnl']:.2f}) — skipping")
                    return {"action": "REJECTED", "ticker": ticker, "signal": signal,
                            "reason": f"Existing {ticker} position is losing — not adding to loser"}
                else:
                    print(f"  Supervisor: Position exists in {ticker} and is profitable (+${pos['unrealized_pnl']:.2f}) — allowing add")

        audit = head_auditor_agent(ticker, signal, risk, research)
        if not audit.get("approved"):
            print(f"  Supervisor: Audit REJECTED — {audit.get('reason')}")
            return {"action": "REJECTED", "ticker": ticker, "signal": signal, "risk": risk, "audit": audit}

        reasoning = (
            f"Signal: {signal['reasoning']} | "
            f"Factors: {', '.join(signal.get('key_factors',[]))} | "
            f"Lessons: {research.get('lessons_applied',0)} applied | "
            f"Auditor: {audit.get('notes','')}"
        )

        print(f"\n  ✅ ALL AGENTS APPROVED — {signal['signal']} {ticker}")
        return {
            "action":            signal["signal"],
            "ticker":            ticker,
            "entry_price":       risk["entry_price"],
            "shares":            risk["shares"],
            "stop_loss_price":   risk["stop_loss_price"],
            "target_price":      risk["target_price"],
            "signal_confidence": signal["confidence"],
            "agent_reasoning":   reasoning,
            "entry_market_data": {
                "rsi":             rsi,
                "macd_crossover":  macd.get("crossover", False),
                "price_5d_change": research.get("price_5d_change", 0),
            },
            "signal":   signal,
            "risk":     risk,
            "audit":    audit,
            "research": research,
        }

    except Exception as e:
        import traceback
        print(f"  ⚠ Error on {ticker}: {e}")
        traceback.print_exc()
        return {"action": "ERROR", "ticker": ticker, "error": str(e)}
