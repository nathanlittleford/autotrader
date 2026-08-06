---
name: eval-cycle
description: Run AutoTrader's full eval cycle (all 6 eval_harness.py sections) and generate a timestamped report per step plus a final synthesis report in reports/. Use when the user says "run the eval", "score the pipeline", or "/eval-cycle".
---

# /eval-cycle — AutoTrader eval cycle

Runs the agent pipeline's eval harness end-to-end and produces a persistent,
reproducible set of markdown reports — not just console output.

1. Run `python3 generate_eval_report.py` from the project root
   (`/Users/nathanlittleford/Downloads/autotrader`). This is a deterministic
   Python script — it imports `eval_harness.py`, runs all 6 analysis
   sections (precision by direction, confidence calibration, RSI-at-entry,
   lessons influence, stop/target hit rate, close-reason breakdown), and
   writes `reports/<YYYY-MM-DD_HHMM>/step1_*.md` through `step6_*.md` plus
   `final_report.md`. Do not hand-write the report content yourself —
   the script owns the numbers and the finding logic, so results stay
   consistent run to run.
2. If the script errors, fix the underlying issue (e.g. a schema change in
   `eval_harness.py` it doesn't expect) rather than working around it, then
   re-run.
3. Read the `final_report.md` it just wrote.
4. Reply in chat with a short summary only — do not paste the full report:
   - Trade count evaluated and the report folder path
   - The headline verdict line
   - Top 2-3 findings worth flagging (in your own words, from the report)
   - Any data-quality caveat that materially affects how to read this run
     (e.g. a section still at N=0)

Keep the chat reply under ~150 words. The full detail lives in the report
files — point the user there rather than restating everything.
