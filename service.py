import os, time
import pandas as pd
from flask import Flask, jsonify
from threading import Thread
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

from lib.bingx import BingX
from strategies.balanced import Strategy, Params
from risk.protection import GuardParams, pre_trade, post_fill, trail, emergency, Circuit

API_KEY = os.getenv("BINGX_API_KEY","").strip()
API_SECRET = os.getenv("BINGX_API_SECRET","").strip()
SYMBOL = os.getenv("SYMBOL","DOGE-USDT")
INTERVAL = os.getenv("INTERVAL","15m")
LEVERAGE = int(os.getenv("LEVERAGE","10"))
TRADE_PORTION = float(os.getenv("TRADE_PORTION","0.60"))
MIN_ATR = float(os.getenv("MIN_ATR","0.001"))
COOLDOWN = int(os.getenv("COOLDOWN","600"))

position_open=False; position_side=None; entry_price=0.0; quantity=0.0
tp_price=0.0; sl_price=0.0; dyn_trail=None; filled_ts=None
compound_profit=0.0; total_trades=0; wins=0; losses=0
last_direction=None; last_trade_time=0

price=0.0; ema200=0.0; rsi=0.0; adx=0.0; atr_val=0.0; range_pct=0.0; st_dir=0; update_ts=""
app = Flask(__name__)

