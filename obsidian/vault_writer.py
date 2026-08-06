# ============================================================
#  AutoTrader — obsidian/vault_writer.py
#  Writes markdown + HTML files directly into Obsidian vault
# ============================================================

import os
import sys
from datetime import datetime, timezone, timedelta
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import OBSIDIAN_VAULT

VAULT_TRADES   = os.path.join(OBSIDIAN_VAULT, "Trades")
VAULT_DAILY    = os.path.join(OBSIDIAN_VAULT, "Daily Notes")
VAULT_WEEKLY   = os.path.join(OBSIDIAN_VAULT, "Weekly Summaries")
VAULT_DASH     = os.path.join(OBSIDIAN_VAULT, "DASHBOARD.md")
VAULT_README   = os.path.join(OBSIDIAN_VAULT, "README.md")


def _ensure_folders():
    for folder in [VAULT_TRADES, VAULT_DAILY, VAULT_WEEKLY]:
        os.makedirs(folder, exist_ok=True)


def _write(path, content):
    """Atomic write — writes to temp file then replaces, bypasses Obsidian locks."""
    import tempfile, shutil
    dir_name = os.path.dirname(path)
    try:
        # Write to temp file in same directory
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic replace
        shutil.move(tmp_path, path)
    except Exception:
        # Fallback to direct write
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def _append(path, content):
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)


def _get_chart(ticker, entry_price, direction):
    try:
        from core.chart import generate_html_chart
        return generate_html_chart(ticker, entry_price, direction)
    except Exception as e:
        return "<p>Chart unavailable: " + str(e) + "</p>"


# ----------------------------------------------------------
#  1. Trade note
# ----------------------------------------------------------
def write_trade_note(trade):
    _ensure_folders()
    today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    suffix     = trade["trade_id"][-6:]
    filename   = trade["ticker"] + "-" + trade["direction"] + "-" + suffix + ".md"
    dated_folder = os.path.join(VAULT_TRADES, today)
    os.makedirs(dated_folder, exist_ok=True)
    filepath   = os.path.join(dated_folder, filename)

    emoji      = "🟢" if trade["direction"] == "BUY" else "🔴"
    reasoning  = trade.get("agent_reasoning", "No reasoning logged.")
    confidence = trade.get("signal_confidence", 0)
    entry      = trade.get("entry_price", 0)
    stop       = trade.get("stop_loss_price", 0)
    target     = trade.get("target_price", 0)
    shares     = trade.get("shares", 0)
    spend      = round(entry * shares, 2)

    risk   = round(((entry - stop) / entry) * 100, 2) if entry > 0 else 0
    reward = round(((target - entry) / entry) * 100, 2) if entry > 0 else 0
    rr     = round(reward / risk, 2) if risk > 0 else 0

    conf_emoji = "🟢" if confidence >= 75 else "🟡" if confidence >= 60 else "🔴"

    parts = reasoning.split(" | ") if " | " in reasoning else [reasoning]
    reasoning_md = "\n".join(["- " + p.strip() for p in parts if p.strip()])

    chart_html = _get_chart(trade["ticker"], entry, trade["direction"])

    content = "---\n"
    content += "ticker: " + trade["ticker"] + "\n"
    content += "direction: " + trade["direction"] + "\n"
    content += "status: OPEN\n"
    content += "opened: " + now_str + "\n"
    content += "trade_id: " + trade["trade_id"] + "\n"
    content += "confidence: " + str(confidence) + "\n"
    content += "tags: [trade, " + trade["ticker"].lower() + ", " + trade["direction"].lower() + "]\n"
    content += "---\n\n"
    content += "# " + emoji + " " + trade["direction"] + " " + trade["ticker"] + " — " + today + "\n\n"
    content += "## Position details\n"
    content += "| Field | Value |\n|---|---|\n"
    content += "| Ticker | " + trade["ticker"] + " |\n"
    content += "| Direction | " + trade["direction"] + " |\n"
    content += "| Entry price | $" + str(entry) + " |\n"
    content += "| Shares | " + str(shares) + " |\n"
    content += "| Total spend | $" + str(spend) + " |\n"
    content += "| Stop-loss | $" + str(stop) + " (-" + str(risk) + "%) |\n"
    content += "| Target | $" + str(target) + " (+" + str(reward) + "%) |\n"
    content += "| Risk/reward | 1:" + str(rr) + " |\n"
    content += "| " + conf_emoji + " Confidence | " + str(confidence) + "% |\n\n"
    content += "## Why the agents chose this trade\n"
    content += reasoning_md + "\n\n"
    content += "## What to watch\n"
    content += "- **Stop-loss** at $" + str(stop) + " — auto-closes if price drops here\n"
    content += "- **Take-profit** at $" + str(target) + " — auto-closes if price reaches here\n"
    content += "- **Risk/reward** 1:" + str(rr) + (" — good ratio" if rr >= 1.5 else " — monitor closely") + "\n\n"
    content += "## Candlestick chart — last 12 candles\n"
    content += chart_html + "\n\n"
    content += "## Outcome\n"
    content += "> Trade still open — will be updated on close.\n\n"
    content += "---\n"
    content += "[[" + today + "]] | [[DASHBOARD]] | [[Learning/lessons]]\n"

    _write(filepath, content)
    print("  ✓ Obsidian trade note: " + filename)
    return filepath


