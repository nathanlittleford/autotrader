# ============================================================
#  AutoTrader — agents/learning.py
#  The learning agent. Runs after every trade closes.
#  Writes lessons to lessons.json.
#  All other agents read lessons before making decisions.
# ============================================================

import json
import os
import sys
from datetime import datetime, timezone
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import GROQ_API_KEY, OBSIDIAN_VAULT

try:
    from groq import Groq
except ImportError:
    print("⚠  groq not installed. Run: pip install groq")
    raise

client = Groq(api_key=GROQ_API_KEY)
MODEL  = "llama-3.1-8b-instant"

LESSONS_PATH  = os.path.join(os.path.dirname(__file__), "..", "lessons.json")
OBSIDIAN_LESSONS = os.path.join(OBSIDIAN_VAULT, "Learning", "lessons.md")


# ----------------------------------------------------------
#  Lessons file management
# ----------------------------------------------------------
def load_lessons() -> list:
    if os.path.exists(LESSONS_PATH):
        with open(LESSONS_PATH, "r") as f:
            return json.load(f)
    return []


def save_lessons(lessons: list):
    with open(LESSONS_PATH, "w") as f:
        json.dump(lessons, f, indent=2)


def get_relevant_lessons(ticker: str, rsi: float, direction: str) -> list:
    """
    Pull lessons relevant to this specific trade setup.
    Called by research + signal agents before they make decisions.
    """
    lessons = load_lessons()
    relevant = []

    for lesson in lessons:
        # Match by ticker
        ticker_match = lesson.get("ticker") == ticker
        # Match by RSI range (within 10 points)
        rsi_match = abs((lesson.get("rsi_at_entry") or 50) - rsi) <= 10
        # Match by direction
        dir_match = lesson.get("direction") == direction

        if ticker_match or (rsi_match and dir_match):
            relevant.append(lesson)

    # Return most recent 5 relevant lessons
    return sorted(relevant, key=lambda x: x.get("timestamp", ""), reverse=True)[:5]


def format_lessons_for_prompt(lessons: list) -> str:
    """Format lessons into a string the agent can read."""
    if not lessons:
        return "No relevant lessons from past trades yet."

    lines = ["Past trade lessons (learn from these):"]
    for i, l in enumerate(lessons, 1):
        outcome = "WIN ✅" if l.get("outcome") == "win" else "LOSS ❌"
        lines.append(
            f"{i}. [{outcome}] {l.get('ticker')} {l.get('direction')} — "
            f"RSI was {l.get('rsi_at_entry', '?')} | "
            f"P&L: ${l.get('profit_loss', 0):+.2f} | "
            f"Lesson: {l.get('lesson_summary', '?')} | "
            f"Watch for: {l.get('warning_signals', '?')}"
        )
    return "\n".join(lines)


