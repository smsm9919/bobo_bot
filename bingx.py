import time, hmac, hashlib, requests
from typing import Optional, Dict, Any

class BingX:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://open-api.bingx.com"):
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.base_url = base_url.rstrip("/")

    def _sign(self, params: Dict[str, Any]) -> str:
        qs = "&".join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(self.api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, data=None, timeout=20):
        url = f"{self.base_url}{endpoint}"
        headers = {"X-BX-APIKEY": self.api_key}
        p = dict(params or {})
        p["timestamp"] = str(int(time.time() * 1000))
        p["signature"] = self._sign(p)
        if method.upper() == "GET":
            r = requests.get(url, headers=headers, params=p, timeout=timeout)
        else:
            r = requests.post(url, headers=headers, params=p, json=data, timeout=timeout)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "text": r.text}
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "text": r.text}
        return {"ok": True, "json": j}

    def balance_usdt(self) -> float:
        res = self._request("GET", "/openApi/swap/v2/user/balance")
        if not res["ok"]:
            return 0.0
        j = res["json"]
        if j.get("code") != 0:
            return 0.0
        data = j.get("data", {})
        bal = data.get("balance")
        if isinstance(bal, list):
            for a in bal:
                if a.get("asset") == "USDT":
                    return float(a.get("availableBalance", 0.0))
        elif isinstance(bal, dict):
            if bal.get("asset") == "USDT":
                return float(bal.get("availableMargin", 0.0))
        return 0.0

    def klines(self, symbol: str, interval: str, limit: int = 200):
        return self._request("GET", "/openApi/swap/v2/quote/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    def positions(self, symbol: str):
        return self._request("GET", "/openApi/swap/v2/user/positions", {"symbol": symbol})

    def market_order(self, symbol: str, side: str, quantity: float):
        params = {"symbol": symbol, "side": side, "positionSide": "BOTH", "type": "MARKET", "quantity": quantity}
        return self._request("POST", "/openApi/swap/v2/trade/order", params)

    def tp_sl_order(self, symbol: str, side: str, order_type: str, quantity: float, stop_price: float, working_type: str = "MARK_PRICE"):
        params = {"symbol": symbol, "side": side, "positionSide": "BOTH", "type": order_type, "quantity": quantity, "stopPrice": f"{stop_price:.5f}", "workingType": working_type}
        return self._request("POST", "/openApi/swap/v2/trade/order", params)
