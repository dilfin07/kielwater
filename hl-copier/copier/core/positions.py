"""Разбор позиций/эквити из clearinghouseState. Чистые функции."""


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def account_value(ch_state):
    return f((ch_state or {}).get("marginSummary", {}).get("accountValue"))


STABLES = ("USDC", "USDT")


def spot_capital_usd(spot_state, coins=STABLES):
    """Весь стейбл-баланс спота в USD (USDC/USDT `total`, включая `hold`).

    Это ПОЛНЫЙ пул USDC цели в спот-леджере. Идёт в базу пропорции как
    `max(перп-эквити, spot_capital_usd)` — НЕ в сумму: спот-USDC у HL-трейдеров и есть
    перп-залог (одни деньги в двух видах; hold-спот == totalMarginUsed перпа), поэтому
    сумма = двойной счёт. max = общий баланс цели (подушка учтена), и плечо
    notional/max совпадает с Hyperdash (у него спот-холдинги = $0, весь USDC = капитал).
    """
    usd = 0.0
    for b in (spot_state or {}).get("balances", []):
        if b.get("coin") in coins:
            usd += f(b.get("total"))
    return usd


def net_positions(ch_state):
    """{coin: {szi, entryPx, lev, uPnl, posVal}}."""
    out = {}
    for ap in (ch_state or {}).get("assetPositions", []):
        p = ap.get("position", {})
        coin = p.get("coin")
        if not coin:
            continue
        out[coin] = {
            "szi": f(p.get("szi")),
            "entryPx": f(p.get("entryPx")),
            "lev": f(p.get("leverage", {}).get("value")),
            "uPnl": f(p.get("unrealizedPnl")),
            "posVal": f(p.get("positionValue")),
        }
    return out


def price_move_pct(side_sign, entry, mark):
    """% движения цены В ПОЛЬЗУ позиции от входа (насколько 'убежала' в плюс)."""
    if not entry:
        return 0.0
    if side_sign > 0:                       # long
        return (mark / entry - 1) * 100
    return (1 - mark / entry) * 100         # short


def reconstruct_positions(trades, symbol, start_pos=0.0, bot_ids=frozenset(), truncated=False):
    """Восстановить ИСТОРИЮ позиций по ленте сделок (чистая функция, без сети).

    Лента идёт по возрастанию времени. Позиция набирается неттингом; запись закрывается,
    когда нетто приходит в ноль.

    РАЗВОРОТ. Встречная сделка может быть больше текущей позиции: сидели в шорте 0.5,
    пришёл BUY 1.2 — позиция мгновенно становится лонгом 0.7, проскакивая ноль. Раньше
    условие «нетто == 0» в такой момент не срабатывало НИКОГДА, поэтому запись не
    закрывалась: сторона и время открытия оставались от самой первой сделки, и журнал
    показывал одну вечную позицию вместо нескольких. Теперь такая сделка режется на две
    части: закрывающую (в неё уходит реализованный PnL) и открывающую новую позицию.

    start_pos — позиция на начало ленты. Биржа отдаёт сделки ограниченным окном, поэтому
    нулём его считать нельзя: окно часто начинается посреди уже открытой позиции.
    truncated=True помечает первую запись как начатую до начала ленты (цена входа и время
    открытия по ней неполные).
    """
    out = []
    pos = float(start_pos)
    # объём, «унаследованный» от куска ленты до её начала: цена входа по нему неизвестна,
    # но в объём закрытия он входить обязан, иначе qty закрытой записи выйдет заниженным
    en_q = abs(pos)
    en_not = rpnl = comm = 0.0
    max_q = abs(pos)
    open_t = None
    side = "LONG" if pos > 0 else ("SHORT" if pos < 0 else None)
    bot_open = False
    first_is_truncated = truncated and abs(pos) > 1e-12
    last_t = None

    def _emit(status, price, close_t):
        cut = first_is_truncated and not out          # обрезана только самая первая запись
        out.append({
            "symbol": symbol, "side": side, "status": status,
            # у обрезанной записи часть объёма набрана до начала ленты — средняя входа неизвестна
            "entry": None if cut else (round(en_not / en_q, 5) if en_q else 0),
            "exit": round(price, 5) if price is not None else None,
            "qty": round(en_q if status == "closed" else abs(pos), 6),
            "max_qty": round(max_q, 6),
            "realizedPnl": round(rpnl, 2), "commission": round(comm, 4),
            "open_time": open_t, "close_time": close_t,
            "duration_min": round((close_t - open_t) / 60000) if (open_t and close_t) else None,
            "bot": bot_open,
            "truncated": cut,
        })

    for t in trades:
        q = float(t["qty"]); price = float(t["price"])
        signed = q if t["side"] == "BUY" else -q
        rp = float(t.get("realizedPnl", 0) or 0); cm = float(t.get("commission", 0) or 0)
        last_t = t["time"]

        if abs(pos) < 1e-12:                                    # открываем с нуля
            open_t = t["time"]; side = "LONG" if signed > 0 else "SHORT"
            en_q, en_not, rpnl, comm, pos = q, q * price, rp, cm, signed
            max_q = abs(pos)
            bot_open = str(t.get("orderId")) in bot_ids
            continue

        if (pos > 0) == (signed > 0):                           # добор в ту же сторону
            en_q += q; en_not += q * price; rpnl += rp; comm += cm
            pos += signed
            max_q = max(max_q, abs(pos))
            continue

        # встречная сделка: часть (или вся) закрывает позицию
        closing = min(q, abs(pos))
        rest = q - closing
        rpnl += rp                                              # PnL реализует именно закрытие
        comm += cm * (closing / q) if q else 0
        pos += closing if signed > 0 else -closing

        if abs(pos) > 1e-9:                                     # частичное сокращение — позиция жива
            continue

        _emit("closed", price, t["time"])                       # закрылась (в ноль или через разворот)
        en_q = en_not = rpnl = comm = max_q = 0.0
        open_t = None; side = None; bot_open = False; pos = 0.0

        if rest > 1e-12:                                        # остаток открывает встречную позицию
            open_t = t["time"]; side = "LONG" if signed > 0 else "SHORT"
            pos = rest if signed > 0 else -rest
            en_q, en_not = rest, rest * price
            rpnl, comm = 0.0, cm * (rest / q) if q else 0.0
            max_q = abs(pos)
            bot_open = str(t.get("orderId")) in bot_ids

    if abs(pos) > 1e-9 and abs(rpnl) > 1e-9:                    # ещё открыта, но PnL уже реализован
        _emit("partial", None, None)
        out[-1]["duration_min"] = round((last_t - open_t) / 60000) if (open_t and last_t) else None
    return out
