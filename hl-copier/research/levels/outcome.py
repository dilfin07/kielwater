#!/usr/bin/env python3
"""outcome.py — второй этап: что стало с теми, кого нашёл scan.py.

scan.py отвечает на вопрос «кто входил от уровня». Но упорный и правый — не одно и то
же: можно методично шортить зону шесть заходов подряд и всё это время терять. Здесь
меряем ИСХОД: сколько реализовано по монете за период, держит ли позицию сейчас и в
какую сторону, и сводим это в вердикт.

Считаем только по найденным адресам (их единицы), поэтому запросов мало — этап дешёвый.

Пример:
  python3 outcome.py --hits /tmp/btc_short_active.json --coin BTC --days 20
"""
import argparse
import json
import time

from scan import info, fills_window, _hms   # общий пейсер и загрузка сделок


def position_now(addr, coin):
    """Открытая позиция по монете сейчас: (размер со знаком, вход, uPnL)."""
    st = info({"type": "clearinghouseState", "user": addr}) or {}
    for ap in st.get("assetPositions", []):
        p = ap.get("position", {})
        if p.get("coin") == coin:
            return float(p.get("szi") or 0), float(p.get("entryPx") or 0), float(p.get("unrealizedPnl") or 0)
    return 0.0, 0.0, 0.0


def verdict(realized, szi, upnl, side):
    """Короткий вывод: закрыл в плюс / держит и прав / держит и не прав / закрыл в минус."""
    holding = abs(szi) > 1e-9
    aligned = (szi < 0) if side == "short" else (szi > 0)
    if not holding:
        return "закрыл в плюс" if realized > 0 else ("закрыл в минус" if realized < 0 else "вышел в ноль")
    if not aligned:
        return "развернулся"
    return "держит, в плюсе" if upnl > 0 else "держит, в минусе"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hits", required=True, help="json от scan.py (--out)")
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--side", choices=("short", "long"), default="short")
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    hits = json.load(open(a.hits))
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - a.days * 86400_000
    print("исход по %d адресам · %s · %d дней\n" % (len(hits), a.coin, a.days))

    rows = []
    t0 = time.time()
    for i, (addr, h) in enumerate(hits.items(), 1):
        try:
            fills = fills_window(addr, start_ms, end_ms)
            realized = sum(float(f.get("closedPnl") or 0) for f in fills if f.get("coin") == a.coin)
            fees = sum(float(f.get("fee") or 0) for f in fills if f.get("coin") == a.coin)
            szi, entry, upnl = position_now(addr, a.coin)
        except Exception as e:
            print("  ! %s: %s" % (addr[:10], e))
            continue
        rows.append({**h, "addr": addr, "realized": realized, "fees": fees,
                     "szi": szi, "entry_now": entry, "upnl": upnl,
                     "net": realized - fees + upnl,
                     "verdict": verdict(realized, szi, upnl, a.side)})
        print("  %d/%d  осталось ~%s" % (i, len(hits), _hms((time.time() - t0) / i * (len(hits) - i))),
              end="\r", flush=True)

    rows.sort(key=lambda r: -r["net"])
    print("\n")
    print("%-44s %-16s %12s %12s %12s %6s  %s" % (
        "адрес", "метка", "вход в зоне $", "реализовано", "итого с uPnL", "дней", "вердикт"))
    for r in rows:
        print("%-44s %-16s %12s %12s %12s %6d  %s" % (
            r["addr"], (r.get("label") or "")[:16], f"{r['usd']:,.0f}",
            f"{r['realized']:,.0f}", f"{r['net']:,.0f}", len(r.get("days") or []), r["verdict"]))

    good = [r for r in rows if r["net"] > 0]
    print("\nв плюсе: %d из %d" % (len(good), len(rows)))
    if a.out:
        json.dump(rows, open(a.out, "w"), ensure_ascii=False, indent=2, default=str)
        print("сохранено: %s" % a.out)


if __name__ == "__main__":
    main()
