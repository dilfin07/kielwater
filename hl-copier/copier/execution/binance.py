"""Клиент Binance USDT-M Futures (подписанный REST, только stdlib).

Никаких зависимостей: urllib + hmac. Ключи передаются из .env (см. copier.secrets).
Testnet: https://testnet.binancefuture.com  |  Mainnet: https://fapi.binance.com
Эндпоинты одинаковые (/fapi/...).
"""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import urllib.error

MAINNET = "https://fapi.binance.com"
TESTNET = "https://testnet.binancefuture.com"

# Ретраи только транзиентных ошибок; постоянные (-2019 маржа, -1013 фильтр, -4xxx) — сразу наверх.
_RETRY_HTTP = {429, 418, 500, 502, 503, 504}          # rate-limit / IP-ban / серверные
_RETRY_BIN_CODES = ("-1003", "-1001", "-1007", "-1006", "-1000")  # too many req / disconnect / timeout / unknown
_MAX_RETRIES = 3
_BACKOFF_CAP = 8.0

# HL-монета -> Binance символ. Только НЕочевидные случаи; для остального — {BASE}USDT.
# HL kXXX = «1000× обёртка» → у Binance это 1000XXX.
SYMBOL_MAP = {
    "KPEPE": "1000PEPEUSDT", "KSHIB": "1000SHIBUSDT", "KBONK": "1000BONKUSDT",
    "KFLOKI": "1000FLOKIUSDT",
}


def to_symbol(hl_coin):
    """HL-монета -> Binance USDT-M символ (кандидат).

    Снимает билдер-декс префикс (`xyz:SPCX` -> `SPCX`), применяет карту исключений,
    иначе `{BASE}USDT`. Существование символа на бирже валидируется выше — по filters
    (см. executor): несуществующий кандидат там аккуратно отсеивается.
    """
    if not hl_coin:
        return None
    base = hl_coin.split(":")[-1].upper()       # xyz:SPCX -> SPCX
    return SYMBOL_MAP.get(base, base + "USDT")


