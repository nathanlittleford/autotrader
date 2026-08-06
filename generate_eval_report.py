#!/usr/bin/env python3
# ============================================================
#  AutoTrader — generate_eval_report.py
#  Runs eval_harness.py's analyses and writes a timestamped set
#  of markdown reports to reports/<run>/ — one per section, plus
#  a final synthesis report. Numbers come straight from
#  eval_harness.py's return values, so a report always matches
#  what `python3 eval_harness.py` printed for the same DB state.
#
#  Usage:
#      python3 generate_eval_report.py
# ============================================================

import os
import sys
from datetime import datetime, timezone

sys.path.append(os.path.dirname(__file__))
import eval_harness as eh

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _pct(v):
    return "—" if v is None else f"{v}%"


def step1_report(run_dir, data):
    buy, sell = data["BUY"], data["SELL"]
    if buy["avg_pnl"] is None or sell["avg_pnl"] is None:
        finding = "Not enough trades in both directions to compare."
    elif buy["avg_pnl"] < 0 <= sell["avg_pnl"]:
        finding = "BUY is net negative while SELL is net positive — SELL entries are outperforming BUY entries."
    elif sell["avg_pnl"] < 0 <= buy["avg_pnl"]:
        finding = "SELL is net negative while BUY is net positive — BUY entries are outperforming SELL entries."
    elif buy["avg_pnl"] < 0 and sell["avg_pnl"] < 0:
        finding = "Both directions are net negative — the pipeline isn't showing an edge in either direction yet."
    else:
        finding = "Both directions are net positive."

    content = f"""# Step 1 — Precision by direction

| Direction | Trades | Wins | Win rate | Avg P&L |
|---|---|---|---|---|
| BUY  | {buy['n']} | {buy['wins']} | {_pct(buy['win_rate'])} | {_pct(buy['avg_pnl'])} |
| SELL | {sell['n']} | {sell['wins']} | {_pct(sell['win_rate'])} | {_pct(sell['avg_pnl'])} |

**Finding:** {finding}
"""
    _write(os.path.join(run_dir, "step1_precision_by_direction.md"), content)
    return finding


def step2_report(run_dir, data):
    rows = data["buckets"]
    monotonic = data["monotonic"]
    table_rows = "\n".join(
        f"| {label} | {s['n']} | {s['wins']} | {_pct(s['win_rate'])} |"
        for label, s in rows
    )

    total_n = sum(s["n"] for _, s in rows)
    max_bucket_n = max((s["n"] for _, s in rows), default=0)
    skewed = total_n > 0 and (max_bucket_n / total_n) > 0.7

    if monotonic is None:
        finding = "Not enough populated confidence buckets to assess calibration."
    elif monotonic:
        finding = "Confidence appears well-calibrated — higher stated confidence tracks with higher win rate."
    else:
        finding = ("Confidence score is not well-calibrated — higher stated confidence "
                   "doesn't reliably mean higher win rate.")
    if skewed:
        finding += (f" Also, {max_bucket_n}/{total_n} trades cluster in a single bucket — "
                    "confidence isn't discriminating outcomes meaningfully across its range.")

    content = f"""# Step 2 — Confidence calibration

| Confidence band | Trades | Wins | Win rate |
|---|---|---|---|
{table_rows}

**Monotonically increasing with confidence:** {monotonic}

**Finding:** {finding}
"""
    _write(os.path.join(run_dir, "step2_confidence_calibration.md"), content)
    return finding