ex = BingX(API_KEY, API_SECRET)
strategy = Strategy(Params())
guards = GuardParams()
circuit = Circuit(guards)

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def adx_calc(df, period=14):
    high,low,close = df["high"],df["low"],df["close"]
    plus_dm = high.diff(); minus_dm = -low.diff()
    plus_dm[plus_dm<0]=0; minus_dm[minus_dm<0]=0
    tr = pd.concat([high-low,(high-close.shift(1)).abs(),(low-close.shift(1)).abs()],axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100*(plus_dm.ewm(alpha=1/period).mean()/atr)
    minus_di= 100*(minus_dm.ewm(alpha=1/period).mean()/atr)
    dx = (abs(plus_di-minus_di)/(plus_di+minus_di))*100
    return dx.ewm(alpha=1/period).mean()

def price_range(df, lookback=20):
    if len(df)<lookback: return 0.0
    recent=df["close"].iloc[-lookback:]; hi=recent.max(); lo=recent.min()
    return ((hi-lo)/lo*100) if lo>0 else 0.0

def loop():
    global price, ema200, rsi, adx, atr_val, range_pct, st_dir, update_ts
    global position_open, position_side, entry_price, quantity, tp_price, sl_price, dyn_trail, filled_ts
    global compound_profit, total_trades, wins, losses, last_direction, last_trade_time

    init_bal = ex.balance_usdt()
    if init_bal<=0: print("FATAL: balance not positive"); return

    while True:
        try:
            update_ts = time.strftime("%Y-%m-%d %H:%M:%S")
            kl = ex.klines(SYMBOL, INTERVAL)
            if not kl["ok"] or not kl["json"].get("data"): time.sleep(30); continue
            data = kl["json"]["data"]
            df = pd.DataFrame(data, columns=["ts","open","high","low","close","vol"])
            df[["open","high","low","close"]] = df[["open","high","low","close"]].astype(float)
            price = df["close"].iloc[-1]
            ema200 = ema(df["close"],200).iloc[-1]
            rsi = RSIIndicator(close=df["close"], window=14).rsi().iloc[-2]
            atr_series = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()
            atr_val = max(MIN_ATR, float(atr_series.iloc[-1]))
            adx = float(adx_calc(df).iloc[-1])
            ema20 = ema(df["close"],20).iloc[-1]
            st_dir = 1 if price > ema20 else -1
            range_pct = price_range(df)

            prev_close = df["close"].iloc[-2]
            spike = abs(price - prev_close) > 1.8*atr_val
            pct3 = float((df["close"].iloc[-1]-df["close"].iloc[-4]) / df["close"].iloc[-4]*100) if len(df)>=4 else 0.0

            bal = ex.balance_usdt()
            total_bal = init_bal + compound_profit
            trade_usdt = min(total_bal*TRADE_PORTION, bal)
            eff_usd = trade_usdt * LEVERAGE
            quantity = round(eff_usd / price, 2)

            mins_since = int((time.time()-last_trade_time)/60)
            state = {"price":price,"ema200":ema200,"rsi":rsi,"adx":adx,"supertrend":st_dir,
                     "sma3": df["close"].rolling(3).mean().iloc[-1],
                     "sma5": df["close"].rolling(5).mean().iloc[-1],
                     "sma7": df["close"].rolling(7).mean().iloc[-1],
                     "range":range_pct,"atr":atr_val,
                     "last_direction":last_direction,"mins_since_last_trade":mins_since,
                     "spike":spike}
            dec = strategy.evaluate(state)
            ok_pre, reasons_pre = pre_trade({"price":price,"prev":prev_close,"atr":atr_val,"pct3":pct3}, guards)

            print(f"[MKT] {update_ts} P={price:.5f} RSI={rsi:.2f} ADX={adx:.2f} ATR={atr_val:.5f} Range={range_pct:.2f}%")
            print(f"[DECISION] enter={dec['enter']} side={dec['side']} estTP~{dec['est_tp_percent']:.2f}% reasons={dec['reasons']}")
            print(f"[PROTECT][PRE] ok={ok_pre} reasons={reasons_pre}")

            if position_open:
                new_sl = trail(position_side, entry_price, price, atr_val, dyn_trail)
                if new_sl and ((position_side=='BUY' and new_sl>sl_price) or (position_side=='SELL' and new_sl<sl_price)):
                    sl_price = new_sl; print(f"[TRAIL] SL -> {sl_price:.5f}")
                if emergency(position_side, entry_price, price, atr_val, filled_ts, guards):
                    print("[EMERGENCY] early adverse -> close")
                    side_close = "SELL" if position_side=="BUY" else "BUY"
                    res = ex.market_order(SYMBOL, side_close, quantity)
                    if res["ok"] and res["json"].get("code")==0:
                        avg = float(res["json"]["data"].get("avgPrice") or price)
                        pnl = (avg-entry_price)*quantity if position_side=="BUY" else (entry_price-avg)*quantity
                        compound_profit += pnl; total_trades += 1
                        if pnl>=0: wins +=1
                        else: losses +=1
                        last_direction = position_side; position_open=False
                        print(f"[CLOSE] EMERGENCY pnl={pnl:.4f}")
                time.sleep(20); continue

            if dec["enter"] and ok_pre and circuit.can_trade():
                if dec["est_tp_percent"] < dec["min_tp_percent"]:
                    print(f"🚫 TP too small {dec['est_tp_percent']:.2f}%"); time.sleep(30); continue
                if time.time()-last_trade_time < COOLDOWN: 
                    print("[SKIP] cooldown"); time.sleep(30); continue
                res = ex.market_order(SYMBOL, dec["side"], quantity)
                if res["ok"] and res["json"].get("code")==0:
                    avg = float(res["json"]["data"].get("avgPrice") or price)
                    position_open=True; position_side=dec["side"]; entry_price=avg; filled_ts = time.time()
                    global tp_price, sl_price, dyn_trail
                    tp_price, sl_price, dyn_trail = post_fill(position_side, entry_price, price, atr_val, guards)
                    last_trade_time = time.time()
                    print(f"[OPEN] {position_side} @ {entry_price:.5f} TP={tp_price:.5f} SL={sl_price:.5f}")
                else:
                    print(f"❌ OPEN failed: {res}")
            time.sleep(30)
        except Exception as e:
            print(f"loop error: {e}"); time.sleep(30)

@app.route("/health")
def health():
    return jsonify({"ok": True, "position_open": position_open, "side": position_side})

@app.route("/metrics")
def metrics():
    return jsonify({
        "price": price, "ema200": ema200, "rsi": rsi, "adx": adx, "atr": atr_val,
        "range": range_pct, "st": st_dir, "compound_profit": compound_profit,
        "total_trades": total_trades, "wins": wins, "losses": losses, "ts": update_ts
    })

def run():
    t = Thread(target=loop, daemon=True); t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

from threading import Thread
if __name__ == "__main__":
    run()
