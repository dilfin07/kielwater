#!/usr/bin/env python3
"""curvescan.py — отбор трейдеров по ФОРМЕ кривой, а не по прибыли.

Задача, ради которой писалось: на месячном окне кривая выглядит прилично, а отдаляешь —
человек сидит в минусе. Витрины показывают выгодное окно, поэтому смотреть надо все сразу
и сравнивать их между собой.

Один запрос portfolio на адрес отдаёт готовые ряды по четырём окнам (day/week/month/allTime),
и этого хватает на весь разбор — филлы и состояние счёта не нужны. Отсюда скорость:
весь лидерборд в 41 448 адресов проходится примерно за полтора часа, активные — за двадцать
минут. Для сравнения, quality.py делает три запроса на адрес и потому считает часами.

Что меряем:
  шарп        — по разностям кривой, годовая нормировка по фактическому шагу;
  просадка    — максимальная от пика и текущая (насколько ниже пика сидим сейчас);
  устойчивость— доля плюсовых отрезков, если побить историю на равные куски: отличает
                равномерный рост от одного удачного рывка;
  свежесть    — вклад последнего месяца в общий итог: ловит выдохшихся;
  ЛОВУШКА     — месяц в плюсе, а всё время в минусе. Ровно то, что видно только при отдалении.

  python3 curvescan.py --pool ../hunter/data/01_active.json --workers 8
"""
import argparse
import json
import sys
import threading
import time

from scan import info, _bar, _hms, load_pool


