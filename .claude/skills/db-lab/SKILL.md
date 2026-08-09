---
name: db-lab
description: Step-by-step Postgres/pgvector fluency sessions against AutoTrader's data, via a free-tier managed provider (Supabase — no card required). User hand-writes all SQL; Claude reviews, checks column choices against real data, and executes once confirmed. Use when the user says "db-lab", "/db-lab", or wants to build Postgres/pgvector interview fluency using AutoTrader as the source schema.
---

# /db-lab — Postgres/pgvector fluency sessions

This is FDE (Forward Deployed Engineer) interview-prep work, built on top of
AutoTrader (`/Users/nathanlittleford/Downloads/autotrader`), a 5-agent LLM
paper trading system currently on SQLite (`autotrader.db`). The point is
fluency the user can defend in an interview, not a finished artifact — so
the mode of working matters as much as the output.

## Non-negotiable working mode

**The user writes every non-trivial line of SQL. Never generate DDL, DML, or
queries for them to paste in.** Point at what needs to be decided (a schema
to migrate, a type-mapping tradeoff, a query shape), let them write it, then
review. Exceptions are narrow and must be flagged explicitly when used:
single canonical incantations with zero design content (e.g.
`CREATE EXTENSION IF NOT EXISTS vector;`) can be handed over verbatim — say
so at the time, don't quietly do it.

When reviewing what they write:
- **Check real data, don't guess.** Before signing off on a column's
  precision/scale/type, query `autotrader.db` (or whatever source is in
  scope) for the actual min/max/distribution. AutoTrader trades small
  amounts of crypto (tickers like `ADA-USD`, `ARB-USD`) alongside anything
  else — sub-cent prices and multi-million share counts from cheap tokens
  are real, not edge cases to dismiss. A column sized against a guess
  instead of the real range is exactly the kind of thing that breaks on the
  first real insert — catch it before they run it, not after.
- **Distinguish sizing bugs from design tradeoffs.** "This will overflow on
  real data" is a correctness problem — say so plainly and expect a fix.
  "ENUM vs CHECK" or "NUMERIC vs DOUBLE PRECISION" are legitimate tradeoffs
  with a right answer for this context — ask them to justify the choice
  rather than mandating one, and note what they should be ready to explain
  if asked about it in an interview.
- **Confirm before running.** Never execute SQL that hasn't been reviewed
  and confirmed as the user's own. Once confirmed, running it via `psql` (a
  connection string, not authored SQL) is fine and saves round-trips.

## Environment

- Provider: Supabase free tier (email/GitHub signup, no card). If a project
  doesn't exist yet, walk the user through console clicks — never assume
  CLI/API access to their account. Console steps for a fresh project:
  supabase.com → Sign in with GitHub → New project → set name, DB password
  (must be saved, shown once), region → Free plan → Create.
- Connection: Supabase's **direct connection host is IPv6-only** on new
  projects and will fail to resolve on networks without IPv6 routing (a
  real, common gotcha, not a config mistake). Use the **pooler** connection
  string instead — check with `dig <host> +short` if unsure which resolves.
- Credentials: store the pooler connection string as `SUPABASE_DB_URL` in
  the project's `.env` (confirm `.env` is gitignored first — it is, but
  check). Never print the raw password back into chat once it's stored;
  read it out of `.env` for `psql` calls instead of retyping it.
- Local tooling: `psql` comes from Homebrew's `libpq`, which is keg-only —
  `brew install libpq && brew link --force libpq`, and add
  `/opt/homebrew/opt/libpq/bin` to `PATH` (persist in `~/.zshrc`, not just
  the session).

## Session shape

1. **Scope the session** — one bounded piece (a table migration, a
   pgvector concept, an indexing exercise), not an open-ended tour. Confirm
   scope and flag time/timeline tradeoffs before writing anything, matching
   however much time the user says they have.
2. **Provide the source schema and a decision cheat sheet**, not a target
   schema. For each column: what it is, what to think about, why (source
   type, real data range if relevant). Leave the actual type choice to them.
3. **Review each artifact as it comes in** — schema, sample inserts, toy
   pgvector tables, similarity queries. Verify against real data where it
   matters, run it once confirmed, show the result.
4. **Close the loop**: save the final, reviewed SQL into the repo (e.g.
   `db/schema.sql`, `db/pgvector_example.sql`) with header comments
   explaining the type-mapping decisions and why — this is portfolio
   material, it should be self-explanatory to someone reading it cold. Keep
   it documentation-only unless the user explicitly asks to wire it into
   live code (`main.py` stays on SQLite unless told otherwise).

## Out of scope by default

No ORMs, no migration frameworks (Alembic/Prisma/etc.) — raw SQL is the
point. No wiring into AutoTrader's live agents/`main.py`. No full historical
data migration (266+ rows) unless explicitly requested — a handful of real
sample rows is enough to prove a schema holds; bulk `COPY`/CSV migration is
a different, lower-fluency-value exercise the user can request separately if
wanted.