def update_trade_note_on_close(trade):
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    suffix   = trade["trade_id"][-6:]
    filename = trade["ticker"] + "-" + trade["direction"] + "-" + suffix + ".md"
    filepath = os.path.join(VAULT_TRADES, today, filename)

    if not os.path.exists(filepath):
        write_trade_note(trade)

    pnl    = trade.get("profit_loss", 0)
    pct    = trade.get("profit_pct", 0)
    result = "✅ WIN" if pnl >= 0 else "❌ LOSS"
    stop   = "Yes" if trade.get("stop_hit") else "No"
    target = "Yes" if trade.get("target_hit") else "No"

    outcome = "\n## Outcome — CLOSED\n\n"
    outcome += "| Field | Value |\n|---|---|\n"
    outcome += "| Exit price | $" + str(trade.get("exit_price", 0)) + " |\n"
    outcome += "| P&L | $" + str(round(pnl, 2)) + " |\n"
    outcome += "| Return | " + str(round(pct, 2)) + "% |\n"
    outcome += "| Result | " + result + " |\n"
    outcome += "| Stop-loss hit | " + stop + " |\n"
    outcome += "| Target hit | " + target + " |\n"
    outcome += "| Closed | " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + " |\n"

    with open(filepath, "r", encoding="utf-8") as f:
        existing = f.read()

    updated = existing.replace(
        "## Outcome\n> Trade still open — will be updated on close.",
        outcome
    ).replace("status: OPEN", "status: CLOSED\npnl: " + str(round(pnl, 2)))

    _write(filepath, updated)


# ----------------------------------------------------------
#  2. Daily note
# ----------------------------------------------------------
def write_daily_note(date_str=None):
    _ensure_folders()
    today    = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(VAULT_DAILY, today + ".md")

    if os.path.exists(filepath):
        return filepath

    content  = "---\ndate: " + today + "\ntags: [daily, trading]\n---\n\n"
    content += "# Trading log — " + today + "\n\n"
    content += "## Trades\n\n"
    content += "| Time | Ticker | Direction | Entry | Exit | P&L | Result |\n"
    content += "|---|---|---|---|---|---|---|\n\n"
    content += "## Day summary\n> Auto-updated at end of day.\n\n"
    content += "---\n[[DASHBOARD]] | [[Weekly Summaries]]\n"

    _write(filepath, content)
    print("  ✓ Obsidian daily note: " + today + ".md")
    return filepath


def append_trade_to_daily(trade):
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(VAULT_DAILY, today + ".md")
    write_daily_note(today)

    pnl      = trade.get("profit_loss", 0)
    exit_p   = trade.get("exit_price", "open")
    time_str = datetime.now(timezone.utc).strftime("%H:%M")
    result   = "✅" if pnl >= 0 else "❌"

    row = "| " + time_str + " | " + trade["ticker"] + " | " + trade["direction"]
    row += " | $" + str(trade["entry_price"]) + " | $" + str(exit_p)
    row += " | $" + str(round(pnl, 2)) + " | " + result + " |\n"

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace(
        "|---|---|---|---|---|---|---|\n",
        "|---|---|---|---|---|---|---|\n" + row
    )
    _write(filepath, content)