class BinanceFutures:
    def __init__(self, api_key="", api_secret="", network="testnet", recv_window=10000, timeout=15):
        self.base = TESTNET if network == "testnet" else MAINNET
        self.key = api_key
        self.secret = api_secret.encode() if api_secret else b""
        self.recv_window = recv_window
        self.timeout = timeout
        self._time_offset = 0          # serverTime - локальное, мс (страховка от дрейфа часов)
        if api_key:
            try:
                self._sync_time()
            except Exception:
                pass

    def _sync_time(self):
        """Смещение локальных часов относительно сервера Binance (мс)."""
        t0 = time.time() * 1000
        sv = self._request("GET", "/fapi/v1/time")["serverTime"]
        t1 = time.time() * 1000
        self._time_offset = int(sv - (t0 + t1) / 2)
        return self._time_offset

    # ---- низкий уровень ----
    def _request(self, method, path, params=None, signed=False):
        """Подписанный/публичный запрос с лестницей ретраев транзиентных ошибок.
        timestamp/подпись пересобираются на каждой попытке (важно после задержек)."""
        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            p = dict(params or {})
            if signed:
                p["timestamp"] = int(time.time() * 1000 + self._time_offset)
                p["recvWindow"] = self.recv_window
                query = urllib.parse.urlencode(p)
                sig = hmac.new(self.secret, query.encode(), hashlib.sha256).hexdigest()
                query += "&signature=" + sig
            else:
                query = urllib.parse.urlencode(p)

            url = f"{self.base}{path}"
            headers = {}
            if self.key:
                headers["X-MBX-APIKEY"] = self.key
            if method == "GET":
                if query:
                    url += "?" + query
                data = None
            else:
                data = query.encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                if attempt >= _MAX_RETRIES:
                    raise RuntimeError(f"Binance {method} {path} -> HTTP {e.code}: {body}") from e
                # -1021: timestamp вне recvWindow — ресинк часов и повтор (без бэкоффа)
                if signed and "-1021" in body:
                    try:
                        self._sync_time()
                    except Exception:
                        pass
                    continue
                # транзиентные: rate-limit/ban/серверные/коды → бэкофф (с учётом Retry-After) и повтор
                if e.code in _RETRY_HTTP or any(c in body for c in _RETRY_BIN_CODES):
                    ra = e.headers.get("Retry-After") if e.headers else None
                    try:
                        delay = float(ra) if ra else min(2 ** attempt, _BACKOFF_CAP)
                    except (TypeError, ValueError):
                        delay = min(2 ** attempt, _BACKOFF_CAP)
                    time.sleep(delay)
                    continue
                # постоянная ошибка (-2019 маржа, -1013 фильтр, -4xxx и т.п.) — сразу наверх
                raise RuntimeError(f"Binance {method} {path} -> HTTP {e.code}: {body}") from e
            except urllib.error.URLError as e:
                last_err = e
                if attempt >= _MAX_RETRIES:
                    raise RuntimeError(f"Binance {method} {path} failed: {e}") from e
                time.sleep(min(2 ** attempt, _BACKOFF_CAP))   # сетевой сбой — повтор
        raise RuntimeError(f"Binance {method} {path} failed: {last_err}")

    # ---- публичные ----
    def ping(self):
        return self._request("GET", "/fapi/v1/ping")

    def exchange_info(self):
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def mark_prices(self):
        """{symbol: markPrice(float)} по всем символам."""
        data = self._request("GET", "/fapi/v1/premiumIndex")
        return {d["symbol"]: float(d["markPrice"]) for d in data}

    # ---- подписанные ----
    def account(self):
        return self._request("GET", "/fapi/v2/account", signed=True)

    def equity(self):
        """totalMarginBalance (баланс + нереализованный PnL), $."""
        return float(self.account().get("totalMarginBalance", 0))

    def position_mode(self):
        """True = Hedge (двусторонний), False = One-way."""
        r = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        return bool(r.get("dualSidePosition"))

    def positions(self):
        """{(symbol, positionSide): signed amt} для ненулевых — из /fapi/v2/positionRisk.

        Для реконсиляции движок использует positions_from_account(account()) — тот же счёт,
        но одним снимком и без лишнего тяжёлого запроса. Здесь оставлено для утилит и диагностики."""
        data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        out = {}
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                out[(p["symbol"], p.get("positionSide", "BOTH"))] = amt
        return out

    def open_orders_all(self):
        """Все открытые ордера (без символа)."""
        return self._request("GET", "/fapi/v1/openOrders", signed=True)

    def positions_detail(self):
        """Список открытых позиций с деталями для дашборда."""
        data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        out = []
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            out.append({
                "symbol": p["symbol"],
                "positionSide": p.get("positionSide", "BOTH"),
                "amt": amt,
                "entry": float(p.get("entryPrice", 0) or 0),
                "breakeven": float(p.get("breakEvenPrice", 0) or 0),
                "mark": float(p.get("markPrice", 0) or 0),
                "liq": float(p.get("liquidationPrice", 0) or 0),
                "uPnl": float(p.get("unRealizedProfit", 0) or 0),
                "leverage": int(float(p.get("leverage", 0) or 0)),
                "marginType": p.get("marginType", "cross"),
            })
        return out

    def funding_rates(self):
        """{symbol: lastFundingRate(float)} по всем символам (премиум-индекс)."""
        data = self._request("GET", "/fapi/v1/premiumIndex")
        return {d["symbol"]: float(d.get("lastFundingRate", 0) or 0) for d in data}

    def klines(self, symbol, interval="15m", limit=300):
        """Свечи (публичные): [[openTime,o,h,l,c,vol,closeTime,...], ...]."""
        return self._request("GET", "/fapi/v1/klines",
                             {"symbol": symbol, "interval": interval, "limit": limit})

    def user_trades(self, symbol, limit=200, start_ms=None, end_ms=None):
        """Наши сделки по символу (маркеры на графике, реконструкция истории позиций).

        БЕЗ диапазона Binance отдаёт только ПОСЛЕДНЮЮ НЕДЕЛЮ — этого не хватает, чтобы найти
        начало давно открытой позиции. С диапазоном окно тоже не длиннее недели, поэтому
        вглубь истории ходят шагами по неделе (см. _trades_back в server/_status.py)."""
        p = {"symbol": symbol, "limit": limit}
        if start_ms:
            p["startTime"] = int(start_ms)
        if end_ms:
            p["endTime"] = int(end_ms)
        return self._request("GET", "/fapi/v1/userTrades", p, signed=True)

    def income(self, start_ms, end_ms=None, income_type=None):
        """История доходов (REALIZED_PNL/FUNDING_FEE/COMMISSION/…) с пагинацией."""
        out, cur = [], int(start_ms)
        for _ in range(40):
            p = {"startTime": cur, "limit": 1000}
            if end_ms:
                p["endTime"] = int(end_ms)
            if income_type:
                p["incomeType"] = income_type
            batch = self._request("GET", "/fapi/v1/income", p, signed=True)
            if not batch:
                break
            out += batch
            if len(batch) < 1000:
                break
            cur = batch[-1]["time"] + 1
        return out

    def set_leverage(self, symbol, leverage):
        return self._request("POST", "/fapi/v1/leverage",
                             {"symbol": symbol, "leverage": int(leverage)}, signed=True)

    def market_order(self, symbol, side, quantity, reduce_only=False, position_side=None):
        params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt_num(quantity)}
        if position_side and position_side != "BOTH":
            params["positionSide"] = position_side      # hedge: reduceOnly НЕ передаём
        elif reduce_only:
            params["reduceOnly"] = "true"
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    # ---- мейкер-исполнение: лимитки/отмена/статус/стакан ----
    def book_ticker(self, symbol):
        """Лучший бид/аск: {bid, ask, bidQty, askQty}."""
        d = self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol})
        return {"bid": float(d["bidPrice"]), "ask": float(d["askPrice"]),
                "bidQty": float(d.get("bidQty", 0) or 0), "askQty": float(d.get("askQty", 0) or 0)}

    def limit_order(self, symbol, side, quantity, price, post_only=False, tif="GTC",
                    reduce_only=False, position_side=None, client_order_id=None):
        """LIMIT-ордер. post_only=True → timeInForce=GTX (только мейкер; пересёкший
        стакан ордер биржа отклонит кодом -5022)."""
        params = {"symbol": symbol, "side": side, "type": "LIMIT",
                  "quantity": fmt_num(quantity), "price": fmt_num(price),
                  "timeInForce": "GTX" if post_only else tif}
        if position_side and position_side != "BOTH":
            params["positionSide"] = position_side      # hedge: reduceOnly НЕ передаём
        elif reduce_only:
            params["reduceOnly"] = "true"
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def cancel_order(self, symbol, order_id=None, client_order_id=None):
        p = {"symbol": symbol}
        if order_id is not None:
            p["orderId"] = order_id
        elif client_order_id is not None:
            p["origClientOrderId"] = client_order_id
        else:
            raise ValueError("cancel_order: order_id or client_order_id required")
        return self._request("DELETE", "/fapi/v1/order", p, signed=True)

    def get_order(self, symbol, order_id=None, client_order_id=None):
        p = {"symbol": symbol}
        if order_id is not None:
            p["orderId"] = order_id
        elif client_order_id is not None:
            p["origClientOrderId"] = client_order_id
        else:
            raise ValueError("get_order: order_id or client_order_id required")
        return self._request("GET", "/fapi/v1/order", p, signed=True)


