import os
from dotenv import load_dotenv
load_dotenv()
# ============================================================
#  AutoTrader — config/settings.py
#  Watchlist rebuilt from backtest data 2026-06-01
#  RSI thresholds adjusted: 40/65 instead of 35/70
# ============================================================

# --- Groq ---
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# --- Anthropic (optional upgrade later) ---
ANTHROPIC_API_KEY = "PASTE_YOUR_ANTHROPIC_KEY_HERE"

# --- Your Obsidian vault ---
OBSIDIAN_VAULT = "/Users/nathanlittleford/Documents/AI Brain/Claude AutoTrading"

# --- Paper trading capital ---
STARTING_CAPITAL = 10_000

# --- Risk rules ---
MAX_LOSS_PCT       = 0.03   # stop-loss at -3%
TARGET_GAIN_PCT    = 0.05   # take-profit at +5%
MAX_TRADES_PER_DAY = 15

# --- Tiered position sizing based on confidence ---
# Higher confidence = allowed to deploy more capital
POSITION_TIERS = {
    60: 0.05,    # 60-69% confidence → 5% of portfolio
    70: 0.075,   # 70-79% confidence → 7.5% of portfolio
    80: 0.10,    # 80-89% confidence → 10% of portfolio
    90: 0.15,    # 90%+ confidence   → 15% of portfolio (high conviction)
}

# --- Cash reserve rule ---
# Always keep this % of portfolio in cash
# Only 90%+ confidence trades can dip below this
CASH_RESERVE_PCT  = 0.20   # keep 20% as dry powder
HIGH_CONVICTION   = 90     # confidence needed to use reserve

# --- RSI thresholds (adjusted from backtest results) ---
# Wider thresholds catch more signals on S&P stocks
RSI_OVERSOLD   = 40   # was 35 — raised to catch more BUY signals
RSI_OVERBOUGHT = 65   # was 70 — lowered to catch more SELL signals

# --- Database ---
DB_PATH        = os.path.join(os.path.dirname(__file__), "..", "autotrader.db")
PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio.json")

# ============================================================
#  WATCHLIST — rebuilt from backtest data
#
#  KEPT in Tier 1 (profitable or mixed):
#  META 100% ✅ | SOFI 100% ✅ | SHOP 66% ✅ | BAC 66% ✅
#  AXP 62% ✅  | NVDA 60% ✅  | PLTR 57% ✅  | AVGO 57% ✅
#  PFE 66% ✅  | JPM 100% ✅  | EBAY 50% ⚠️  | MSFT 50% ⚠️
#  MA 50% ⚠️  | UPS 50% ⚠️  | T 50% ⚠️    | COP 40% ⚠️
#  DIS 40% ⚠️ | PG 50% ⚠️   | MRK 44% ⚠️  | PEP 50% ⚠️
#
#  MOVED to Tier 2 learn-only (consistent losers):
#  INTC -$1035 | AMD -$816 | QCOM -$321 | TXN -$345
#  UNH -$284  | SPY -$46  | QQQ -$80   | IWM -$90
#  GS -$200   | MS -$101  | JNJ -$187  | ABBV -$110
#  KO -$136   | WMT -$42  | COST -$95  | BA -$101
#  CAT -$227  | FDX -$110 | VZ -$55    | CMCSA -$60
#  V -$104    | BLK -$40  | XOM -$67   | CVX -$64
#  F -$105    | NFLX -$79 | AMZN -$85  | TSLA -$16
#  GOOGL -$213| AAPL -$0.27
# ============================================================

