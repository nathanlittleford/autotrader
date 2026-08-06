# ============================================================
#  AutoTrader — core/chart.py
#  Generates a proper HTML candlestick chart for Obsidian
#  Shows last 10 candles before trade entry
#  Obsidian renders HTML in notes natively
# ============================================================

import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    import yfinance as yf
except ImportError:
    print("⚠  yfinance not installed.")
    raise


def get_candle_data(ticker: str, num_candles: int = 12) -> list:
    """
    Fetches OHLC data for the last N candles.
    Returns list of dicts with open, high, low, close, volume, date.
    """
    data = yf.Ticker(ticker)
    hist = data.history(period="30d", interval="1d")

    if hist.empty:
        # Try hourly for crypto
        hist = data.history(period="5d", interval="1h")

    if hist.empty:
        return []

    candles = []
    for i, (date, row) in enumerate(hist.tail(num_candles).iterrows()):
        candles.append({
            "date":   str(date)[:10],
            "open":   round(float(row["Open"]),  6),
            "high":   round(float(row["High"]),  6),
            "low":    round(float(row["Low"]),   6),
            "close":  round(float(row["Close"]), 6),
            "volume": int(row["Volume"]),
            "bullish": float(row["Close"]) >= float(row["Open"]),
        })

    return candles


def analyse_candles(candles: list) -> dict:
    """Reads the candles and returns market context."""
    if not candles:
        return {}

    bullish_count = sum(1 for c in candles if c["bullish"])
    bearish_count = len(candles) - bullish_count

    # Overall trend — compare first half to second half closes
    mid       = len(candles) // 2
    first_avg = sum(c["close"] for c in candles[:mid]) / mid
    last_avg  = sum(c["close"] for c in candles[mid:]) / (len(candles) - mid)
    trending  = "BULLISH 📈" if last_avg > first_avg else "BEARISH 📉"

    # Last candle context
    last = candles[-1]
    body  = abs(last["close"] - last["open"])
    wick_upper = last["high"] - max(last["open"], last["close"])
    wick_lower = min(last["open"], last["close"]) - last["low"]

    if wick_lower > body * 1.5:
        last_signal = "Strong buyer rejection — long lower wick (bullish)"
    elif wick_upper > body * 1.5:
        last_signal = "Strong seller rejection — long upper wick (bearish)"
    elif last["bullish"] and body > (last["high"] - last["low"]) * 0.6:
        last_signal = "Strong bullish candle — large body, buyers in control"
    elif not last["bullish"] and body > (last["high"] - last["low"]) * 0.6:
        last_signal = "Strong bearish candle — large body, sellers in control"
    else:
        last_signal = "Indecision candle — small body, mixed signals"

    return {
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "trend":         trending,
        "last_signal":   last_signal,
        "price_range":   f"${min(c['low'] for c in candles):.4f} — ${max(c['high'] for c in candles):.4f}",
    }


