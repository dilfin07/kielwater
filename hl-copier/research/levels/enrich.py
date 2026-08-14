#!/usr/bin/env python3
"""enrich.py — дособрать по отобранным адресам всё для карточки-таблицы.

curvescan.py считает форму кривой, но для разбора этого мало: нужно видеть капитал,
что открыто прямо сейчас и как человек торгует — скальпер он или позиционщик. Здесь
на каждый адрес делается четыре запроса и собирается полный набор.

Стиль определяется по медианному удержанию позиции (FIFO по Open/Close в филлах):
до часа — скальпер, до восьми — интрадей, до трёх суток — свинг, дальше позиционный.
Это важнее, чем кажется: за скальпером копир с задержкой в минуты просто не успеет.

Окна кривой: неделя и месяц берутся готовыми рядами Hyperliquid, квартал и год
нарезаются из allTime по времени. Точки прореживаются до 48 на ряд — для спарклайна
хватает, а вес файла падает в разы.

  python3 enrich.py --src /tmp/curvescan_all.json --min-days 180 --workers 6
"""
import argparse
import json
import statistics
import sys
import threading
import time
from collections import defaultdict, deque

from scan import info, _bar

DAY = 86400_000


def thin(series, n=48):
    """Проредить ряд до n точек, сохранив первую и последнюю."""
    if len(series) <= n:
        return series
    step = len(series) / n
    out = [series[int(i * step)] for i in range(n)]
    out[-1] = series[-1]
    return out


def style_of(median_hold_min):
    if median_hold_min is None:
        return "—"
    h = median_hold_min / 60
    if h < 1:
        return "скальпер"
    if h < 8:
        return "интрадей"
    if h < 72:
        return "свинг"
    return "позиционный"


