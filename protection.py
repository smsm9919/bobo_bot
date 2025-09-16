import time
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional

@dataclass
class GuardParams:
    spike_atr_mult_1bar: float = 2.2
    spike_pct_3bars: float = 3.5
    early_adverse_atr: float = 1.5
    early_window_min: int = 10
    trail_start_atr: float = 0.8
    trail_step_atr: float = 0.4
    session_max_loss_usdt: float = 5.0
    session_cooldown_min: int = 30

def pre_trade(state: Dict[str, Any], p: GuardParams) -> Tuple[bool, list]:
    reasons=[]; ok=True
    curr=float(state['price']); prev=float(state.get('prev', curr)); atr=float(state['atr'])
    if atr>0 and abs(curr-prev)>p.spike_atr_mult_1bar*atr:
        ok=False; reasons.append(f"1bar spike>{p.spike_atr_mult_1bar}*ATR")
    pct3=float(state.get('pct3',0.0))
    if abs(pct3)>p.spike_pct_3bars:
        ok=False; reasons.append(f"3bars move>{p.spike_pct_3bars}%")
    return ok,reasons

def post_fill(side:str, entry:float, price:float, atr:float, p:GuardParams):
    if atr<=0 or entry<=0: return None,None, None
    tp = round(entry + 1.2*atr,5) if side=="BUY" else round(entry - 1.2*atr,5)
    sl = round(entry - 0.8*atr,5) if side=="BUY" else round(entry + 0.8*atr,5)
    dyn={"enabled":True,"start_profit_atr":p.trail_start_atr,"step_atr":p.trail_step_atr,"last":None}
    return tp,sl,dyn

def trail(side, entry, price, atr, dyn)->Optional[float]:
    if not dyn or not dyn.get("enabled") or atr<=0: return None
    moved=(price-entry) if side=="BUY" else (entry-price)
    if moved < dyn["start_profit_atr"]*atr: return None
    step = dyn["step_atr"]*atr
    return round(price-step,5) if side=="BUY" else round(price+step,5)

def emergency(side, entry, price, atr, filled_ts, p:GuardParams)->bool:
    if not filled_ts or atr<=0: return False
    mins=(time.time()-filled_ts)/60
    if mins>p.early_window_min: return False
    adverse=(entry-price) if side=="BUY" else (price-entry)
    return adverse>p.early_adverse_atr*atr

class Circuit:
    def __init__(self, p:GuardParams):
        self.p=p; self.loss_acc=0.0; self.paused_until=0.0
    def on_close(self, pnl):
        self.loss_acc += min(0.0, pnl)
        if abs(self.loss_acc)>=self.p.session_max_loss_usdt:
            self.paused_until=time.time()+self.p.session_cooldown_min*60
    def can_trade(self)->bool: return time.time()>=self.paused_until
    def status(self): 
        import time as _t
        return {"loss_acc":round(self.loss_acc,4),"paused": _t.time()<self.paused_until}
