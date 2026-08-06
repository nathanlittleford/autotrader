# ============================================================
#  AutoTrader — agents/news.py
#  News agent — scans the web for recent news before trading
#  Uses Groq's built-in web search capability
# ============================================================

import json
import re
import os
import sys
from datetime import datetime, timezone
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config.settings import GROQ_API_KEY

try:
    from groq import Groq
except ImportError:
    print("⚠  groq not installed. Run: pip install groq")
    raise

client    = Groq(api_key=GROQ_API_KEY)
MODEL     = "llama-3.1-8b-instant"

# Company names for better search queries
TICKER_NAMES = {
    "META":    "Meta Platforms Facebook",
    "SOFI":    "SoFi Technologies",
    "JPM":     "JPMorgan Chase",
    "SHOP":    "Shopify",
    "BAC":     "Bank of America",
    "AXP":     "American Express",
    "NVDA":    "Nvidia",
    "PLTR":    "Palantir Technologies",
    "AVGO":    "Broadcom",
    "PFE":     "Pfizer",
    "MSFT":    "Microsoft",
    "EBAY":    "eBay",
    "MA":      "Mastercard",
    "UPS":     "UPS United Parcel Service",
    "T":       "AT&T",
    "PG":      "Procter Gamble",
    "PEP":     "PepsiCo",
    "DIS":     "Disney",
    "COP":     "ConocoPhillips",
    "AAPL":    "Apple",
    "GOOGL":   "Alphabet Google",
    "AMZN":    "Amazon",
    "TSLA":    "Tesla",
    "AMD":     "AMD Advanced Micro Devices",
    "INTC":    "Intel",
    "NFLX":    "Netflix",
    "GS":      "Goldman Sachs",
    "MS":      "Morgan Stanley",
    "BTC-USD": "Bitcoin cryptocurrency",
    "ETH-USD": "Ethereum cryptocurrency",
    "SOL-USD": "Solana cryptocurrency",
    "XRP-USD": "XRP Ripple cryptocurrency",
    "ADA-USD": "Cardano cryptocurrency",
    "LTC-USD": "Litecoin cryptocurrency",
    "NEAR-USD":"NEAR Protocol cryptocurrency",
    "INJ-USD": "Injective cryptocurrency",
}


def run_news_agent(ticker: str) -> dict:
    """
    Searches for recent news about a ticker and returns a risk assessment.
    Returns dict with: sentiment, risk_level, key_headlines, trade_impact
    """
    company = TICKER_NAMES.get(ticker, ticker)
    is_crypto = "-USD" in ticker

    system = """You are a financial news analyst. Your job is to assess whether recent news 
about a company or asset makes it risky to trade right now.

Be concise and specific. Focus on news from the last 48 hours that could move the price.

Respond ONLY in valid JSON:
{
  "sentiment": "bullish or bearish or neutral",
  "risk_level": "low or medium or high or critical",
  "key_headlines": ["headline 1", "headline 2"],
  "trade_impact": "one sentence on how this affects a BUY or SELL decision",
  "avoid_trade": true or false
}

Set avoid_trade to true if:
- Major negative news (CEO leaving, fraud, bankruptcy, crash, hack, ban)
- Earnings announcement in next 24 hours
- Major regulatory action
- Crypto exchange hack or major protocol issue
- Market-wide crash in progress"""

    asset_type = "cryptocurrency" if is_crypto else "stock"
    user = f"""Search for the latest news about {company} ({ticker}) in the last 48 hours.

What has happened recently that could affect the {asset_type} price?
Are there any major announcements, scandals, regulatory issues, or market events?
Is there any reason to avoid trading {ticker} right now?"""

    try:
        # Use Groq — fallback to Ollama if rate limited
        try:
          _model = "llama-3.1-8b-instant"
        except:
          _model = "llama-3.1-8b-instant"
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for recent news",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"}
                        },
                        "required": ["query"]
                    }
                }
            }],
            temperature=0.1,
            max_tokens=600,
        )

        raw = response.choices[0].message.content or ""

        # Parse JSON from response
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            result = {
                "sentiment":    "neutral",
                "risk_level":   "low",
                "key_headlines": [],
                "trade_impact": "No significant news found.",
                "avoid_trade":  False,
            }

    except Exception as e:
        # If news search fails, return neutral — don't block the trade
        result = {
            "sentiment":    "neutral",
            "risk_level":   "low",
            "key_headlines": [],
            "trade_impact": f"News search unavailable: {str(e)[:50]}",
            "avoid_trade":  False,
        }

    return result


if __name__ == "__main__":
    print("Testing news agent on TSLA...")
    result = run_news_agent("TSLA")
    print(json.dumps(result, indent=2))

    print("\nTesting news agent on BTC-USD...")
    result = run_news_agent("BTC-USD")
    print(json.dumps(result, indent=2))