def positions_from_account(acct):
    """{(symbol, positionSide): signed amt} из ответа /fapi/v2/account.

    Движок и так дёргает account() на каждом тике (нужна equity/маржа), поэтому позиции
    берём оттуда же: один снимок — один момент времени, и на один тяжёлый запрос меньше
    (positionRisk без фильтра по символу отдаёт сотни записей)."""
    out = {}
    for p in (acct or {}).get("positions", []):
        amt = float(p.get("positionAmt", 0) or 0)
        if amt != 0:
            out[(p["symbol"], p.get("positionSide", "BOTH"))] = amt
    return out


def symbol_filters(exchange_info, only_trading=True):
    """{symbol: {stepSize, minQty, minNotional, qtyPrecision}}.

    only_trading: брать ТОЛЬКО символы со status="TRADING". Наличие символа в filters —
    это признак «можно торговать» (build_orders пропускает монету, если symbol не в filters).
    В exchangeInfo больше сотни символов в статусах SETTLING/PENDING_TRADING/CLOSE — по ним
    биржа отвергнет любой ордер. Раньше они попадали в filters, и бот молча слал заведомо
    провальные ордера (напр. LITUSDT в SETTLING)."""
    out = {}
    for s in exchange_info.get("symbols", []):
        if only_trading and s.get("status") != "TRADING":
            continue
        step = minq = 0.0
        minnotional = 0.0
        tick = 0.0
        for fl in s.get("filters", []):
            t = fl.get("filterType")
            if t == "LOT_SIZE":
                step = float(fl["stepSize"]); minq = float(fl["minQty"])
            elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                minnotional = float(fl.get("notional", fl.get("minNotional", 0)))
            elif t == "PRICE_FILTER":
                tick = float(fl.get("tickSize", 0) or 0)
        out[s["symbol"]] = {
            "stepSize": step, "minQty": minq, "minNotional": minnotional,
            "tickSize": tick, "qtyPrecision": s.get("quantityPrecision", 3),
            "pricePrecision": s.get("pricePrecision", 2),
        }
    return out


def fmt_num(x):
    """Число → строка без float-хвостов для тела ордера. 0.06999999999999999 → '0.07'.
    Защита от Binance -1111 «Precision is over the maximum»: даже если в qty/price просочился
    float-шум (сложение после round_step и т.п.), сюда он приходит и срезается до 8 знаков.
    Не-числа (уже строки/int) отдаём как есть."""
    if isinstance(x, bool) or not isinstance(x, float):
        return x
    s = f"{x:.8f}".rstrip("0").rstrip(".")
    return s or "0"


def round_step(qty, step):
    if step <= 0:
        return qty
    # Округление ВНИЗ к шагу лота. Эпсилон обязателен: 0.3/0.1 == 2.9999999999999996,
    # и без него int() срезал бы ЦЕЛЫЙ шаг (0.3 → 0.2). На закрытии это оставляло
    # остаток позиции, который потом уже меньше minQty и не закрывается никогда.
    n = int(qty / step + 1e-9)
    val = n * step
    # привести к точности шага (избежать float-хвостов)
    decimals = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
    return round(val, decimals)


def round_price(price, tick, side, maker=True):
    """Округлить цену к кратному tickSize.
    maker  — в сторону пассивности (BUY вниз / SELL вверх → лимитка не пересечёт стакан);
    taker  — в сторону пересечения (BUY вверх / SELL вниз → гарантированно возьмёт)."""
    import math
    if tick <= 0:
        return price
    n = price / tick
    if maker:
        n = math.floor(n) if side == "BUY" else math.ceil(n)
    else:
        n = math.ceil(n) if side == "BUY" else math.floor(n)
    decimals = max(0, len(f"{tick:.10f}".rstrip("0").split(".")[-1]))
    return round(n * tick, decimals)
