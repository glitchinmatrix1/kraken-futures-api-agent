#!/usr/bin/env python3
"""
Kraken Futures Agent - No API key required
Run: python kraken_agent.py
Then open: http://localhost:8000
"""

import json, re, os, urllib.request, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

PORT = 8000
KRAKEN_BASE = "https://futures.kraken.com"

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,"january":1,"february":2,"march":3,"april":4,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
RESOLUTIONS = ["1w","1d","12h","4h","1h","30m","15m","5m","1m"]
RESOLUTION_S = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"12h":43200,"1d":86400,"1w":604800}
INTERVAL_S = RESOLUTION_S  # analytics endpoint uses same interval values in seconds

ANALYTICS_TYPES = [
    "open-interest","aggressor-differential","trade-volume","trade-count",
    "liquidation-volume","rolling-volatility","long-short-ratio","long-short-info",
    "cvd","top-traders","orderbook","spreads","liquidity","slippage",
    "future-basis","funding"
]
TICK_TYPES = {"trade":"trade","trades":"trade","mark":"mark","spot":"spot","index":"spot"}
LIVE_FIELDS = {
    # tickers - price
    "last price":("tickers","last"),"current price":("tickers","last"),"last":("tickers","last"),"price":("tickers","last"),
    "bid price":("tickers","bid"),"ask price":("tickers","ask"),"bid":("tickers","bid"),"ask":("tickers","ask"),
    "current mark price":("tickers","markPrice"),"mark price":("tickers","markPrice"),"mark":("tickers","markPrice"),
    "current index price":("tickers","indexPrice"),"index price":("tickers","indexPrice"),"index":("tickers","indexPrice"),
    # tickers - funding
    "predicted absolute funding rate":("tickers","fundingRatePrediction"),"predicted funding rate":("tickers","fundingRatePrediction"),"funding prediction":("tickers","fundingRatePrediction"),
    "current absolute funding rate":("tickers","fundingRate"),"funding rate":("tickers","fundingRate"),"funding":("tickers","fundingRate"),
    # tickers - volume/market
    "24hvol$":("tickers","vol24h"),"24h vol":("tickers","vol24h"),"vol24h":("tickers","vol24h"),"volume":("tickers","vol24h"),"vol":("tickers","vol24h"),
    "24hvolquote":("tickers","volumeQuote"),"volume quote":("tickers","volumeQuote"),"vol quote":("tickers","volumeQuote"),
    "open interest":("tickers","openInterest"),"oi":("tickers","openInterest"),
    "24h volume":("tickers","open24h"),"open24h":("tickers","open24h"),
    "24h high":("tickers","high24h"),"high24h":("tickers","high24h"),
    "24h low":("tickers","low24h"),"low24h":("tickers","low24h"),
    "24h vwap":("tickers","vwap24h"),"vwap":("tickers","vwap24h"),"vwap24h":("tickers","vwap24h"),
    "last trade size":("tickers","lastSize"),"last size":("tickers","lastSize"),"lastsize":("tickers","lastSize"),
    "24h change":("tickers","change24h"),"change":("tickers","change24h"),
    # instruments
    "impact mid size":("instruments","impactMidSize"),"impact mid":("instruments","impactMidSize"),
    "tick size":("instruments","tickSize"),
    "max position size":("instruments","maxPositionSize"),"max position":("instruments","maxPositionSize"),
    "contract trade precision":("instruments","contractValueTradePrecision"),"contract value trade precision":("instruments","contractValueTradePrecision"),
    "contract size":("instruments","contractSize"),
    "tradeable":("instruments","tradeable"),"tradable":("instruments","tradeable"),
    "margin":("instruments","marginLevels"),"opening date":("instruments","openingDate"),
}

