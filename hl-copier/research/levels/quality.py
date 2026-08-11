#!/usr/bin/env python3
"""quality.py — отсеять из улова scan.py тех, кто торгует прилично.

scan.py находит, КТО входил от уровня. Здесь отвечаем, СТОИТ ЛИ на него смотреть:
кривая PnL растёт, сейчас не в глубокой просадке, профит-фактор больше единицы,
позиции держатся достаточно долго, чтобы копир вообще успевал повторять.

Метрики не свои — переиспользуем profile_address из research/hunter/hunt.py, чтобы
цифры были те же, что в остальном ресёрче (кривая берётся из portfolio, просадка
считается от пика, underwater = ниже пика больше чем на 10%).

Темп запросов намеренно вдвое медленнее обычного: у бота на Pi общий с нами внешний
IP, и на полной скорости он ловит 429 по вебсокету.

  python3 quality.py --hits /tmp/btc_short_active.json --workers 6
"""
import argparse
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HUNTER = os.path.join(HERE, "..", "hunter")
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))   # hl-copier/
sys.path.insert(0, os.path.abspath(HUNTER))

from copier.hl import rest                                    # noqa: E402
from copier.hl.rest import HLInfo, MAINNET                    # noqa: E402
from hunt import profile_address                              # noqa: E402
from scan import _bar, _hms                                   # noqa: E402


def sharpe(curve):
    """Шарп по кривой pnlHistory: разности соседних точек — это доход за период.

    hunt.py шарп не считает, а он тут ключевой: profit_factor и PnL показывают, ЧТО
    заработано, но не КАК. Отрицательный шарп при плюсовом итоге означает, что плюс
    держится на одной удачной сделке, а остальное время счёт болтает.

    Годовая нормировка — по фактическому шагу кривой (обычно сутки)."""
    if not curve or len(curve) < 8:
        return {"sharpe": None, "curve_pts": len(curve or [])}
    vals = [v for _t, v in curve]
    dl = [b - a for a, b in zip(vals, vals[1:])]
    n = len(dl)
    mean = sum(dl) / n
    var = sum((x - mean) ** 2 for x in dl) / (n - 1) if n > 1 else 0.0
    sd = var ** 0.5
    if sd <= 0:
        return {"sharpe": None, "curve_pts": len(curve)}
    step_ms = (curve[-1][0] - curve[0][0]) / max(n, 1)
    per_year = (365 * 86400_000 / step_ms) if step_ms > 0 else 365
    return {"sharpe": round(mean / sd * (per_year ** 0.5), 2),
            "sharpe_raw": round(mean / sd, 3), "curve_pts": len(curve)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hits", required=True, help="json от scan.py")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pace", type=float, default=0.30, help="сек между запросами (бот делит с нами IP)")
    ap.add_argument("--min-days", type=int, default=0, help="брать только с N+ днями входов в зоне")
    ap.add_argument("--out", default="/tmp/zone_quality.json")
    ap.add_argument("--resume", action="store_true",
                    help="дочитать только тех, у кого прошлый прогон упал на 429")
    a = ap.parse_args()

    rest._MIN_INTERVAL = a.pace                               # уступаем дорогу боту
    hits = json.load(open(a.hits))
    addrs = [(k, v) for k, v in hits.items() if len(v.get("days") or []) >= a.min_days]

    done_before = {}
    if a.resume and os.path.exists(a.out):
        done_before = json.load(open(a.out))
        # готовым считаем только полностью измеренного: без ошибок и с кривой
        ready = {k for k, r in done_before.items()
                 if not (r.get("err") or r.get("pf_err") or r.get("snap_err")) and r.get("curve_pts")}
        addrs = [(k, v) for k, v in addrs if k not in ready]
        print("докачка: готово %d, осталось %d" % (len(ready), len(addrs)), file=sys.stderr)
    print("профилирую %d адресов, темп %.2fс/запрос" % (len(addrs), a.pace), file=sys.stderr)

    hl = HLInfo(MAINNET)
    out, done, lock = dict(done_before), [0], threading.Lock()
    total, t0 = len(addrs), time.time()
    if not total:
        print("нечего добирать", file=sys.stderr)
    tty = sys.stderr.isatty()
    queue, qlock = list(addrs), threading.Lock()

    def loop():
        while True:
            with qlock:
                if not queue:
                    return
                addr, hit = queue.pop()
            try:
                p = profile_address(hl, addr)
            except Exception as e:
                p = {"address": addr, "err": str(e)[:60]}
            p.update(sharpe(p.pop("curve", None)))            # кривую в отбор не тащим, берём из неё шарп
            with lock:
                out[addr] = {**p, "zone_usd": hit["usd"], "zone_days": len(hit.get("days") or []),
                             "zone_n": hit["n"], "label": hit.get("label")}
                done[0] += 1
                if tty:
                    sys.stderr.write(_bar(done[0], total, len(out), t0)); sys.stderr.flush()
                elif done[0] % 25 == 0:
                    print("  %d/%d" % (done[0], total), file=sys.stderr)

    ths = [threading.Thread(target=loop, daemon=True) for _ in range(a.workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    if tty:
        sys.stderr.write("\n")

    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1, default=str)

    # отбор: кривая в плюсе, не под водой, прибыль есть, держит дольше пары минут
    def ok(r):
        sh = r.get("sharpe")
        return (r.get("pnl_last") is not None and r["pnl_last"] > 0
                and not r.get("underwater")
                and sh is not None and sh > 0          # отрицательный шарп режем сразу
                and (r.get("profit_factor") or 0) > 1.0
                and (r.get("realized") or 0) > 0
                and r.get("copyable"))

    good = sorted([r for r in out.values() if ok(r)], key=lambda r: -(r.get("sharpe") or 0))
    print()
    print("ГОДНЫХ: %d из %d" % (len(good), len(out)))
    print()
    neg = sum(1 for r in out.values() if (r.get("sharpe") or 0) < 0)
    print("отсеяно по отрицательному шарпу: %d" % neg)
    print()
    print("%-44s %-13s %7s %11s %8s %7s %6s %8s %5s" % (
        "адрес", "метка", "шарп", "PnL кривой", "просад%", "PF", "винр%", "удерж", "дней"))
    for r in good[:40]:
        mh = r.get("median_hold_min")
        print("%-44s %-13s %7s %11s %7.1f%% %7s %6s %8s %5d" % (
            r["address"], (r.get("label") or "")[:13], r.get("sharpe"),
            f"{r.get('pnl_last', 0):,.0f}", r.get("cur_dd_pct") or 0,
            r.get("profit_factor"), r.get("win_rate"),
            _hms(mh * 60) if mh else "—", r["zone_days"]))
    print("\nсохранено: %s" % a.out)


if __name__ == "__main__":
    main()
