# ============================================================
#  AutoTrader — core/consistency.py
#  Consistency scoring system
#  Measures whether wins are reliably sized vs losses
#  Auto-demotes underperforming tickers to Tier 2
# ============================================================

import os
import sys
import json
from datetime import datetime, timezone
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

MIN_TRADES_TO_SCORE = 8     # need at least 8 trades before scoring
DEMOTION_THRESHOLD  = 0.5   # below this = auto-demote to Tier 2
PROMOTION_THRESHOLD = 0.8   # above this = strong performer


def calculate_consistency(lessons: list, ticker: str) -> dict:
    """
    Calculate consistency score for a ticker from its lessons.
    consistency = (avg_win / avg_loss) * win_rate
    """
    ticker_lessons = [l for l in lessons if l.get("ticker") == ticker
                      and l.get("outcome") in ("win", "loss")]

    if len(ticker_lessons) < MIN_TRADES_TO_SCORE:
        return {
            "ticker":       ticker,
            "score":        None,
            "verdict":      "insufficient_data",
            "total_trades": len(ticker_lessons),
            "message":      f"Need {MIN_TRADES_TO_SCORE} trades, have {len(ticker_lessons)}"
        }

    wins   = [l for l in ticker_lessons if l.get("outcome") == "win"]
    losses = [l for l in ticker_lessons if l.get("outcome") == "loss"]

    win_rate = len(wins) / len(ticker_lessons)

    # Average win and loss sizes
    avg_win  = sum(abs(l.get("profit_loss", 0)) for l in wins)   / len(wins)   if wins   else 0
    avg_loss = sum(abs(l.get("profit_loss", 0)) for l in losses) / len(losses) if losses else 0.01

    # Detect outlier wins (3x average)
    if wins:
        sorted_wins  = sorted([abs(l.get("profit_loss", 0)) for l in wins])
        median_win   = sorted_wins[len(sorted_wins) // 2]
        outlier_wins = [w for w in sorted_wins if w > median_win * 3]
        outlier_pct  = len(outlier_wins) / len(wins) * 100
    else:
        outlier_pct  = 0
        median_win   = 0
        outlier_wins = []

    # Consistency score
    score = round((avg_win / avg_loss) * win_rate, 3) if avg_loss > 0 else round(avg_win * win_rate, 3)

    # Verdict
    if score >= PROMOTION_THRESHOLD:
        verdict = "strong"
        emoji   = "🟢"
    elif score >= DEMOTION_THRESHOLD:
        verdict = "acceptable"
        emoji   = "🟡"
    else:
        verdict = "weak"
        emoji   = "🔴"

    # Check if wins are masking losses
    total_pnl    = sum(l.get("profit_loss", 0) for l in ticker_lessons)
    pnl_ex_outliers = total_pnl - sum(outlier_wins)
    masked = outlier_pct > 30 and pnl_ex_outliers < 0

    return {
        "ticker":            ticker,
        "score":             score,
        "verdict":           verdict,
        "emoji":             emoji,
        "total_trades":      len(ticker_lessons),
        "wins":              len(wins),
        "losses":            len(losses),
        "win_rate":          round(win_rate * 100, 1),
        "avg_win":           round(avg_win, 2),
        "avg_loss":          round(avg_loss, 2),
        "total_pnl":         round(total_pnl, 2),
        "outlier_pct":       round(outlier_pct, 1),
        "wins_masking_losses": masked,
        "message":           f"{emoji} Score: {score} | {len(wins)}W/{len(losses)}L | Avg win: ${avg_win:.2f} vs avg loss: ${avg_loss:.2f}"
    }


def score_all_tickers(lessons: list) -> list:
    """Score every ticker that has enough lesson data."""
    tickers = list(set(l.get("ticker") for l in lessons))
    results = []
    for ticker in sorted(tickers):
        result = calculate_consistency(lessons, ticker)
        if result["verdict"] != "insufficient_data":
            results.append(result)
    return sorted(results, key=lambda x: x["score"], reverse=True)


def auto_demote_check(lessons: list, settings_path: str) -> list:
    """
    Check all tickers and auto-demote weak ones to Tier 2.
    Returns list of tickers that were demoted.
    """
    scores   = score_all_tickers(lessons)
    demoted  = []

    with open(settings_path, "r") as f:
        content = f.read()

    for s in scores:
        ticker  = s["ticker"]
        score   = s["score"]
        verdict = s["verdict"]

        # Only demote Tier 1 tickers that are consistently weak
        if verdict == "weak" and s["total_trades"] >= MIN_TRADES_TO_SCORE:
            # Check if currently Tier 1
            if f'"ticker": "{ticker}", "tier": 1' in content:
                old = f'{{"ticker": "{ticker}", "tier": 1, "label":'
                # Find the full line
                import re
                match = re.search(rf'\{{"ticker": "{re.escape(ticker)}", "tier": 1, "label": "([^"]+)"\}}', content)
                if match:
                    label   = match.group(1)
                    new_label = label + " — auto-demoted (score: " + str(score) + ")"
                    old_line  = f'{{"ticker": "{ticker}", "tier": 1, "label": "{label}"}}'
                    new_line  = f'{{"ticker": "{ticker}", "tier": 2, "label": "{new_label}"}}'
                    content   = content.replace(old_line, new_line)
                    demoted.append(ticker)
                    print(f"  🔴 Auto-demoted {ticker} to Tier 2 (consistency score: {score})")

    if demoted:
        with open(settings_path, "w") as f:
            f.write(content)

    return demoted


def write_consistency_to_obsidian(scores: list, vault_path: str, demoted: list = None):
    """Write consistency report to Obsidian."""
    folder   = os.path.join(vault_path, "Performance")
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, "consistency-scores.md")
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = "\n".join([
        f"| {s['emoji']} {s['ticker']} | {s['score']} | {s['win_rate']}% | "
        f"${s['avg_win']:.2f} | ${s['avg_loss']:.2f} | ${s['total_pnl']:+.2f} | "
        f"{'⚠️ YES' if s['wins_masking_losses'] else 'No'} | {s['verdict']} |"
        for s in scores
    ])

    strong     = [s for s in scores if s["verdict"] == "strong"]
    acceptable = [s for s in scores if s["verdict"] == "acceptable"]
    weak       = [s for s in scores if s["verdict"] == "weak"]
    masked     = [s for s in scores if s["wins_masking_losses"]]

    content  = f"---\nupdated: {now}\ntags: [performance, consistency]\n---\n\n"
    content += f"# 📊 Consistency scores\n*Updated: {now}*\n\n"
    content += f"Measures whether wins are **reliably sized** vs losses.\n"
    content += f"`score = (avg_win / avg_loss) × win_rate` — higher is better.\n\n"
    content += f"- 🟢 Strong (≥0.8): {len(strong)} tickers\n"
    content += f"- 🟡 Acceptable (0.5-0.8): {len(acceptable)} tickers\n"
    content += f"- 🔴 Weak (<0.5): {len(weak)} tickers\n"
    if masked:
        content += f"- ⚠️ Wins masking losses: {', '.join(s['ticker'] for s in masked)}\n"
    if demoted:
        content += f"- 🔻 Auto-demoted this run: {', '.join(demoted)}\n"
    content += "\n---\n\n"
    content += "## All scores\n\n"
    content += "| Ticker | Score | Win rate | Avg win | Avg loss | Total P&L | Outliers masking? | Verdict |\n"
    content += "|---|---|---|---|---|---|---|---|\n"
    content += rows + "\n\n---\n[[DASHBOARD]] | [[Learning/lessons]]\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  ✓ Consistency scores written to Obsidian")
    return filepath


if __name__ == "__main__":
    from agents.learning import load_lessons
    from config.settings import OBSIDIAN_VAULT

    print("Calculating consistency scores...")
    lessons = load_lessons()
    scores  = score_all_tickers(lessons)

    print(f"\n{'='*55}")
    print(f"  CONSISTENCY SCORES ({len(scores)} tickers scored)")
    print(f"{'='*55}")
    for s in scores:
        masked = " ⚠️  WINS MASKING LOSSES" if s["wins_masking_losses"] else ""
        print(f"  {s['emoji']} {s['ticker']:12} score: {s['score']:.3f} | "
              f"{s['wins']}W/{s['losses']}L | "
              f"avg win ${s['avg_win']:.2f} vs avg loss ${s['avg_loss']:.2f}{masked}")

    # Auto-demote check
    settings_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.py")
    demoted = auto_demote_check(lessons, settings_path)

    # Write to Obsidian
    write_consistency_to_obsidian(scores, OBSIDIAN_VAULT, demoted)

    if demoted:
        print(f"\n  🔻 Auto-demoted: {', '.join(demoted)}")
        print(f"  Restart the loop to apply changes.")
    else:
        print(f"\n  ✓ No auto-demotions needed.")
