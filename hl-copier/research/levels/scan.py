#!/usr/bin/env python3
"""scan.py — кто входил в позицию ОТ ЗАДАННОЙ ЦЕНОВОЙ ЗОНЫ.

Задача: есть уровень (квартальное значение, VAL/VAH, любой прямоугольник с графика) —
найти адреса, которые от него набирали шорт (или лонг) и делали это не разово.

ПОЧЕМУ ПЕРЕБОР, А НЕ ПОТОК. У Hyperliquid нет глобального поиска по сделкам: спросить
«кто торговал по цене X» не у кого, Info API отвечает только по конкретному адресу.
Живой поток (ws trades) видит всех, но лишь с момента подписки — прошлое им не достать.
Поэтому история = перебор пула, а поток = накопление на будущее.

ЗАПУСКАТЬ С НОУТА, НЕ С Pi: у копира общий на процесс пейсер запросов к HL, и лишняя
пачка чтений замедлит его торговый тик. Отдельная машина = отдельный IP и лимит.

Примеры:
  python3 scan.py --pool ../../../trader-watch/data/pool.json \\
                  --coin BTC --low 64750 --high 65500 --side short --days 20
  python3 scan.py --pool pool.json --coin ETH --low 1571 --high 1600 --side long --top 30
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request

INFO = "https://api.hyperliquid.xyz/info"
WEEK_MS = 7 * 24 * 3600 * 1000
_lock = threading.Lock()
_last = 0.0


def info(payload, pace=0.15, retries=4):
    """POST в Info API с ритмом и бэкоффом на 429 (лимит HL ~1200/мин на IP)."""
    global _last
    for attempt in range(retries):
        with _lock:
            wait = pace - (time.monotonic() - _last)
            if wait > 0:
                time.sleep(wait)
            _last = time.monotonic()
        try:
            req = urllib.request.Request(INFO, data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=25).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.0 * (attempt + 1))
    return None


def fills_window(addr, start_ms, end_ms):
    """Сделки адреса за период. HL отдаёт максимум неделю за запрос — шагаем окнами."""
    out, cur = [], start_ms
    while cur < end_ms:
        chunk = info({"type": "userFillsByTime", "user": addr,
                      "startTime": cur, "endTime": min(cur + WEEK_MS, end_ms)}) or []
        out += chunk
        cur += WEEK_MS
    return out


# Направление входа по полю dir. Разворот («Long > Short») тоже считаем входом в шорт:
# трейдер оказался в шорте именно на этой цене, а как он туда попал — деталь.
ENTER = {
    "short": lambda d: d == "Open Short" or d.endswith("> Short"),
    "long": lambda d: d == "Open Long" or d.endswith("> Long"),
}


def _hms(sec):
    sec = int(max(sec, 0))
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60) if sec >= 3600 \
        else "%d:%02d" % (sec // 60, sec % 60)


def _bar(done, total, found, t0, width=30):
    """Полоса прогресса в одну строку: перерисовывается на месте через \\r."""
    pct = done / total if total else 1.0
    fill = int(pct * width)
    eta = (time.time() - t0) / done * (total - done) if done else 0
    return "\r\033[K  [%s%s] %3.0f%%  %d/%d  найдено %d  осталось ~%s" % (
        "█" * fill, "·" * (width - fill), pct * 100, done, total, found, _hms(eta))


def scan(pool, coin, low, high, side, start_ms, end_ms, min_usd, verbose, workers=8):
    """Перебор пула. Узкое место — не лимит биржи, а задержка сети: запросы идут по одному
    и адрес занимает ~3.5с. Потоки перекрывают ожидания, пейсер при этом общий, так что
    суммарный темп остаётся в рамках лимита HL."""
    enter = ENTER[side]
    hits = {}
    items = list(pool.items())
    total, t0 = len(items), time.time()
    tty = sys.stderr.isatty()
    done = [0]
    out_lock = threading.Lock()

    def draw():
        if not verbose:
            return
        if tty:
            sys.stderr.write(_bar(done[0], total, len(hits), t0)); sys.stderr.flush()
        elif done[0] % 25 == 0:
            print("  …просмотрено %d / %d, найдено %d" % (done[0], total, len(hits)), file=sys.stderr)

    def work(item):
        addr, meta = item
        try:
            fills = fills_window(addr, start_ms, end_ms)
        except Exception as e:
            with out_lock:
                print("\r\033[K  ! %s: %s" % (addr[:10], e), file=sys.stderr)
                done[0] += 1; draw()
            return
        acc = None
        for f in fills:
            if f.get("coin") != coin or not enter(f.get("dir", "")):
                continue
            px = float(f["px"])
            if not (low <= px <= high):
                continue
            sz = float(f["sz"])
            acc = acc or {"addr": addr, "label": (meta or {}).get("label"), "sz": 0.0,
                          "usd": 0.0, "n": 0, "days": set(), "first": f["time"], "last": f["time"],
                          "pxs": []}
            acc["sz"] += sz
            acc["usd"] += sz * px
            acc["n"] += 1
            acc["pxs"].append(px)
            acc["days"].add(time.strftime("%m-%d", time.gmtime(f["time"] / 1000)))
            acc["first"] = min(acc["first"], f["time"])
            acc["last"] = max(acc["last"], f["time"])
        with out_lock:
            if acc and acc["usd"] >= min_usd:
                hits[addr] = acc
                # находку показываем сразу, поверх полосы — интереснее смотреть вживую
                print("\r\033[K  ✓ %s  %-16s $%s · %d сделок · %d дней · средняя %.1f" % (
                    addr[:12] + "…", (acc["label"] or "")[:16], f"{acc['usd']:,.0f}",
                    acc["n"], len(acc["days"]), sum(acc["pxs"]) / len(acc["pxs"])), file=sys.stderr)
            done[0] += 1
            draw()

    threads = []
    queue = list(items)
    qlock = threading.Lock()

    def loop():
        while True:
            with qlock:
                if not queue:
                    return
                item = queue.pop()
            work(item)

    for _ in range(max(1, workers)):
        th = threading.Thread(target=loop, daemon=True)
        th.start(); threads.append(th)
    for th in threads:
        th.join()

    if verbose and tty:
        sys.stderr.write(_bar(total, total, len(hits), t0) + "\n"); sys.stderr.flush()
    return hits


def load_pool(path):
    """Пул адресов из любого нашего формата: сырой лидерборд HL (00_leaderboard.json),
    список активных (01_active.json), pool.json, csv-вотчлист или просто список адресов."""
    if path.endswith(".csv"):
        import csv
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        key = "a" if rows and "a" in rows[0] else "address"
        return {r[key]: r for r in rows if r.get(key, "").startswith("0x")}

    raw = json.load(open(path))
    if isinstance(raw, dict) and "leaderboardRows" in raw:      # сырой лидерборд
        raw = raw["leaderboardRows"]
    if isinstance(raw, dict):                                   # {addr: meta}
        return raw
    out = {}
    for x in raw:                                               # список строк или словарей
        if isinstance(x, str):
            out[x] = {}
            continue
        addr = x.get("address") or x.get("ethAddress") or x.get("user")
        if addr:
            out[addr] = x
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True, help="json: {addr: {...}} или список адресов")
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--low", type=float, required=True)
    ap.add_argument("--high", type=float, required=True)
    ap.add_argument("--side", choices=("short", "long"), default="short")
    ap.add_argument("--days", type=int, default=21, help="глубина истории")
    ap.add_argument("--min-usd", type=float, default=50_000, help="порог объёма входа в зоне")
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N адресов (проба)")
    ap.add_argument("--workers", type=int, default=8, help="потоков; пейсер общий, лимит HL не превышаем")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", default="", help="куда сохранить json с уловом")
    a = ap.parse_args()

    pool = load_pool(a.pool)
    if a.limit:
        pool = dict(list(pool.items())[:a.limit])

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - a.days * 86400_000
    print("зона %s %.1f–%.1f · вход в %s · %d адресов · %d дней"
          % (a.coin, a.low, a.high, a.side, len(pool), a.days), file=sys.stderr)

    t0 = time.time()
    hits = scan(pool, a.coin, a.low, a.high, a.side, start_ms, end_ms, a.min_usd, True, a.workers)
    print("готово за %.0f с" % (time.time() - t0), file=sys.stderr)

    rows = sorted(hits.values(), key=lambda r: -r["usd"])
    print()
    print("НАЙДЕНО АДРЕСОВ: %d" % len(rows))
    print()
    print("%-44s %-18s %12s %10s %6s %6s  %s" % ("адрес", "метка", "объём $", "размер", "сдел", "дней", "средняя"))
    for r in rows[:a.top]:
        print("%-44s %-18s %12s %10.4f %6d %6d  %8.1f" % (
            r["addr"], (r["label"] or "")[:18], f"{r['usd']:,.0f}", r["sz"], r["n"],
            len(r["days"]), sum(r["pxs"]) / len(r["pxs"])))
    if a.out:
        json.dump({k: {**v, "days": sorted(v["days"])} for k, v in hits.items()},
                  open(a.out, "w"), ensure_ascii=False, indent=2)
        print("\nсохранено: %s" % a.out)


if __name__ == "__main__":
    main()