def write_daily_summary(date_str=None, trades=None):
    today    = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(VAULT_DAILY, today + ".md")
    if not os.path.exists(filepath):
        write_daily_note(today)
    if not trades:
        return

    wins      = [t for t in trades if t.get("profit_loss", 0) > 0]
    losses    = [t for t in trades if t.get("profit_loss", 0) <= 0]
    total_pnl = round(sum(t.get("profit_loss", 0) for t in trades), 2)
    win_rate  = round(len(wins) / len(trades) * 100, 1) if trades else 0
    best      = max(trades, key=lambda t: t.get("profit_loss", 0), default=None)
    worst     = min(trades, key=lambda t: t.get("profit_loss", 0), default=None)

    pnl_icon = "UP" if total_pnl >= 0 else "DOWN"
    wr_icon  = "GREEN" if win_rate >= 55 else "YELLOW" if win_rate >= 45 else "RED"

    rows = ["## Day summary", ""]
    rows.append("| Metric | Value |")
    rows.append("|---|---|")
    rows.append("| Net P&L (" + pnl_icon + ") | $" + str(total_pnl) + " |")
    rows.append("| Win rate (" + wr_icon + ") | " + str(win_rate) + "% |")
    rows.append("| Total trades | " + str(len(trades)) + " |")
    rows.append("| Wins | " + str(len(wins)) + " |")
    rows.append("| Losses | " + str(len(losses)) + " |")
    if best:
        rows.append("| Best trade | " + best["ticker"] + " +$" + str(round(best.get("profit_loss", 0), 2)) + " |")
    if worst:
        rows.append("| Worst trade | " + worst["ticker"] + " $" + str(round(worst.get("profit_loss", 0), 2)) + " |")
    rows.append("")
    rows.append("---")
    rows.append("[[DASHBOARD]] | [[Weekly Summaries]]")

    summary = "\n".join(rows)

    with open(filepath, "r", encoding="utf-8") as f:
        existing = f.read()

    updated = existing.replace(
        "## Day summary\n> Auto-updated at end of day.",
        summary
    )
    _write(filepath, updated)
    print("  Obsidian daily summary written: " + today)


    today      = datetime.now(timezone.utc)
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    filename   = "Week-" + week_start + ".md"
    filepath   = os.path.join(VAULT_WEEKLY, filename)

    total_pnl = sum(t.get("profit_loss", 0) for t in trades)
    wins      = sum(1 for t in trades if t.get("profit_loss", 0) > 0)
    win_rate  = round((wins / len(trades) * 100) if trades else 0, 1)

    best  = max(trades, key=lambda t: t.get("profit_loss", 0), default={})
    worst = min(trades, key=lambda t: t.get("profit_loss", 0), default={})

    trade_rows = "\n".join([
        "| " + t.get("opened_at","")[:10] + " | " + t["ticker"] + " | " + t["direction"] +
        " | $" + str(t.get("entry_price",0)) + " | $" + str(t.get("exit_price",0)) +
        " | $" + str(round(t.get("profit_loss",0),2)) + " | " +
        ("✅" if t.get("profit_loss",0) >= 0 else "❌") + " |"
        for t in trades
    ]) or "| — | — | — | — | — | — | — |"

    content  = "---\nweek: " + week_start + "\ntags: [weekly, summary]\n---\n\n"
    content += "# Weekly summary — " + week_start + "\n\n"
    content += "| Metric | Value |\n|---|---|\n"
    content += "| Total trades | " + str(len(trades)) + " |\n"
    content += "| Wins | " + str(wins) + " |\n"
    content += "| Win rate | " + str(win_rate) + "% |\n"
    content += "| Net P&L | $" + str(round(total_pnl, 2)) + " |\n\n"
    content += "## All trades\n\n"
    content += "| Date | Ticker | Direction | Entry | Exit | P&L | Result |\n"
    content += "|---|---|---|---|---|---|---|\n"
    content += trade_rows + "\n\n---\n[[DASHBOARD]]\n"

    _write(filepath, content)
    print("  ✓ Obsidian weekly summary: " + filename)