def curve_stats(curve, segments=10):
    """Метрики формы по ряду [[ts, cumulative_pnl], …]."""
    if not curve or len(curve) < 5:
        return None
    vals = [v for _t, v in curve]
    last, peak, trough = vals[-1], max(vals), min(vals)

    pk = vals[0]; maxdd = 0.0
    for v in vals:
        pk = max(pk, v)
        maxdd = max(maxdd, pk - v)
    denom = max(abs(peak), abs(last), 1.0)

    d = [b - a for a, b in zip(vals, vals[1:])]
    n = len(d)
    mean = sum(d) / n
    var = sum((x - mean) ** 2 for x in d) / (n - 1) if n > 1 else 0.0
    sd = var ** 0.5
    step_ms = (curve[-1][0] - curve[0][0]) / max(n, 1)
    per_year = (365 * 86400_000 / step_ms) if step_ms > 0 else 365
    sharpe = round(mean / sd * (per_year ** 0.5), 2) if sd > 0 else None

    # устойчивость: бьём на равные куски и считаем, сколько из них закрылись в плюс
    k = min(segments, max(2, n // 3))
    size = max(1, len(vals) // k)
    chunks = [vals[i:i + size + 1] for i in range(0, len(vals) - 1, size)]
    ups = sum(1 for c in chunks if len(c) > 1 and c[-1] > c[0])
    stability = round(ups / len(chunks) * 100) if chunks else None

    return {"last": round(last, 2), "peak": round(peak, 2), "trough": round(trough, 2),
            "max_dd": round(maxdd, 2), "max_dd_pct": round(maxdd / denom * 100, 1),
            "cur_dd_pct": round((peak - last) / denom * 100, 1),
            "sharpe": sharpe, "stability": stability, "points": len(curve),
            "span_days": round((curve[-1][0] - curve[0][0]) / 86400_000, 1)}


def profile(addr):
    pf = info({"type": "portfolio", "user": addr})
    if not pf:
        return None
    pf = dict(pf)
    out = {"address": addr}
    for w in ("allTime", "month", "week", "day"):
        block = pf.get(w) or {}
        cur = [[int(t), float(v)] for t, v in (block.get("pnlHistory") or [])]
        st = curve_stats(cur)
        if st:
            out[w] = st
        acct = [[int(t), float(v)] for t, v in (block.get("accountValueHistory") or [])]
        if w == "allTime" and acct:
            out["acct_now"] = round(acct[-1][1], 2)
            out["acct_peak"] = round(max(v for _t, v in acct), 2)
    return out


def verdict(r):
    """Короткий диагноз по расхождению окон."""
    a, mo = r.get("allTime"), r.get("month")
    if not a:
        return "нет данных"
    if mo and mo["last"] > 0 and a["last"] < 0:
        return "ЛОВУШКА: месяц в плюсе, всё время в минусе"
    if a["last"] < 0:
        return "в минусе за всё время"
    if mo and mo["last"] < 0:
        return "растёт исторически, но месяц минусовой"
    if a["cur_dd_pct"] > 25:
        return "глубоко под пиком"
    if (a.get("stability") or 0) >= 70 and (a.get("sharpe") or 0) > 1:
        return "ровный рост"
    return "плюс, но неровно"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-acct", type=float, default=10_000, help="отсечь мелкие счета")
    ap.add_argument("--min-vlm-week", type=float, default=100_000,
                    help="минимальный оборот за неделю: кривая дышит и у бездельника, оборот — нет")
    ap.add_argument("--min-vlm-month", type=float, default=500_000)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--out", default="/tmp/curvescan.json")
    a = ap.parse_args()

    pool = load_pool(a.pool)
    items = list(pool.items())
    if a.limit:
        items = items[:a.limit]
    total, t0 = len(items), time.time()
    print("кривые по %d адресам, %d потоков" % (total, a.workers), file=sys.stderr)

    out, done, lock = {}, [0], threading.Lock()
    tty = sys.stderr.isatty()
    queue, qlock = list(items), threading.Lock()

    def loop():
        while True:
            with qlock:
                if not queue:
                    return
                addr, meta = queue.pop()
            try:
                r = profile(addr)
            except Exception:
                r = None
            with lock:
                if r:
                    mt = meta or {}
                    r["meta_acct"] = mt.get("acct")
                    # обороты по окнам из лидерборда — единственный честный признак активности
                    for w in ("day", "week", "month", "allTime"):
                        r["vlm_" + w] = float((mt.get(w) or {}).get("vlm") or 0)
                    out[addr] = r
                done[0] += 1
                if tty:
                    sys.stderr.write(_bar(done[0], total, len(out), t0)); sys.stderr.flush()
                elif done[0] % 200 == 0:
                    print("  %d/%d" % (done[0], total), file=sys.stderr)

    ths = [threading.Thread(target=loop, daemon=True) for _ in range(a.workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    if tty:
        sys.stderr.write("\n")

    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)

    rows = [r for r in out.values() if r.get("allTime")]
    for r in rows:
        r["verdict"] = verdict(r)

    traps = [r for r in rows if r["verdict"].startswith("ЛОВУШКА")]
    idle = [r for r in rows if r.get("vlm_week", 0) < a.min_vlm_week
            and (r["allTime"].get("sharpe") or 0) > 1 and r["allTime"]["last"] > 0]
    good = [r for r in rows
            if r["allTime"]["last"] > 0
            and (r["allTime"].get("sharpe") or 0) > 1
            and (r["allTime"].get("stability") or 0) >= 60
            and r["allTime"]["cur_dd_pct"] < 25
            and (r.get("acct_now") or 0) >= a.min_acct
            and r.get("vlm_week", 0) >= a.min_vlm_week          # торгует на этой неделе
            and r.get("vlm_month", 0) >= a.min_vlm_month]
    good.sort(key=lambda r: -(r["allTime"].get("sharpe") or 0))

    print()
    print("измерено %d · подходящих %d · ловушек «месяц плюс / всё время минус» %d · с хорошей кривой, но простаивают %d" % (
        len(rows), len(good), len(traps), len(idle)))
    print()
    print("%-44s %11s %6s %6s %7s %11s %9s %11s" % (
        "адрес", "PnL всё", "шарп", "устойч", "просад", "PnL месяц", "счёт", "оборот/нед"))
    for r in good[:a.top]:
        A, M = r["allTime"], r.get("month") or {}
        print("%-44s %11s %6s %5s%% %6.1f%% %11s %9s %11s" % (
            r["address"], format(round(A["last"]), ",").replace(",", " "), A.get("sharpe"),
            A.get("stability"), A["cur_dd_pct"],
            format(round(M.get("last", 0)), ",").replace(",", " "),
            format(round(r.get("acct_now") or 0), ",").replace(",", " "),
            format(round(r.get("vlm_week", 0)), ",").replace(",", " ")))
    print("\nсохранено: %s" % a.out)


if __name__ == "__main__":
    main()