def generate_html_chart(ticker: str, entry_price: float, direction: str, num_candles: int = 12) -> str:
    """
    Generates a full HTML candlestick chart for embedding in Obsidian.
    Returns the complete HTML string.
    """
    candles = get_candle_data(ticker, num_candles)
    if not candles:
        return "<p>⚠️ No candle data available for this ticker.</p>"

    analysis = analyse_candles(candles)

    # Chart dimensions
    chart_width  = 520
    chart_height = 280
    padding      = {"top": 30, "right": 20, "bottom": 40, "left": 65}
    plot_w = chart_width  - padding["left"] - padding["right"]
    plot_h = chart_height - padding["top"]  - padding["bottom"]

    # Price range with padding
    all_highs = [c["high"] for c in candles]
    all_lows  = [c["low"]  for c in candles]
    price_max = max(all_highs) * 1.005
    price_min = min(all_lows)  * 0.995
    price_rng = price_max - price_min

    def price_to_y(price):
        return padding["top"] + plot_h * (1 - (price - price_min) / price_rng)

    def idx_to_x(i):
        candle_w = plot_w / len(candles)
        return padding["left"] + (i + 0.5) * candle_w

    candle_width = (plot_w / len(candles)) * 0.6

    # Build candle SVG elements
    candle_svgs = []
    for i, c in enumerate(candles):
        x      = idx_to_x(i)
        is_last = i == len(candles) - 1
        color  = "#26a69a" if c["bullish"] else "#ef5350"
        border = "#26a69a" if c["bullish"] else "#ef5350"

        open_y  = price_to_y(c["open"])
        close_y = price_to_y(c["close"])
        high_y  = price_to_y(c["high"])
        low_y   = price_to_y(c["low"])

        body_y = min(open_y, close_y)
        body_h = max(abs(close_y - open_y), 1.5)

        # Highlight entry candle
        glow = f'filter="url(#glow)"' if is_last else ""

        candle_svgs.append(f'''
        <!-- Candle {i+1}: {c["date"]} -->
        <line x1="{x}" y1="{high_y}" x2="{x}" y2="{low_y}"
              stroke="{color}" stroke-width="1.5"/>
        <rect x="{x - candle_width/2}" y="{body_y}"
              width="{candle_width}" height="{body_h}"
              fill="{color}" stroke="{border}" stroke-width="0.5"
              rx="1" {glow}/>
        <title>{c["date"]} O:{c["open"]} H:{c["high"]} L:{c["low"]} C:{c["close"]}</title>
        ''')

    # Date labels (every 3rd)
    date_labels = []
    for i, c in enumerate(candles):
        if i % 3 == 0 or i == len(candles) - 1:
            x = idx_to_x(i)
            label = c["date"][5:]  # MM-DD
            date_labels.append(
                f'<text x="{x}" y="{chart_height - 8}" '
                f'fill="#888" font-size="9" text-anchor="middle">{label}</text>'
            )

    # Price grid lines and labels
    grid_lines = []
    num_grids  = 5
    for i in range(num_grids + 1):
        price = price_min + (price_rng * i / num_grids)
        y     = price_to_y(price)
        grid_lines.append(
            f'<line x1="{padding["left"]}" y1="{y}" '
            f'x2="{chart_width - padding["right"]}" y2="{y}" '
            f'stroke="#2a2a2a" stroke-width="0.5" stroke-dasharray="3,3"/>'
        )
        grid_lines.append(
            f'<text x="{padding["left"] - 5}" y="{y + 3}" '
            f'fill="#888" font-size="9" text-anchor="end">${price:.2f}</text>'
        )

    # Entry price line
    entry_y    = price_to_y(entry_price)
    entry_line = f'''
    <line x1="{padding["left"]}" y1="{entry_y}"
          x2="{chart_width - padding["right"]}" y2="{entry_y}"
          stroke="#f0b429" stroke-width="1" stroke-dasharray="4,3"/>
    <text x="{chart_width - padding["right"] + 2}" y="{entry_y + 3}"
          fill="#f0b429" font-size="9">entry</text>
    '''

    # Direction arrow on last candle
    last_x   = idx_to_x(len(candles) - 1)
    arrow_dir = "▲ BUY" if direction == "BUY" else "▼ SELL"
    arrow_col = "#26a69a" if direction == "BUY" else "#ef5350"
    arrow_y   = padding["top"] - 12 if direction == "SELL" else chart_height - padding["bottom"] + 20
    arrow_svg = f'<text x="{last_x}" y="{padding["top"] - 8}" fill="{arrow_col}" font-size="10" text-anchor="middle" font-weight="bold">{arrow_dir}</text>'

    trend_col  = "#26a69a" if "BULLISH" in analysis.get("trend","") else "#ef5350"
    bull_count = analysis.get("bullish_count", 0)
    bear_count = analysis.get("bearish_count", 0)
    trend      = analysis.get("trend", "—")
    last_sig   = analysis.get("last_signal", "—")
    p_range    = analysis.get("price_range", "—")

    html = f"""<div style="font-family:-apple-system,sans-serif;background:#131722;border-radius:12px;padding:16px;margin:12px 0;max-width:560px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <span style="color:#d1d4dc;font-size:13px;font-weight:600">{ticker} — Last {len(candles)} candles</span>
    <span style="color:{trend_col};font-size:12px;font-weight:500">{trend}</span>
  </div>
  <svg width="{chart_width}" height="{chart_height}" style="display:block">
    <defs>
      <filter id="glow">
        <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
        <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    {''.join(grid_lines)}
    {entry_line}
    {''.join(candle_svgs)}
    {''.join(date_labels)}
    {arrow_svg}
  </svg>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:10px">
    <div style="background:#1e222d;border-radius:8px;padding:8px;text-align:center">
      <div style="color:#26a69a;font-size:16px;font-weight:600">{bull_count}</div>
      <div style="color:#666;font-size:10px;margin-top:2px">Bullish candles</div>
    </div>
    <div style="background:#1e222d;border-radius:8px;padding:8px;text-align:center">
      <div style="color:#ef5350;font-size:16px;font-weight:600">{bear_count}</div>
      <div style="color:#666;font-size:10px;margin-top:2px">Bearish candles</div>
    </div>
    <div style="background:#1e222d;border-radius:8px;padding:8px;text-align:center">
      <div style="color:#f0b429;font-size:11px;font-weight:500">{p_range}</div>
      <div style="color:#666;font-size:10px;margin-top:2px">Price range</div>
    </div>
  </div>
  <div style="background:#1e222d;border-radius:8px;padding:10px;margin-top:8px">
    <div style="color:#888;font-size:10px;margin-bottom:3px">ENTRY CANDLE SIGNAL</div>
    <div style="color:#d1d4dc;font-size:12px">{last_sig}</div>
  </div>
</div>"""

    return html


if __name__ == "__main__":
    print("Testing chart generation for AAPL BUY...")
    html = generate_html_chart("AAPL", 212.50, "BUY")
    with open("/tmp/test_chart.html", "w") as f:
        f.write(f"<html><body style='background:#0d1117'>{html}</body></html>")
    print("✓ Chart written to /tmp/test_chart.html — open in browser to preview")
