# Minimaler VWAP/RSI-Scalper (PAPER-MODUS)
import time, traceback, numpy as np, pandas as pd
import ccxt, os

EXCHANGE = os.getenv("EXCHANGE", "mexc")   # "mexc" oder "bitget"
SYMBOL   = os.getenv("SYMBOL", "BTC/USDT")
TF       = os.getenv("TF", "1m")
LOOKBACK = int(os.getenv("LOOKBACK", "200"))

# Paper/Live
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
API_KEY    = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")

# Fees & Risk
FEE_RT      = float(os.getenv("FEE_RT", "0.0010"))
SLIPPAGE_RT = float(os.getenv("SLIPPAGE_RT", "0.0006"))
GUARD       = FEE_RT + SLIPPAGE_RT + 0.0004
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
TP_OFFSET      = float(os.getenv("TP_OFFSET", "0.0040"))
SL_OFFSET      = float(os.getenv("SL_OFFSET", "0.0060"))
VWAP_WIN       = int(os.getenv("VWAP_WIN", "60"))
RSI_LEN        = int(os.getenv("RSI_LEN", "7"))
DD_MIN         = float(os.getenv("DD_MIN", "0.0025"))
COOLDOWN_SEC   = int(os.getenv("COOLDOWN_SEC", "60"))
MAX_HOLD_SEC   = int(os.getenv("MAX_HOLD_SEC", "1500"))
START_EQUITY   = float(os.getenv("START_EQUITY", "300"))

paper_equity = START_EQUITY
paper_pos = None
last_trade_ts = 0

def rsi(series, length=14):
    delta = series.diff()
    up = delta.clip(lower=0); down = (-delta).clip(lower=0)
    ma_up = up.ewm(com=length-1, adjust=False).mean()
    ma_down = down.ewm(com=length-1, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100/(1+rs))

def vwap(close, volume, win):
    pv = (close * volume).rolling(win).sum()
    v  = volume.rolling(win).sum().replace(0, np.nan)
    return pv / v

def get_ex():
    if EXCHANGE == "mexc":
        ex = ccxt.mexc({'enableRateLimit': True})
    elif EXCHANGE == "bitget":
        ex = ccxt.bitget({'enableRateLimit': True})
    else:
        raise ValueError("EXCHANGE muss 'mexc' oder 'bitget' sein.")
    if not PAPER_MODE:
        ex.apiKey = API_KEY; ex.secret = API_SECRET
    return ex

def fetch_ohlcv(ex):
    ohlcv = ex.fetch_ohlcv(SYMBOL, timeframe=TF, limit=LOOKBACK)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    return df

def desired_qty(price):
    global paper_equity
    risk_usdt = paper_equity * RISK_PER_TRADE
    sl_dist = price * SL_OFFSET
    if sl_dist <= 0: return 0.0
    return max(risk_usdt / sl_dist, 0.0001)

def paper_buy(price, qty):
    global paper_equity, paper_pos, last_trade_ts
    cost = price * qty; fee = cost * FEE_RT
    paper_equity -= (cost + fee)
    paper_pos = {"qty":qty, "entry":price, "t":time.time()}
    last_trade_ts = time.time()
    print(f"[PAPER] BUY {qty:.6f} @ {price:.2f} | equity {paper_equity:.2f}")

def paper_sell(price, qty):
    global paper_equity, paper_pos, last_trade_ts
    proceeds = price * qty; fee = proceeds * FEE_RT
    paper_equity += (proceeds - fee)
    print(f"[PAPER] SELL {qty:.6f} @ {price:.2f} | equity {paper_equity:.2f}")
    paper_pos = None; last_trade_ts = time.time()

def try_exit(price):
    global paper_pos
    if paper_pos is None: return
    entry = paper_pos["entry"]; age = time.time() - paper_pos["t"]
    ret = (price - entry) / entry
    net_tp = max(TP_OFFSET, GUARD + 0.0002)
    if ret >= net_tp or ret <= -SL_OFFSET or age >= MAX_HOLD_SEC:
        paper_sell(price, paper_pos["qty"])

def loop():
    ex = get_ex()
    print(f"== {EXCHANGE.upper()} {SYMBOL} {TF} | PAPER={PAPER_MODE} ==")
    global last_trade_ts
    while True:
        try:
            df = fetch_ohlcv(ex)
            if len(df) < VWAP_WIN + 5: time.sleep(2); continue
            price = float(df.iloc[-1, 4])
            df["RSI"] = rsi(df["close"], RSI_LEN)
            df["VWAP"] = vwap(df["close"], df["volume"], VWAP_WIN)
            rsi_now = float(df["RSI"].iloc[-1])
            vwap_now = float(df["VWAP"].iloc[-1])
            dd = (vwap_now - price) / vwap_now

            try_exit(price)

            # Cooldown
            if time.time() - last_trade_ts < COOLDOWN_SEC:
                time.sleep(2); continue

            should_long = (dd >= DD_MIN) and (rsi_now <= 32)
            if paper_pos is None and should_long:
                qty = desired_qty(price)
                if qty > 0:
                    if PAPER_MODE:
                        paper_buy(price, qty)
                    else:
                        # echte Order: ex.create_order(SYMBOL, 'market', 'buy', qty)
                        paper_buy(price, qty)  # fallback simulierter Log
                        print("[LIVE] Hier echte Order platzieren (auskommentierte Zeile).")
                    print(f"[SIGNAL] LONG | dd={dd*100:.2f}% rsi={rsi_now:.1f}")
        except Exception as e:
            print("ERR:", e); traceback.print_exc()
            time.sleep(3)
        time.sleep(2)

if __name__ == "__main__":
    print("Starte Bot… (Paper). Für Live ENV PAPER_MODE=false + API_KEY/SECRET setzen.")
    loop()