def step3_report(run_dir, data, n_trades):
    if data["n"] == 0:
        finding = "No trades with rsi_at_entry recorded."
        content = f"# Step 3 — RSI-at-entry vs outcome\n\n**Finding:** {finding}\n"
        _write(os.path.join(run_dir, "step3_rsi_extremity.md"), content)
        return finding

    lo, hi = data["less_extreme"], data["more_extreme"]
    coverage = round(data["n"] / n_trades * 100, 1) if n_trades else 0
    if (hi["win_rate"] or 0) > (lo["win_rate"] or 0):
        finding = "Trades entered at more extreme RSI levels perform better."
    elif (lo["win_rate"] or 0) > (hi["win_rate"] or 0):
        finding = "Trades entered at less extreme RSI levels perform better."
    else:
        finding = "No meaningful difference by RSI extremity."
    if coverage < 50:
        finding += (f" Coverage caveat: rsi_at_entry is only populated on {data['n']}/{n_trades} "
                    f"closed trades ({coverage}%) — it was added to the pipeline partway through "
                    "this trade history, so older trades don't have it. Read this section as a "
                    "smaller, more recent sample, not the full dataset.")

    content = f"""# Step 3 — RSI-at-entry vs outcome

Coverage: {data['n']}/{n_trades} closed trades ({coverage}%)

| Bucket | Trades | Wins | Win rate |
|---|---|---|---|
| Less extreme RSI (closer to 50) | {lo['n']} | {lo['wins']} | {_pct(lo['win_rate'])} |
| More extreme RSI (further from 50) | {hi['n']} | {hi['wins']} | {_pct(hi['win_rate'])} |

**Finding:** {finding}
"""
    _write(os.path.join(run_dir, "step3_rsi_extremity.md"), content)
    return finding


def step4_report(run_dir, data):
    ws, wo = data["with_lessons"], data["without_lessons"]
    small_sample = min(ws["n"], wo["n"]) < 10
    if (ws["win_rate"] or 0) > (wo["win_rate"] or 0):
        finding = "Trades where lessons were applied outperform those without."
    elif (wo["win_rate"] or 0) > (ws["win_rate"] or 0):
        finding = "Trades without lessons applied outperform those with — lessons aren't adding measurable edge yet."
    else:
        finding = "No meaningful difference with vs without lessons applied."
    if small_sample:
        finding += (f" Sample size caveat: one bucket has only {min(ws['n'], wo['n'])} trades — "
                    "too few to draw a reliable conclusion.")

    content = f"""# Step 4 — Lessons-influenced vs not

| Bucket | Trades | Wins | Win rate |
|---|---|---|---|
| With lessons applied    | {ws['n']} | {ws['wins']} | {_pct(ws['win_rate'])} |
| Without lessons applied | {wo['n']} | {wo['wins']} | {_pct(wo['win_rate'])} |

**Finding:** {finding}
"""
    _write(os.path.join(run_dir, "step4_lessons_influence.md"), content)
    return finding


def step5_report(run_dir, data):
    n = data["n"]
    if n == 0:
        finding = "No closed trades."
    else:
        stop_pct = round(data["stop_hit"] / n * 100, 1)
        target_pct = round(data["target_hit"] / n * 100, 1)
        neither_pct = round(data["neither"] / n * 100, 1)
        finding = (f"{neither_pct}% of trades close through the dynamic exit system "
                   "(profit lock, RSI exhaustion, chandelier exit, trend reversal, max hold) "
                   f"rather than a fixed stop ({stop_pct}%) or target ({target_pct}%). "
                   "Note: target_hit is hardcoded False at the close_trade() call site in "
                   "main.py — the exit logic moved to dynamic conditions and this legacy field "
                   "was never wired up to reflect that, so its 3.8%-style figure reflects a "
                   "handful of trades closed under an older fixed take-profit version of the "
                   "code, not current behavior.")

    content = f"""# Step 5 — Stop/target hit rate

| Outcome | Count | % of closed trades |
|---|---|---|
| Stop hit   | {data.get('stop_hit', 0)} | {_pct(round(data['stop_hit']/n*100, 1)) if n else '—'} |
| Target hit | {data.get('target_hit', 0)} | {_pct(round(data['target_hit']/n*100, 1)) if n else '—'} |
| Neither (dynamic exit) | {data.get('neither', 0)} | {_pct(round(data['neither']/n*100, 1)) if n else '—'} |

**Finding:** {finding}
"""
    _write(os.path.join(run_dir, "step5_stop_target_hit_rate.md"), content)
    return finding