def kraken_get(path, params=None):
    url = KRAKEN_BASE + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k,v in params.items())
    req = urllib.request.Request(url, headers={"User-Agent":"KrakenFuturesAgent/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def extract_symbol(t):
    m = re.search(r'\b(P[FI]_[A-Z]{3,8}USD[A-Z]?)\b', t.upper())
    return m.group(1) if m else None

def extract_resolution(t):
    tl = t.lower()
    for r in RESOLUTIONS:
        if re.search(r'\b'+re.escape(r)+r'\b', tl): return r
    if re.search(r'\b1[\s-]?min(ute)?\b',tl): return "1m"
    if re.search(r'\b5[\s-]?min(ute)?\b',tl): return "5m"
    if re.search(r'\b15[\s-]?min(ute)?\b',tl): return "15m"
    if re.search(r'\b30[\s-]?min(ute)?\b',tl): return "30m"
    if re.search(r'\b1[\s-]?hour\b',tl): return "1h"
    if re.search(r'\b4[\s-]?hour\b',tl): return "4h"
    if re.search(r'\b1[\s-]?day\b',tl): return "1d"
    if re.search(r'\b1[\s-]?week\b',tl): return "1w"
    return None

def extract_tick_type(t):
    tl = t.lower()
    # Don't match 'trade' if it's part of an analytics compound word
    for analytics in ANALYTICS_TYPES:
        tl = tl.replace(analytics, "")
        tl = tl.replace(analytics.replace("-", " "), "")
    for kw,tick in TICK_TYPES.items():
        if re.search(r'\b'+re.escape(kw)+r'\b', tl): return tick
    return None

def extract_analytics_type(t):
    tl = t.lower()
    for a in ANALYTICS_TYPES:
        if a in tl or a.replace("-"," ") in tl:
            return a
    return None

def extract_datetime(t):
    tl = t.lower()
    time_h, time_m = None, 0
    tm = re.search(r'\b(\d{1,2}):(\d{2})\s*(?:utc)?\b', tl)
    if tm: time_h,time_m = int(tm.group(1)),int(tm.group(2))
    else:
        am = re.search(r'\b(\d{1,2})\s*(am|pm)\b', tl)
        if am:
            time_h = int(am.group(1))
            if am.group(2)=="pm" and time_h!=12: time_h+=12
            elif am.group(2)=="am" and time_h==12: time_h=0
    ambiguous = time_h is None
    day=month=year=None
    # "1st of July 2025", "1 of July 2025", "1st July 2025", "1 July 2025"
    m1 = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+([a-z]+)\s+(\d{4})\b', tl)
    if m1: day,month_str,year = int(m1.group(1)),m1.group(2),int(m1.group(3)); month=MONTHS.get(month_str[:3])
    # "July 1st 2025", "July 1 2025"
    if not (day and month and year):
        m2 = re.search(r'\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})\b', tl)
        if m2: month_str,day,year = m2.group(1),int(m2.group(2)),int(m2.group(3)); month=MONTHS.get(month_str[:3])
    # "2025-07-01"
    if not (day and month and year):
        m3 = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', tl)
        if m3: year,month,day = int(m3.group(1)),int(m3.group(2)),int(m3.group(3))
    if not (day and month and year): return None, False
    try: return datetime(year,month,day,time_h or 0,time_m,0,tzinfo=timezone.utc), ambiguous
    except ValueError: return None, False

def is_candle(t):
    return any(k in t.lower() for k in ["candle","ohlc","chart"]) or extract_resolution(t) is not None

def find_field(t):
    tl = t.lower()
    for k in sorted(LIVE_FIELDS, key=len, reverse=True):
        if k in tl: return LIVE_FIELDS[k]
    return None

def fmt_val(key, val):
    if val is None: return "N/A"
    if isinstance(val, bool): return "yes" if val else "no"
    if isinstance(val, (int,float)):
        if "Rate" in key:
            pct = float(val) * 100
            return f"{pct:.10f}".rstrip("0").rstrip(".") + "%"
        if "change" in key.lower():
            return f"{float(val):.10f}".rstrip("0").rstrip(".") + "%"
        if key in ("last","bid","ask","markPrice","indexPrice"):
            from decimal import Decimal
            return "$" + format(Decimal(str(val)).normalize(), 'f')
        if any(x in key for x in ("Volume","Interest","vol","impactMid","maxPosition","contractSize")): return f"{float(val):,.2f}"
        from decimal import Decimal
        return format(Decimal(str(val)).normalize(), 'f')
    if isinstance(val, list): return json.dumps(val, indent=2)
    return str(val)

def process(text, hist):
    text = text.strip()

    # ── Tradeable contracts shortcut ──
    if re.search(r'\btradeable?\b|\btradable?\b', text.lower()) and not extract_symbol(text):
        try:
            d = kraken_get("/derivatives/api/v3/instruments")
            t = [i["symbol"] for i in d.get("instruments",[]) if i.get("tradeable")]
            return {"type":"answer","source":"instruments","text":f"{len(t)} tradeable contracts:\n"+", ".join(t)}
        except Exception as e: return {"type":"error","text":str(e)}

    # ── Analytics — always checked first so it wins over candle when explicitly named ──
    analytics_type = extract_analytics_type(text)
    if not analytics_type:
        for e in reversed(hist):
            if e.get("role") == "assistant":
                if e.get("type") == "clarify" and e.get("analytics_context"):
                    # mid-clarification — find type from user messages
                    for ue in hist:
                        if ue.get("role") == "user":
                            at = extract_analytics_type(ue.get("content",""))
                            if at:
                                analytics_type = at
                                break
                elif e.get("type") == "answer" and e.get("source","").startswith("analytics/"):
                    # only inherit if the current message looks like a follow-up analytics query
                    # (has a symbol + resolution/datetime but no live data field)
                    has_field = find_field(text) is not None
                    has_res = extract_resolution(text) is not None
                    has_dt = extract_datetime(text)[0] is not None
                    is_followup = not has_field and (has_res or has_dt)
                    if is_followup:
                        analytics_type = e.get("source","").replace("analytics/","")
                break
    # Also check if user is replying with just a symbol/now to a previous analytics clarify
    # by scanning all user messages since last completed answer
    if not analytics_type:
        snap_in_text = any(k in text.lower() for k in ("now","latest","snapshot"))
        sym_in_text = bool(extract_symbol(text))
        if snap_in_text or sym_in_text:
            for e in reversed(hist):
                if e.get("role") == "assistant" and e.get("type") in ("answer","candle"):
                    break
                if e.get("role") == "user":
                    at = extract_analytics_type(e.get("content",""))
                    if at:
                        analytics_type = at
                        break

    if analytics_type:
        sym = extract_symbol(text)
        res = extract_resolution(text)
        dt_from, amb_from = extract_datetime(text)
        snapshot = "now" in text.lower() or "latest" in text.lower() or "snapshot" in text.lower()
        for e in reversed(hist):
            if e.get("role") == "assistant":
                # stop at any completed answer — don't inherit dt from old requests
                if e.get("type") in ("answer","candle"): break
                # only inherit from active analytics clarification chain
                if not e.get("analytics_context"): break
            msg = e.get("content","")
            if not sym: sym = extract_symbol(msg)
            if not res: res = extract_resolution(msg)
            if not dt_from: dt_from, amb_from = extract_datetime(msg)
            if not snapshot and any(k in msg.lower() for k in ("now","latest","snapshot")): snapshot = True
        missing = []
        if not sym: missing.append("symbol (e.g. PF_ETHUSD)")
        if not res: missing.append("interval (e.g. 1m, 5m, 1h)")
        if not snapshot and not dt_from: missing.append("a 'since' datetime UTC including the year — e.g. '6 April 2026 15:00 UTC' (optionally add a second time for 'to'). Or say 'latest' for the most recent data point")
        elif not snapshot and amb_from: missing.append("a start time UTC (e.g. 15:00 UTC)")
        if missing:
            return {"type":"clarify","text":"Still need: "+" and ".join(missing)+".","analytics_context":True}
        import time as _time
        now_s = int(_time.time())
        params = {"interval": INTERVAL_S[res]}
        if snapshot:
            # Return only the latest bucket: since = now - one interval
            params["since"] = now_s - INTERVAL_S[res]
            params["to"] = now_s
        else:
            params["since"] = int(dt_from.timestamp())
            all_times = re.findall(r'\b(\d{1,2}):(\d{2})\s*(?:utc)?\b', text.lower())
            if len(all_times) >= 2:
                h2, m2 = int(all_times[1][0]), int(all_times[1][1])
                params["to"] = int(dt_from.replace(hour=h2, minute=m2).timestamp())
            else:
                params["to"] = params["since"] + 3600  # default to 1 hour window
        try:
            data = kraken_get(f"/api/charts/v1/analytics/{sym}/{analytics_type}", params)
            return {"type":"answer","source":f"analytics/{analytics_type}","text":json.dumps(data, indent=2)}
        except Exception as e:
            return {"type":"error","text":f"Analytics fetch failed: {e}"}

    # ── Candle (charts) — only if not mid-analytics clarification ──
    in_analytics_clarify = False
    for e in reversed(hist):
        if e.get("role") == "assistant":
            in_analytics_clarify = e.get("type") == "clarify" and e.get("analytics_context", False)
            break

    candle_mode = False if in_analytics_clarify else is_candle(text)
    if not candle_mode and not in_analytics_clarify:
        for e in reversed(hist):
            if e.get("role") == "assistant":
                if e.get("type") == "clarify" and e.get("candle_context"):
                    candle_mode = True
                break

    if candle_mode:
        sym=extract_symbol(text); res=extract_resolution(text); tt=extract_tick_type(text); dt,amb=extract_datetime(text)
        recent_hist = []
        for e in reversed(hist):
            if e.get("role") == "assistant" and e.get("type") in ("candle","answer"): break
            recent_hist.append(e)
        for e in recent_hist:
            msg=e.get("content","")
            if not sym: sym=extract_symbol(msg)
            if not res: res=extract_resolution(msg)
            if not tt: tt=extract_tick_type(msg)
            if not dt: dt,amb=extract_datetime(msg)
        missing=[]
        if not sym: missing.append("symbol (e.g. PF_ETHUSD)")
        if not res: missing.append("resolution (e.g. 1m, 5m, 1h)")
        if not tt: missing.append("tick type — trade, mark, or spot?")
        if not dt: missing.append("date and time UTC")
        elif amb: missing.append("time UTC (e.g. 14:00 UTC)")
        if missing: return {"type":"clarify","text":"Still need: "+" and ".join(missing)+".","candle_context":True}
        from_s=int(dt.timestamp()); to_s=from_s+RESOLUTION_S[res]
        try:
            d=kraken_get(f"/api/charts/v1/{tt}/{sym}/{res}",{"from":from_s,"to":to_s})
            candles=d.get("candles",[])
            if not candles: return {"type":"answer","source":f"charts/{tt}","text":f"No candle found for {sym} at that time."}
            return {"type":"candle","source":f"charts/{tt}","symbol":sym,"resolution":res,"tick_type":tt,"from_ms":from_s*1000,"candle":candles[0]}
        except Exception as e: return {"type":"error","text":f"Candle fetch failed: {e}"}

    # ── Live data (tickers / instruments) ──
    sym=extract_symbol(text); fi=find_field(text)
    # If field missing from current message, scan recent history (up to last answer) for it
    if not fi:
        for e in reversed(hist):
            if e.get("role") == "assistant" and e.get("type") in ("answer","candle"):
                break
            msg = e.get("content","")
            fi = find_field(msg)
            if fi: break
    if not sym and not fi: return {"type":"clarify","text":"Could you be more specific? Include a symbol (e.g. PF_ETHUSD) and what you'd like to know (e.g. mark price, funding rate)."}
    if not sym: return {"type":"clarify","text":"Which contract symbol? e.g. PF_ETHUSD, PF_XBTUSD"}
    src,field = fi if fi else ("tickers",None)
    try:
        if src=="tickers":
            d=kraken_get("/derivatives/api/v3/tickers")
            tickers={t["symbol"]:t for t in d.get("tickers",[])}
            tk=tickers.get(sym)
            if not tk: return {"type":"error","text":f"{sym} not found."}
            if field:
                val = tk.get(field)
                if field in ("fundingRate","fundingRatePrediction") and val is not None:
                    return {"type":"answer","source":"tickers","text":f"{field} for {sym}: {float(val):.18f}".rstrip("0").rstrip(".")}
                return {"type":"answer","source":"tickers","text":f"{field} for {sym}: {fmt_val(field,val)}"}
            lines=[f"  {f}: {fmt_val(f,tk.get(f))}" for f in ["last","bid","ask","markPrice","fundingRate","vol24h","openInterest","change24h"] if tk.get(f) is not None]
            return {"type":"answer","source":"tickers","text":f"{sym} summary:\n"+"\n".join(lines)}
        else:
            d=kraken_get("/derivatives/api/v3/instruments")
            instrs={i["symbol"]:i for i in d.get("instruments",[])}
            ins=instrs.get(sym)
            if not ins: return {"type":"error","text":f"{sym} not found."}
            if field: return {"type":"answer","source":"instruments","text":f"{field} for {sym}: {fmt_val(field,ins.get(field))}"}
            lines=[f"  {f}: {fmt_val(f,ins.get(f))}" for f in ["tickSize","contractSize","impactMidSize","maxPositionSize","tradeable"] if ins.get(f) is not None]
            return {"type":"answer","source":"instruments","text":f"{sym} details:\n"+"\n".join(lines)}
    except Exception as e: return {"type":"error","text":str(e)}

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/><title>Kraken Futures Agent</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap');
:root{--bg:#0d0d0f;--bg2:#141418;--bg3:#1c1c22;--border:rgba(255,255,255,0.08);--border2:rgba(255,255,255,0.14);--purple:#7c5cfc;--purple2:#9b82fd;--text:#e8e8f0;--text3:#555568;--mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:0 16px 100px}
.header{width:100%;max-width:720px;padding:28px 0 20px;display:flex;align-items:center;gap:12px;border-bottom:0.5px solid var(--border);margin-bottom:24px}
.logo{width:36px;height:36px;background:var(--purple);border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.logo svg{width:18px;height:18px;stroke:white;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.header-text h1{font-size:15px;font-weight:500}.header-text p{font-size:12px;color:var(--text3);margin-top:2px;font-family:var(--mono)}

.chip{font-size:11px;padding:4px 10px;border:0.5px solid var(--border2);border-radius:20px;cursor:pointer;color:var(--text3);background:transparent;font-family:var(--mono);transition:border-color .15s,color .15s}
.chip:hover{border-color:var(--purple);color:var(--purple2)}
.dropdowns{width:100%;max-width:720px;display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.dropdown{position:relative}
.dropdown-btn{font-size:11px;padding:4px 10px;border:0.5px solid var(--border2);border-radius:20px;cursor:pointer;color:var(--text3);background:transparent;font-family:var(--mono);display:flex;align-items:center;gap:5px;transition:border-color .15s,color .15s;white-space:nowrap}
.dropdown-btn:hover,.dropdown-btn.open{border-color:var(--purple);color:var(--purple2)}
.dropdown-btn svg{width:10px;height:10px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;transition:transform .2s}
.dropdown-btn.open svg{transform:rotate(180deg)}
.dropdown-menu{display:none;position:absolute;top:calc(100% + 6px);left:0;background:var(--bg2);border:0.5px solid var(--border2);border-radius:10px;padding:6px;min-width:220px;z-index:100;flex-direction:column;gap:2px}
.dropdown-menu.open{display:flex}
.dropdown-item{font-size:12px;padding:7px 10px;border-radius:6px;cursor:pointer;color:var(--text2);font-family:var(--mono);transition:background .1s,color .1s;white-space:nowrap}
.dropdown-item:hover{background:var(--bg3);color:var(--text)}
.messages{width:100%;max-width:720px;display:flex;flex-direction:column;gap:10px}
.msg{padding:12px 15px;border-radius:10px;font-size:14px;line-height:1.65}
.msg.user{background:var(--bg2);border:0.5px solid var(--border);align-self:flex-end;max-width:85%}
.msg.agent{background:var(--bg2);border:0.5px solid var(--border)}
.msg.clarify{background:var(--bg2);border:0.5px solid var(--purple)}
.msg.error{background:rgba(248,113,113,0.08);border:0.5px solid rgba(248,113,113,0.3);color:#f87171;font-size:13px;font-family:var(--mono)}
.ep-tag{display:inline-block;font-size:10px;padding:2px 7px;border-radius:4px;background:var(--bg3);border:0.5px solid var(--border2);color:var(--text3);margin-bottom:7px;font-family:var(--mono)}
.thinking{display:flex;align-items:center;gap:8px;padding:12px 15px;border-radius:10px;border:0.5px solid var(--border);font-size:13px;color:var(--text3);font-family:var(--mono)}
.dots span{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--purple);animation:bop 1.2s infinite;margin:0 1px}
.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}
@keyframes bop{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-4px)}}
.ohlc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;margin-top:10px}
.ohlc-cell{background:var(--bg3);border-radius:7px;padding:8px 11px}
.ohlc-label{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;font-family:var(--mono)}
.ohlc-val{font-size:14px;font-weight:500;font-family:var(--mono)}
.candle-header{font-size:12px;color:var(--text3);margin-bottom:6px;font-family:var(--mono)}
.input-area{position:fixed;bottom:0;left:0;right:0;background:linear-gradient(to top,var(--bg) 70%,transparent);padding:16px;display:flex;justify-content:center}
.input-row{width:100%;max-width:720px;display:flex;gap:8px;background:var(--bg2);border:0.5px solid var(--border2);border-radius:10px;padding:8px 8px 8px 14px;align-items:center}
.input-row:focus-within{border-color:var(--purple)}
#question{flex:1;background:transparent;border:none;outline:none;color:var(--text);font-family:var(--sans);font-size:14px}
#question::placeholder{color:var(--text3)}
#ask-btn{padding:7px 16px;font-size:13px;font-weight:500;background:var(--purple);color:white;border:none;border-radius:7px;cursor:pointer;font-family:var(--sans);white-space:nowrap}
#ask-btn:hover{background:#6b4de8}#ask-btn:disabled{opacity:0.4;cursor:not-allowed}
</style></head><body>
<div class="header"><div class="logo"><svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div><div class="header-text"><h1>Kraken Futures Agent</h1><p>no api key required · live data · historical candles</p></div></div>
<div class="dropdowns">
  <div class="dropdown" id="dd-tickers">
    <div class="dropdown-btn" onclick="toggleDD('dd-tickers')">Tickers <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
    <div class="dropdown-menu">
      <div class="dropdown-item" onclick="pick('dd-tickers','last price')">Last Price</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','current mark price')">Current Mark Price</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','current index price')">Current Index Price</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','vol24h')">24hVol$</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','volume quote')">24hVolQuote</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','open interest')">Open Interest</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','open24h')">24h Volume</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','high24h')">24h High</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','low24h')">24h Low</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','vwap24h')">24h VWAP</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','last trade size')">Last Trade Size</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','current absolute funding rate')">Current Absolute Funding Rate</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','predicted absolute funding rate')">Predicted Absolute Funding Rate</div>
      <div class="dropdown-item" onclick="pick('dd-tickers','24h change')">24h Change</div>
    </div>
  </div>
  <div class="dropdown" id="dd-instruments">
    <div class="dropdown-btn" onclick="toggleDD('dd-instruments')">Instruments <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
    <div class="dropdown-menu">
      <div class="dropdown-item" onclick="pick('dd-instruments','tick size')">Tick Size</div>
      <div class="dropdown-item" onclick="pick('dd-instruments','impact mid size')">Impact Mid</div>
      <div class="dropdown-item" onclick="pick('dd-instruments','max position size')">Max Position Size</div>
      <div class="dropdown-item" onclick="pick('dd-instruments','contract trade precision')">Contract Trade Precision</div>
    </div>
  </div>
  <div class="dropdown" id="dd-charts">
    <div class="dropdown-btn" onclick="toggleDD('dd-charts')">Charts <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
    <div class="dropdown-menu">
      <div class="dropdown-item" onclick="pick('dd-charts','candle')">Candle</div>
      <div class="dropdown-item" onclick="pick('dd-charts','What contracts are currently tradeable?')">Tradeable Contracts</div>
    </div>
  </div>
  <div class="dropdown" id="dd-analytics">
    <div class="dropdown-btn" onclick="toggleDD('dd-analytics')">Analytics <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
    <div class="dropdown-menu">
      <div class="dropdown-item" onclick="pick('dd-analytics','open-interest')">Open Interest</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','aggressor-differential')">Aggressor Differential</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','trade-volume')">Trade Volume</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','trade-count')">Trade Count</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','liquidation-volume')">Liquidation Volume</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','rolling-volatility')">Rolling Volatility</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','long-short-ratio')">Long Short Ratio</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','long-short-info')">Long Short Info</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','cvd')">CVD</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','top-traders')">Top Traders</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','orderbook')">Orderbook</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','spreads')">Spreads</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','liquidity')">Liquidity</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','slippage')">Slippage</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','future-basis')">Future Basis</div>
      <div class="dropdown-item" onclick="pick('dd-analytics','funding')">Funding</div>
    </div>
  </div>
