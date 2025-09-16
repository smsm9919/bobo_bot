from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class Params:
    rsi_buy: float = 50.0
    rsi_sell: float = 50.0
    adx_min: float = 20.0
    price_range_min: float = 1.0
    spike_atr_mult: float = 1.8
    block_same_dir_minutes: int = 45
    min_tp_percent: float = 0.6

class Strategy:
    def __init__(self, p: Params = Params()):
        self.p = p

    def evaluate(self, s: Dict[str, Any]) -> Dict[str, Any]:
        reasons: List[str] = []
        ok = True
        side = None

        price = float(s["price"]); ema200 = float(s["ema200"]); rsi = float(s["rsi"]); adx = float(s["adx"])
        st = 1 if int(s.get("supertrend", 1)) > 0 else -1
        sma3, sma5, sma7 = float(s["sma3"]), float(s["sma5"]), float(s["sma7"])
        prange = float(s["range"]); atr = float(s["atr"])
        last_dir = s.get("last_direction"); mins_since = int(s.get("mins_since_last_trade", 9999))
        spike = bool(s.get("spike", False))

        if spike: ok=False; reasons.append(f"Spike>{self.p.spike_atr_mult}*ATR")
        if prange < self.p.price_range_min: ok=False; reasons.append(f"Range<{self.p.price_range_min}%")

        buy_ok = price > ema200 and rsi >= self.p.rsi_buy and adx >= self.p.adx_min and st > 0 and (sma3 > sma5 > sma7)
        sell_ok= price < ema200 and rsi <= self.p.rsi_sell and adx >= self.p.adx_min and st < 0 and (sma3 < sma5 < sma7)

        if last_dir and mins_since < self.p.block_same_dir_minutes:
            if (last_dir == "BUY" and buy_ok) or (last_dir == "SELL" and sell_ok):
                ok=False; reasons.append(f"SameDir<{self.p.block_same_dir_minutes}m")

        if ok and buy_ok: side="BUY"
        elif ok and sell_ok: side="SELL"
        else:
            reasons.append("Pattern not aligned")

        est_tp = (1.2*atr/price*100) if (atr>0 and price>0) else 0.0
        return {"enter": bool(side) and ok, "side": side, "reasons": reasons, "est_tp_percent": est_tp, "min_tp_percent": self.p.min_tp_percent}