def step6_report(run_dir, data):
    if data["n"] == 0:
        finding = ("No trades with close_reason recorded yet — this field is forward-only "
                   "(added after the existing closed trades), so it populates as new trades "
                   "close going forward.")
        content = f"# Step 6 — Win rate / avg P&L by close reason\n\n**Finding:** {finding}\n"
        _write(os.path.join(run_dir, "step6_close_reason_breakdown.md"), content)
        return finding

    buckets = data["buckets"]
    table_rows = "\n".join(
        f"| {label} | {s['n']} | {s['wins']} | {_pct(s['win_rate'])} | {_pct(s['avg_pnl'])} |"
        for label, s in buckets.items()
    )
    best = max(buckets.items(), key=lambda kv: kv[1]["avg_pnl"])
    worst = min(buckets.items(), key=lambda kv: kv[1]["avg_pnl"])
    finding = f"Best-performing exit: {best[0]} (avg P&L {best[1]['avg_pnl']}%). Worst: {worst[0]} (avg P&L {worst[1]['avg_pnl']}%)."

    content = f"""# Step 6 — Win rate / avg P&L by close reason

| Close reason | Trades | Wins | Win rate | Avg P&L |
|---|---|---|---|---|
{table_rows}

**Finding:** {finding}
"""
    _write(os.path.join(run_dir, "step6_close_reason_breakdown.md"), content)
    return finding


KNOWN_CAVEATS = """## Known data quality caveats

- **agent_log table is dead infrastructure** — it exists in the schema but `crew.py` never
  writes to it. This harness works entirely off outcome columns on the `trades` table, which
  means precision is measurable but recall (opportunities silently HOLD'd on) is not.
- **rsi_at_entry is forward-populated from 2026-06-19** — the field was added to
  `run_supervisor()`'s return dict partway through this trade history. Trades opened before
  that date will always show as missing; this is expected, not a live bug.
- **target_hit is a legacy field, hardcoded `False`** at the `close_trade()` call site in
  `main.py`. The exit logic evolved from fixed take-profit targets to a 5-condition dynamic
  exit system, and this field was never wired up to reflect that — treat any non-zero
  target_hit rate as residue from the old exit logic, not current behavior.
- **close_reason is forward-only** — added this session. Existing closed trades won't have it
  retroactively; Step 6 will only become meaningful as new trades close.
"""


def final_report(run_dir, run_id, n_trades, findings):
    verdict = ("Net edge is not yet established — treat this as a research/paper system, "
               "not one ready for more capital.")
    if (findings.get("step1") or "").startswith("Both directions are net positive"):
        verdict = "Both directions show a positive edge — a promising sign, but keep validating over more trades."

    content = f"""# AutoTrader Eval — Final Report
Run: {run_id}
Closed trades evaluated: {n_trades}

## Summary of findings

1. **Precision by direction** — {findings.get('step1', '—')}
2. **Confidence calibration** — {findings.get('step2', '—')}
3. **RSI-at-entry vs outcome** — {findings.get('step3', '—')}
4. **Lessons-influenced vs not** — {findings.get('step4', '—')}
5. **Stop/target hit rate** — {findings.get('step5', '—')}
6. **Close reason breakdown** — {findings.get('step6', '—')}

{KNOWN_CAVEATS}

## Verdict

{verdict}

---
See step1_*.md through step6_*.md in this folder for the full numbers behind each finding.
"""
    _write(os.path.join(run_dir, "final_report.md"), content)


def main():
    results = eh.main()  # reuses eval_harness's console output + returns the same stats dicts

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    run_dir = os.path.join(REPORTS_DIR, run_id)

    findings = {}
    findings["step1"] = step1_report(run_dir, results["precision_by_direction"])
    findings["step2"] = step2_report(run_dir, results["confidence_calibration"])
    findings["step3"] = step3_report(run_dir, results["rsi_extremity"], results["n_trades"])
    findings["step4"] = step4_report(run_dir, results["lessons_influence"])
    findings["step5"] = step5_report(run_dir, results["stop_target_hit_rate"])
    findings["step6"] = step6_report(run_dir, results["close_reason_breakdown"])
    final_report(run_dir, run_id, results["n_trades"], findings)

    print(f"\n{'='*50}")
    print(f"  Eval report generated: reports/{run_id}/")
    print(f"  Trades evaluated: {results['n_trades']}")
    print(f"  7 files written (6 step reports + final_report.md)")
    print(f"{'='*50}\n")
    return run_dir


if __name__ == "__main__":
    main()