</div>
<div class="messages" id="messages"></div>
<div class="input-area"><div class="input-row"><input id="question" type="text" placeholder="Ask anything, or reply to a clarifying question here..." onkeydown="if(event.key==='Enter')askFromInput()"/><button id="ask-btn" onclick="askFromInput()">Send ↗</button></div></div>
<script>
let history=[];
function toggleDD(id){
  const dd=document.getElementById(id);
  const btn=dd.querySelector('.dropdown-btn');
  const menu=dd.querySelector('.dropdown-menu');
  const isOpen=menu.classList.contains('open');
  // close all
  document.querySelectorAll('.dropdown-menu').forEach(m=>m.classList.remove('open'));
  document.querySelectorAll('.dropdown-btn').forEach(b=>b.classList.remove('open'));
  if(!isOpen){menu.classList.add('open');btn.classList.add('open');}
}
function pick(id,query){
  document.querySelectorAll('.dropdown-menu').forEach(m=>m.classList.remove('open'));
  document.querySelectorAll('.dropdown-btn').forEach(b=>b.classList.remove('open'));
  ask(query);
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.dropdown')){
    document.querySelectorAll('.dropdown-menu').forEach(m=>m.classList.remove('open'));
    document.querySelectorAll('.dropdown-btn').forEach(b=>b.classList.remove('open'));
  }
});
function addMsg(type,html,tag){const d=document.createElement('div');d.className='msg '+type;if(type==='user')d.textContent=html;else d.innerHTML=(tag?`<div class="ep-tag">${tag}</div>`:'')+`<div style="white-space:pre-wrap">${html}</div>`;document.getElementById('messages').appendChild(d);d.scrollIntoView({behavior:'smooth',block:'nearest'})}
function addThinking(){const d=document.createElement('div');d.className='thinking';d.innerHTML='<div class="dots"><span></span><span></span><span></span></div><span>fetching...</span>';document.getElementById('messages').appendChild(d);return d}
function renderCandle(r){const c=r.candle,o=parseFloat(c.open),h=parseFloat(c.high),l=parseFloat(c.low),cl=parseFloat(c.close),vol=c.volume?parseFloat(c.volume).toLocaleString(undefined,{maximumFractionDigits:2}):'—',chg=((cl-o)/o*100).toFixed(3),chgCol=cl>=o?'#4ade80':'#f87171',fmt=v=>'$'+parseFloat(v).toPrecision(12).replace(/\.?0+$/,''),dt=new Date(r.from_ms).toISOString().replace('T',' ').slice(0,16);return`<div class="candle-header">${r.symbol} · ${r.resolution} ${r.tick_type} · ${dt} UTC</div><div class="ohlc-grid"><div class="ohlc-cell"><div class="ohlc-label">open</div><div class="ohlc-val">${fmt(o)}</div></div><div class="ohlc-cell"><div class="ohlc-label">high</div><div class="ohlc-val" style="color:#4ade80">${fmt(h)}</div></div><div class="ohlc-cell"><div class="ohlc-label">low</div><div class="ohlc-val" style="color:#f87171">${fmt(l)}</div></div><div class="ohlc-cell"><div class="ohlc-label">close</div><div class="ohlc-val">${fmt(cl)}</div></div><div class="ohlc-cell"><div class="ohlc-label">change</div><div class="ohlc-val" style="color:${chgCol};font-size:13px">${cl>=o?'+':''}${chg}%</div></div><div class="ohlc-cell"><div class="ohlc-label">volume</div><div class="ohlc-val" style="font-size:12px">${vol}</div></div></div>`}
async function ask(q){if(!q.trim())return;const btn=document.getElementById('ask-btn');document.getElementById('question').value='';btn.disabled=true;addMsg('user',q);const th=addThinking();try{const res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history})});const r=await res.json();th.remove();history.push({role:'user',content:q});history.push({role:'assistant',type:r.type,content:r.text||'',source:r.source||''});if(r.type==='candle')addMsg('agent',renderCandle(r),`→ ${r.source}`);else if(r.type==='clarify')addMsg('clarify',r.text);else if(r.type==='answer')addMsg('agent',r.text,r.source?`→ ${r.source}`:null);else if(r.type==='error')addMsg('error',r.text)}catch(e){th.remove();addMsg('error',e.message)}finally{btn.disabled=false;document.getElementById('question').focus()}}
function askFromInput(){const v=document.getElementById('question').value.trim();if(v)ask(v)}
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): print(f"  {args[0]} {args[1]}")
    def send_json(self,code,data):
        body=json.dumps(data).encode()
        self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",len(body));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path in ("/","/index.html"):
            body=HTML.encode();self.send_response(200);self.send_header("Content-Type","text/html");self.send_header("Content-Length",len(body));self.end_headers();self.wfile.write(body)
        else: self.send_json(404,{"error":"not found"})
    def do_POST(self):
        if self.path=="/ask":
            length=int(self.headers.get("Content-Length",0));body=json.loads(self.rfile.read(length))
            try: self.send_json(200,process(body.get("question",""),body.get("history",[])))
            except Exception as e: self.send_json(500,{"type":"error","text":str(e)})
        else: self.send_json(404,{"error":"not found"})

if __name__=="__main__":
    PORT = int(os.environ.get("PORT", 8000))
    print(f"\n  Kraken Futures Agent\n  ────────────────────\n  No API key required.\n  Open: http://localhost:{PORT}\n")
    server=HTTPServer(("0.0.0.0",PORT),Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n  Stopped.")