WATCHLIST = [

    # ----------------------------------------------------------
    #  TIER 1 — Profitable + mixed stocks (trade + learn)
    #  All verified profitable or borderline from backtest
    # ----------------------------------------------------------

    # 100% win rate from backtest
    {"ticker": "META",  "tier": 1, "label": "Meta"},
    {"ticker": "SOFI",  "tier": 2, "label": "SoFi"},
    {"ticker": "JPM",   "tier": 1, "label": "JPMorgan"},

    # 60-70% win rate
    {"ticker": "SHOP",  "tier": 2, "label": "Shopify"},
    {"ticker": "BAC",   "tier": 1, "label": "Bank of America"},
    {"ticker": "AXP",   "tier": 1, "label": "American Express"},
    {"ticker": "NVDA",  "tier": 1, "label": "Nvidia"},
    {"ticker": "PLTR",  "tier": 1, "label": "Palantir"},
    {"ticker": "AVGO",  "tier": 1, "label": "Broadcom"},
    {"ticker": "PFE",   "tier": 1, "label": "Pfizer"},

    # 50% win rate but positive P&L (mixed but leaning good)
    {"ticker": "MSFT",  "tier": 1, "label": "Microsoft"},
    {"ticker": "EBAY",  "tier": 2, "label": "eBay"},
    {"ticker": "MA",    "tier": 2, "label": "Mastercard"},
    {"ticker": "UPS",   "tier": 2, "label": "UPS"},
    {"ticker": "T",     "tier": 1, "label": "AT&T"},
    {"ticker": "PG",    "tier": 2, "label": "Procter & Gamble"},
    {"ticker": "PEP",   "tier": 2, "label": "PepsiCo"},
    {"ticker": "DIS",   "tier": 2, "label": "Disney"},
    {"ticker": "MRK",   "tier": 2, "label": "Merck"},  # demoted — chronic loser both with and without filters

    # ----------------------------------------------------------
    #  TIER 2 — Learn only (consistent losers from backtest)
    #  Full pipeline runs, lessons logged, NO orders placed
    # ----------------------------------------------------------

    # Backtest losers — keeping for learning data
    {"ticker": "COP", "tier": 2, "label": "ConocoPhillips — learn only"},
    {"ticker": "AAPL",  "tier": 2, "label": "Apple — learn only"},
    {"ticker": "GOOGL", "tier": 2, "label": "Alphabet — learn only"},
    {"ticker": "AMZN",  "tier": 2, "label": "Amazon — learn only"},
    {"ticker": "TSLA",  "tier": 2, "label": "Tesla — learn only"},
    {"ticker": "AMD",   "tier": 2, "label": "AMD — learn only"},
    {"ticker": "INTC",  "tier": 2, "label": "Intel — learn only"},
    {"ticker": "QCOM",  "tier": 2, "label": "Qualcomm — learn only"},
    {"ticker": "TXN",   "tier": 2, "label": "Texas Instruments — learn only"},
    {"ticker": "NFLX",  "tier": 2, "label": "Netflix — learn only"},
    {"ticker": "GS",    "tier": 2, "label": "Goldman Sachs — learn only"},
    {"ticker": "MS",    "tier": 2, "label": "Morgan Stanley — learn only"},
    {"ticker": "V",     "tier": 2, "label": "Visa — learn only"},
    {"ticker": "BLK",   "tier": 2, "label": "BlackRock — learn only"},
    {"ticker": "JNJ",   "tier": 2, "label": "J&J — learn only"},
    {"ticker": "ABBV",  "tier": 2, "label": "AbbVie — learn only"},
    {"ticker": "UNH",   "tier": 2, "label": "UnitedHealth — learn only"},
    {"ticker": "XOM",   "tier": 2, "label": "ExxonMobil — learn only"},
    {"ticker": "CVX",   "tier": 2, "label": "Chevron — learn only"},
    {"ticker": "KO",    "tier": 2, "label": "Coca-Cola — learn only"},
    {"ticker": "WMT",   "tier": 2, "label": "Walmart — learn only"},
    {"ticker": "COST",  "tier": 2, "label": "Costco — learn only"},
    {"ticker": "BA",    "tier": 2, "label": "Boeing — learn only"},
    {"ticker": "CAT",   "tier": 2, "label": "Caterpillar — learn only"},
    {"ticker": "FDX",   "tier": 2, "label": "FedEx — learn only"},
    {"ticker": "VZ",    "tier": 2, "label": "Verizon — learn only"},
    {"ticker": "CMCSA", "tier": 2, "label": "Comcast — learn only"},
    {"ticker": "F",     "tier": 2, "label": "Ford — learn only"},
    {"ticker": "SPY",   "tier": 2, "label": "S&P 500 ETF — learn only"},
    {"ticker": "QQQ",   "tier": 2, "label": "Nasdaq ETF — learn only"},
    {"ticker": "IWM",   "tier": 2, "label": "Russell 2000 ETF — learn only"},

    # High volatility training
    {"ticker": "GME",      "tier": 2, "label": "GameStop — learn only"},
    {"ticker": "AMC",      "tier": 2, "label": "AMC — learn only"},
    {"ticker": "RIVN",     "tier": 2, "label": "Rivian — learn only"},
    {"ticker": "LCID",     "tier": 2, "label": "Lucid — learn only"},

    # Crypto training
    {"ticker": "DOGE-USD", "tier": 2, "label": "Dogecoin — learn only"},
    {"ticker": "SHIB-USD", "tier": 2, "label": "Shiba Inu — learn only"},
    {"ticker": "WIF-USD",  "tier": 2, "label": "dogwifhat — learn only"},
    {"ticker": "FLOKI-USD","tier": 2, "label": "Floki — learn only"},

    # ----------------------------------------------------------
    #  TIER 3 — Crypto (trade + learn, scans 24/7)
    # ----------------------------------------------------------

    {"ticker": "BTC-USD",  "tier": 2, "label": "Bitcoin — learn only"},
    {"ticker": "ETH-USD",  "tier": 2, "label": "Ethereum — learn only"},
    {"ticker": "SOL-USD",  "tier": 3, "label": "Solana"},
    {"ticker": "BNB-USD",  "tier": 2, "label": "BNB — learn only"},
    {"ticker": "XRP-USD",  "tier": 3, "label": "XRP"},
    {"ticker": "ADA-USD",  "tier": 2, "label": "Cardano — learn only"},
    {"ticker": "AVAX-USD", "tier": 3, "label": "Avalanche"},
    {"ticker": "LINK-USD", "tier": 2, "label": "Chainlink"},
    {"ticker": "DOT-USD",  "tier": 3, "label": "Polkadot"},
    {"ticker": "LTC-USD",  "tier": 2, "label": "Litecoin — learn only"},
    {"ticker": "ATOM-USD", "tier": 3, "label": "Cosmos"},
    {"ticker": "NEAR-USD", "tier": 3, "label": "NEAR Protocol — learn only"},
    {"ticker": "ONDO-USD", "tier": 2, "label": "Ondo Finance — learn only"},
    {"ticker": "OP-USD",   "tier": 3, "label": "Optimism"},
    {"ticker": "INJ-USD",  "tier": 3, "label": "Injective — learn only"},
    {"ticker": "JUP-USD",  "tier": 3, "label": "Jupiter — learn only"},
    {"ticker": "WLD-USD",  "tier": 3, "label": "Worldcoin"},
    {"ticker": "FET-USD",  "tier": 3, "label": "Fetch.ai"},
    {"ticker": "HBAR-USD", "tier": 3, "label": "Hedera"},
    {"ticker": "MEME-USD", "tier": 2, "label": "Memecoin — learn only"},
]

# ----------------------------------------------------------
#  Helper functions
# ----------------------------------------------------------
def get_tier(tier_num: int) -> list:
    return [w for w in WATCHLIST if w["tier"] == tier_num]

def get_tradeable() -> list:
    return [w for w in WATCHLIST if w["tier"] in (1, 3)]

def get_learn_only() -> list:
    return [w for w in WATCHLIST if w["tier"] == 2]

def get_crypto() -> list:
    return [w for w in WATCHLIST if w["tier"] == 3]

def get_stocks() -> list:
    return [w for w in WATCHLIST if w["tier"] == 1]

TOTAL_TICKERS    = len(WATCHLIST)
TOTAL_TRADEABLE  = len(get_tradeable())
TOTAL_LEARN_ONLY = len(get_learn_only())