def collect(addr):
    now = int(time.time() * 1000)
    r = {"address": addr}

    pf = dict(info({"type": "portfolio", "user": addr}) or {})
    curves = {}
    for w in ("week", "month", "allTime"):
        c = [[int(t), float(v)] for t, v in ((pf.get(w) or {}).get("pnlHistory") or [])]
        if c:
            curves[w] = c
    all_c = curves.get("allTime") or []
    for name, days in (("quarter", 90), ("year", 365)):
        sl = [p for p in all_c if p[0] >= now - days * DAY]
        if len(sl) >= 3:
            base = sl[0][1]
            curves[name] = [[t, v - base] for t, v in sl]
    r["curves"] = {k: thin(v) for k, v in curves.items()}
    r["pnl"] = {k: round(v[-1][1] - v[0][1], 2) for k, v in curves.items()}
    acct = [[int(t), float(v)] for t, v in ((pf.get("allTime") or {}).get("accountValueHistory") or [])]
    r["acct_now"] = round(acct[-1][1], 2) if acct else 0

    st = info({"type": "clearinghouseState", "user": addr}) or {}
    ms = st.get("marginSummary", {})
    fl = lambda x: float(x or 0)
    r["perp"] = round(fl(ms.get("accountValue")), 2)
    r["ntl"] = round(fl(ms.get("totalNtlPos")), 2)
    mu = fl(ms.get("totalMarginUsed"))
    r["margin_ratio"] = round(mu / fl(ms.get("accountValue")) * 100, 1) if fl(ms.get("accountValue")) else 0
    r["free_margin"] = round(fl(ms.get("accountValue")) - mu, 2)
    poss = []
    for ap in st.get("assetPositions", []):
        p = ap.get("position", {})
        if fl(p.get("szi")) == 0:
            continue
        poss.append({"coin": p.get("coin"), "szi": fl(p.get("szi")),
                     "entry": fl(p.get("entryPx")), "upnl": round(fl(p.get("unrealizedPnl")), 2),
                     "lev": fl((p.get("leverage") or {}).get("value")),
                     "liq": fl(p.get("liquidationPx"))})
    r["positions"] = poss
    r["n_pos"] = len(poss)
    r["upnl"] = round(sum(p["upnl"] for p in poss), 2)

    sp = info({"type": "spotClearinghouseState", "user": addr}) or {}
    r["spot"] = round(sum(fl(b.get("total")) for b in sp.get("balances", [])
                          if b.get("coin") in ("USDC", "USDT")), 2)
    r["bank"] = round(r["perp"] + r["spot"], 2)
    r["basis"] = round(max(r["perp"], r["spot"]), 2)

    fills = sorted(info({"type": "userFills", "user": addr}) or [], key=lambda x: x.get("time", 0))
    r["n_fills"] = len(fills)
    if fills:
        span = max((fills[-1]["time"] - fills[0]["time"]) / DAY, 1e-9)
        r["fills_per_day"] = round(len(fills) / span, 1)
        r["taker"] = round(sum(1 for f in fills if f.get("crossed")) / len(fills), 2)
        r["coins"] = len({f.get("coin") for f in fills})
        r["last_trade"] = fills[-1]["time"]
        book, holds = defaultdict(deque), []
        for f in fills:
            d, coin, sz, tm = f.get("dir") or "", f.get("coin"), fl(f.get("sz")), f.get("time")
            if "Open" in d:
                book[coin].append([tm, sz])
            elif "Close" in d:
                rem = sz
                while rem > 1e-12 and book[coin]:
                    otm, osz = book[coin][0]
                    take = min(rem, osz)
                    holds.append((tm - otm) / 60000.0)
                    osz -= take; rem -= take
                    if osz <= 1e-12:
                        book[coin].popleft()
                    else:
                        book[coin][0][1] = osz
        r["median_hold_min"] = round(statistics.median(holds), 1) if holds else None
        r["round_trips"] = len(holds)
    r["style"] = style_of(r.get("median_hold_min"))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="json от curvescan.py")
    ap.add_argument("--min-days", type=int, default=180, help="минимальный возраст счёта")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="/tmp/enriched.json")
    a = ap.parse_args()

    src = json.load(open(a.src))
    sel = []
    for addr, r in src.items():
        A = r.get("allTime") or {}
        if (A.get("last", 0) > 0 and (A.get("sharpe") or 0) > 1 and (A.get("stability") or 0) >= 60
                and A.get("cur_dd_pct", 100) < 25 and (r.get("acct_now") or 0) >= 50000
                and r.get("vlm_week", 0) >= 200000 and A.get("span_days", 0) >= a.min_days):
            sel.append((addr, r))
    if a.limit:
        sel = sel[:a.limit]
    total, t0 = len(sel), time.time()
    print("обогащаю %d адресов (4 запроса на каждый)" % total, file=sys.stderr)

    out, done, lock = {}, [0], threading.Lock()
    tty = sys.stderr.isatty()
    q, qlock = list(sel), threading.Lock()

    def loop():
        while True:
            with qlock:
                if not q:
                    return
                addr, base = q.pop()
            try:
                r = collect(addr)
                r["curve_stats"] = {k: base.get(k) for k in ("allTime", "month", "week") if base.get(k)}
                r["vlm_week"] = base.get("vlm_week", 0)
                r["vlm_month"] = base.get("vlm_month", 0)
            except Exception as e:
                r = {"address": addr, "err": str(e)[:60]}
            with lock:
                out[addr] = r
                done[0] += 1
                if tty:
                    sys.stderr.write(_bar(done[0], total, len(out), t0)); sys.stderr.flush()
                elif done[0] % 20 == 0:
                    print("  %d/%d" % (done[0], total), file=sys.stderr)

    ths = [threading.Thread(target=loop, daemon=True) for _ in range(a.workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    if tty:
        sys.stderr.write("\n")

    json.dump(out, open(a.out, "w"), ensure_ascii=False)
    ok = [r for r in out.values() if not r.get("err")]
    print("собрано %d, ошибок %d → %s" % (len(ok), len(out) - len(ok), a.out))
    st = defaultdict(int)
    for r in ok:
        st[r.get("style", "—")] += 1
    print("стили:", dict(st))


if __name__ == "__main__":
    main()
