# AutoTrader

A five-agent paper trading system that scans a tiered watchlist of stocks and crypto, decides whether to buy, sell, or hold using a chain of LLM agents, and manages open positions with a dynamic, multi-condition exit strategy. Built as a real project, not a demo — it's been running continuously for months and has closed over 250 trades.

## What it does

AutoTrader watches a configurable list of tickers across three tiers (tradeable stocks, learn-only tickers, and crypto, which trades 24/7) and runs each one through a supervised pipeline before ever placing a trade:

1. **Pre-filter** — a pure-math RSI, trend, volume, and EMA check runs first, with zero API calls. Only tickers that clear this bar (RSI oversold/overbought, safe trend direction, live volume) go on to the full agent pipeline. Everything else is an instant HOLD.
2. **Research agent** — pulls price history, RSI, MACD, SMA200 positioning, and trend context, and summarises the setup along with any risk flags.
3. **Signal agent** — turns the research into a BUY/SELL/HOLD call with a confidence score, applying lessons learned from past trades with a similar setup.
4. **Risk manager** — sizes the position based on confidence and portfolio state, and enforces hard rules like a cash reserve and a cap on concurrent positions.
5. **Head auditor** — a final review pass using a stronger model, the last line of defence before a trade actually executes.

Once a position is open, a separate exit system manages it dynamically: a hard stop-loss, a profit lock that moves the stop to breakeven once a trade is up 3%, an RSI-exhaustion check that closes a trade once the original signal is no longer valid, an ATR-based chandelier trailing stop, a trend-reversal check, and a five-day max hold as a final safety net.

Every trade, along with the agents' reasoning, is logged to SQLite and written out to Obsidian as a running trade journal.

## Stack

Python, Groq API (Llama 3.1 8B for the cheap agents, Llama 3.3 70B for the auditor) with a local Ollama fallback if the API rate-limits, SQLite for persistence, yfinance for market data, and an Obsidian vault as the reporting layer.

## Running it

\`\`\`bash
python3 main.py --setup    # first-time setup
python3 main.py --test     # dry run, no real orders
python3 main.py --loop     # runs continuously, scanning every 15 minutes
python3 main.py --learn    # show learning stats
\`\`\`

## Evaluation

\`eval_harness.py\` scores the agent pipeline's decisions against actual trade outcomes: precision by trade direction, confidence calibration (does higher stated confidence actually predict a higher win rate), the influence of applied lessons, and exit-condition breakdown. \`generate_eval_report.py\` runs the harness and writes a timestamped markdown report to \`reports/\`.

---

## Case study: finding the gap between what the database said and what the system actually did

I wanted to know how well AutoTrader was actually performing beyond raw profit and loss, so I set out to build an evaluation harness that could score the agents' decisions against real outcomes. Along the way I found two things that had quietly drifted apart from what I assumed the system was doing.

### The table that was never written to

Before writing a line of the harness, I checked the schema. There was already an \`agent_log\` table, purpose-built to record every individual agent call — input data, output data, tokens used, timestamped and keyed to a trade ID. It looked like exactly the join table an eval harness would want, letting me pull each agent's reasoning alongside the trade's eventual result.

It had zero rows in it. The table was defined in \`database.py\` and never once written to anywhere in \`crew.py\`. Not a bug in the traditional sense, since nothing was throwing an error; it was infrastructure that had been designed and then never wired up. I rebuilt the eval design around the \`trades\` table alone, which still held enough — \`signal_confidence\`, \`rsi_at_entry\`, \`agent_reasoning\`, \`stop_hit\`, \`target_hit\` — to answer most of what I actually cared about.

### What the numbers surfaced

With 266 closed trades to work with, BUY signals were closing at a 41.5% win rate with an average P&L of -0.06%, essentially break-even but slightly negative once losses were weighed against wins. SELL signals, despite a lower sample size, were winning 46.6% of the time with a positive average P&L, which lines up with the SELL rule (RSI above 70 *and* a 5-day price move over 3%) being a meaningfully stricter gate than the BUY rule.

The more useful finding was in how confidence scores were distributed rather than in the win rates themselves. Of 266 trades, 218 sat in the 80-90% confidence bucket, with almost nothing spread across the rest and nothing above 90%. A confidence score clustered that tightly isn't giving the risk manager or auditor much to differentiate on — a model that's honest about when it's less sure is more useful downstream than one that calls almost everything 85% confident regardless of the setup.

### Chasing down the trades that "closed some other way"

The stop/target breakdown was where things got genuinely confusing at first. Only 3.8% of closed trades had \`target_hit\` set to true, 28.2% had \`stop_hit\` true, and the remaining 68% had neither flag set, despite every trade obviously closing somehow.

Reading through \`main.py\`'s position management loop explained it. The exit logic had evolved past a simple stop-loss-or-target-price model into the five separate conditions described above. Every one of those exits calls the same \`close_trade()\` function, but that function only ever received two booleans, and \`target_hit\` was hardcoded to \`False\` in every single call site. The ten historical trades showing \`target_hit=1\` almost certainly came from an earlier version of the strategy, before the exit logic was rewritten, and the database schema simply never caught up to the code.

The fix was small: add a \`close_reason\` text column to the \`trades\` table, and pass through the human-readable reason string that \`main.py\` was already constructing internally but never persisting. Every trade now closes with a specific, queryable reason attached instead of two flags that had stopped meaning anything six exit conditions ago.

### What this changes

None of this changed AutoTrader's actual trading logic — the system was still running live paper trades throughout, so the fix was deliberately scoped to instrumentation only. What it does change is what the eval harness can measure going forward: once enough trades close under the new schema, win rate can be broken down by which of the five exit conditions actually fired, rather than inferred indirectly from timing and price action after the fact.

The broader lesson was less about SQL and more about a pattern worth watching for generally: a system's logging and its actual behaviour drift apart over time as the behaviour keeps evolving and the instrumentation doesn't, and the only way to catch that is to go and check what the code is actually doing rather than trusting that a table exists for the reason its name implies.