# ----------------------------------------------------------
#  The learning agent — runs after every trade closes
# ----------------------------------------------------------
def run_learning_agent(trade: dict, entry_data: dict = None) -> dict:
    """
    Analyses a closed trade and extracts lessons.
    trade: the closed trade dict from database
    entry_data: the market data at the time of entry (RSI, MACD etc)
    """
    ticker     = trade.get("ticker", "?")
    direction  = trade.get("direction", "?")
    profit_loss = trade.get("profit_loss", 0) or 0
    profit_pct  = trade.get("profit_pct", 0) or 0
    outcome    = "win" if profit_loss > 0 else "loss"
    reasoning  = trade.get("agent_reasoning", "No reasoning logged.")
    stop_hit   = trade.get("stop_hit", 0)
    target_hit = trade.get("target_hit", 0)

    print(f"\n  [Learning] Analysing closed {direction} {ticker} — {outcome.upper()} ${profit_loss:+.2f}")

    system = """You are a trading system learning agent. Your job is to analyse completed trades 
and extract clear, actionable lessons that will improve future trading decisions.

Be specific and honest. If the trade lost money, identify exactly what signals were misleading.
If it made money, identify what signals were most predictive.

Respond ONLY in valid JSON with exactly these keys:
{
  "lesson_summary": "one clear sentence about what this trade teaches",
  "what_went_right": "what signals or conditions led to profit (or limited loss)",
  "what_went_wrong": "what signals were misleading or missed (or N/A if win)",
  "warning_signals": "specific things to watch for next time in similar setups",
  "confidence_adjustment": "should confidence threshold be higher/lower/same for this setup",
  "avoid_conditions": "specific market conditions to avoid for this ticker/setup",
  "seek_conditions": "specific conditions that would make this a better trade next time"
}"""

    user = f"""Analyse this completed trade and extract lessons:

TRADE DETAILS:
Ticker: {ticker}
Direction: {direction}
Outcome: {outcome.upper()} — ${profit_loss:+.2f} ({profit_pct:+.1f}%)
Stop-loss hit: {'Yes' if stop_hit else 'No'}
Target hit: {'Yes' if target_hit else 'No'}
Entry reasoning: {reasoning}

MARKET CONDITIONS AT ENTRY:
RSI: {entry_data.get('rsi', 'unknown') if entry_data else 'unknown'}
MACD crossover: {entry_data.get('macd_crossover', 'unknown') if entry_data else 'unknown'}
5-day price change: {entry_data.get('price_5d_change', 'unknown') if entry_data else 'unknown'}%
Signal confidence: {trade.get('signal_confidence', 'unknown')}%

What can the system learn from this trade to make better decisions next time?"""

    try:
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            raw = response.choices[0].message.content.strip()
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                import urllib.request
                payload = json.dumps({
                    "model": "llama3.1:8b",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 600},
                }).encode("utf-8")
                req = urllib.request.Request(
                    "http://localhost:11434/api/chat", data=payload,
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                raw = data["message"]["content"].strip()
            else:
                raise

        # Parse JSON
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        analysis = json.loads(match.group()) if match else {}

    except Exception as e:
        print(f"  [Learning] Agent error: {e}")
        analysis = {
            "lesson_summary": f"Trade {'won' if outcome == 'win' else 'lost'} — manual review needed",
            "what_went_right": "N/A",
            "what_went_wrong": "N/A",
            "warning_signals": "N/A",
            "confidence_adjustment": "same",
            "avoid_conditions": "N/A",
            "seek_conditions": "N/A",
        }

    # Build the lesson record
    lesson = {
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "trade_id":           trade.get("trade_id", "?"),
        "ticker":             ticker,
        "direction":          direction,
        "outcome":            outcome,
        "profit_loss":        round(profit_loss, 2),
        "profit_pct":         round(profit_pct, 2),
        "rsi_at_entry":       entry_data.get("rsi", None) if entry_data else None,
        "macd_crossover":     entry_data.get("macd_crossover", None) if entry_data else None,
        "signal_confidence":  trade.get("signal_confidence", None),
        "stop_hit":           bool(stop_hit),
        "target_hit":         bool(target_hit),
        **analysis,
    }

    # Save to lessons.json
    lessons = load_lessons()
    lessons.append(lesson)
    save_lessons(lessons)

    # Write to Obsidian
    _write_lesson_to_obsidian(lesson, lessons)

    print(f"  [Learning] Lesson saved: {analysis.get('lesson_summary', '')}")
    return lesson


# ----------------------------------------------------------
#  Write lessons to Obsidian
# ----------------------------------------------------------
def _write_lesson_to_obsidian(new_lesson: dict, all_lessons: list):
    """Updates the lessons.md file in Obsidian with all lessons."""
    folder = os.path.join(OBSIDIAN_VAULT, "Learning")
    os.makedirs(folder, exist_ok=True)

    wins   = [l for l in all_lessons if l.get("outcome") == "win"]
    losses = [l for l in all_lessons if l.get("outcome") == "loss"]

    # Group lessons by ticker
    by_ticker = {}
    for l in all_lessons:
        t = l.get("ticker", "?")
        if t not in by_ticker:
            by_ticker[t] = []
        by_ticker[t].append(l)

    # Build ticker sections
    ticker_sections = []
    for ticker, lessons in sorted(by_ticker.items()):
        t_wins   = sum(1 for l in lessons if l.get("outcome") == "win")
        t_losses = len(lessons) - t_wins
        t_pnl    = sum(l.get("profit_loss", 0) for l in lessons)

        rows = "\n".join([
            f"| {l['timestamp'][:10]} | {l['direction']} | "
            f"{'✅' if l['outcome']=='win' else '❌'} | "
            f"${l.get('profit_loss',0):+.2f} | "
            f"{l.get('lesson_summary','—')} | "
            f"{l.get('warning_signals','—')} |"
            for l in sorted(lessons, key=lambda x: x['timestamp'], reverse=True)
        ])

        ticker_sections.append(f"""
### {ticker} — {t_wins}W / {t_losses}L / ${t_pnl:+.2f} total

| Date | Direction | Result | P&L | Lesson | Watch for |
|---|---|---|---|---|---|
{rows}

**Avoid:** {lessons[-1].get('avoid_conditions','—')}
**Seek:** {lessons[-1].get('seek_conditions','—')}
""")

    # Most recent lessons
    recent = sorted(all_lessons, key=lambda x: x['timestamp'], reverse=True)[:10]
    recent_rows = "\n".join([
        f"| {l['timestamp'][:10]} | {l['ticker']} | {l['direction']} | "
        f"{'✅' if l['outcome']=='win' else '❌'} | "
        f"${l.get('profit_loss',0):+.2f} | "
        f"{l.get('lesson_summary','—')} |"
        for l in recent
    ])

    content = f"""---
updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
total_lessons: {len(all_lessons)}
wins: {len(wins)}
losses: {len(losses)}
tags: [learning, trading, lessons]
---

# 🧠 AutoTrader — learning log
*Updated automatically after every closed trade*

The system learns from every trade it makes. Wins reinforce good signals. Losses teach what to avoid.

---

## Summary
| Metric | Value |
|---|---|
| Total lessons | {len(all_lessons)} |
| From wins | {len(wins)} |
| From losses | {len(losses)} |
| Most recent | {all_lessons[-1]['ticker'] if all_lessons else '—'} — {all_lessons[-1].get('lesson_summary','—') if all_lessons else '—'} |

---

## 10 most recent lessons

| Date | Ticker | Direction | Result | P&L | Lesson |
|---|---|---|---|---|---|
{recent_rows}

---

## Lessons by ticker
{''.join(ticker_sections)}

---

## How this works
After every trade closes, the learning agent:
1. Reviews the entry signals (RSI, MACD, confidence)
2. Compares them to what actually happened
3. Extracts a specific lesson and warning signals
4. Saves it here AND feeds it back into future agent decisions

*The longer this runs, the smarter it gets.*

---
[[DASHBOARD]] | [[Weekly Summaries]]
"""

    with open(OBSIDIAN_LESSONS, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  [Learning] Obsidian lessons.md updated ({len(all_lessons)} total lessons)")


# ----------------------------------------------------------
#  Quick stats on what the system has learned
# ----------------------------------------------------------
def print_learning_stats():
    lessons = load_lessons()
    if not lessons:
        print("No lessons yet — run some trades first.")
        return

    wins   = [l for l in lessons if l.get("outcome") == "win"]
    losses = [l for l in lessons if l.get("outcome") == "loss"]

    print(f"\n{'='*50}")
    print(f"  Learning stats — {len(lessons)} lessons total")
    print(f"{'='*50}")
    print(f"  Wins logged  : {len(wins)}")
    print(f"  Losses logged: {len(losses)}")

    if losses:
        print(f"\n  Most common loss patterns:")
        for l in losses[-3:]:
            print(f"  • {l['ticker']} {l['direction']}: {l.get('what_went_wrong','?')}")

    if wins:
        print(f"\n  Most reliable win conditions:")
        for l in wins[-3:]:
            print(f"  • {l['ticker']} {l['direction']}: {l.get('what_went_right','?')}")


if __name__ == "__main__":
    print_learning_stats()