# ----------------------------------------------------------
#  4. Dashboard
# ----------------------------------------------------------
def update_dashboard(stats, open_positions):
    _ensure_folders()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total_pnl = stats.get("total_pnl", 0)
    win_rate  = stats.get("win_rate", 0)
    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    wr_emoji  = "🟢" if win_rate >= 55 else "🟡" if win_rate >= 45 else "🔴"

    pos_rows = "\n".join([
        "| " + p["ticker"] + " | " + str(p["shares"]) +
        " | $" + str(p["entry_price"]) + " | $" + str(p["current_price"]) +
        " | $" + str(p["unrealized_pnl"]) + " | " + str(p["pnl_pct"]) + "% |"
        for p in open_positions
    ]) or "| — | — | — | — | — | — |"

    content  = "---\nupdated: " + now + "\ntags: [dashboard]\n---\n\n"
    content += "# AutoTrader dashboard\n*" + now + "*\n\n"
    content += "## All-time performance\n| Metric | Value |\n|---|---|\n"
    content += "| " + pnl_emoji + " Total P&L | $" + str(total_pnl) + " |\n"
    content += "| " + wr_emoji + " Win rate | " + str(win_rate) + "% |\n"
    content += "| Total trades | " + str(stats.get("total_trades", 0)) + " |\n"
    content += "| Wins | " + str(stats.get("wins", 0)) + " |\n"
    content += "| Losses | " + str(stats.get("losses", 0)) + " |\n"
    content += "| Best trade | " + str(stats.get("best_profit_ticker","—")) + " +$" + str(stats.get("best_profit",0)) + " |\n"
    content += "| Worst trade | " + str(stats.get("worst_loss_ticker","—")) + " $" + str(stats.get("worst_loss",0)) + " |\n\n"
    content += "## Open positions\n"
    content += "| Ticker | Shares | Entry | Current | Unrealised | % |\n"
    content += "|---|---|---|---|---|---|\n"
    content += pos_rows + "\n\n"
    content += "## Quick links\n"
    content += "- [[Trades]]\n- [[Daily Notes]]\n- [[Weekly Summaries]]\n- [[Learning/lessons]]\n\n"
    content += "---\n*Generated by AutoTrader*\n"

    _write(VAULT_DASH, content)
    print("  ✓ Obsidian dashboard updated")


# ----------------------------------------------------------
#  5. Vault init
# ----------------------------------------------------------
def init_vault():
    _ensure_folders()
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    content = "# Claude AutoTrader vault\n\n"
    content += "- **Trades/** — one note per trade\n"
    content += "- **Daily Notes/** — daily logs\n"
    content += "- **Weekly Summaries/** — Sunday reports\n"
    content += "- **Learning/** — AI lessons\n"
    content += "- **Backtests/** — backtest reports\n"
    content += "- **DASHBOARD.md** — live stats\n\n"
    content += "*Initialised: " + now + "*\n"
    if not os.path.exists(VAULT_README):
        _write(VAULT_README, content)
    print("✓ Obsidian vault initialised at: " + OBSIDIAN_VAULT)
    print("  Folders created: Trades/, Daily Notes/, Weekly Summaries/")



def write_daily_summary(date_str=None, trades=None):
    today    = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(VAULT_DAILY, today + ".md")
    if not os.path.exists(filepath):
        write_daily_note(today)
    if not trades:
        return

    wins      = [t for t in trades if t.get("profit_loss", 0) > 0]
    losses    = [t for t in trades if t.get("profit_loss", 0) <= 0]
    total_pnl = round(sum(t.get("profit_loss", 0) for t in trades), 2)
    win_rate  = round(len(wins) / len(trades) * 100, 1) if trades else 0
    best      = max(trades, key=lambda t: t.get("profit_loss", 0), default=None)
    worst     = min(trades, key=lambda t: t.get("profit_loss", 0), default=None)

    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    wr_emoji  = "🟢" if win_rate >= 55 else "🟡" if win_rate >= 45 else "🔴"

    rows = ["## Day summary", ""]
    rows.append("| Metric | Value |")
    rows.append("|---|---|")
    rows.append("| " + pnl_emoji + " Net P&L | $" + str(total_pnl) + " |")
    rows.append("| " + wr_emoji + " Win rate | " + str(win_rate) + "% |")
    rows.append("| Total trades | " + str(len(trades)) + " |")
    rows.append("| Wins | " + str(len(wins)) + " |")
    rows.append("| Losses | " + str(len(losses)) + " |")
    if best:
        rows.append("| Best trade | " + best["ticker"] + " +$" + str(round(best.get("profit_loss", 0), 2)) + " |")
    if worst:
        rows.append("| Worst trade | " + worst["ticker"] + " $" + str(round(worst.get("profit_loss", 0), 2)) + " |")
    rows.append("")
    rows.append("---")
    rows.append("[[DASHBOARD]] | [[Weekly Summaries]]")

    summary = "\n".join(rows)

    with open(filepath, "r", encoding="utf-8") as f:
        existing = f.read()

    updated = existing.replace(
        "## Day summary\n> Auto-updated at end of day.",
        summary
    )
    _write(filepath, updated)
    print("  ✓ Daily summary written: " + today)
