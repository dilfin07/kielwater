"""Реконструкция истории позиций из ленты сделок.

Баг найден на боевом счёте 2026-08-09: журнал показывал ОДНУ позицию «SHORT, открыта
7 дней назад», хотя на бирже стоял LONG, а за неделю позиция разворачивалась дважды.
Причина — закрытие фиксировалось только при попадании нетто РОВНО в ноль, а разворот
проскакивает ноль насквозь (шорт 0.5 + BUY 1.2 = лонг 0.7), поэтому запись не
закрывалась никогда и копила в себе все последующие сделки.
"""
from copier.core.positions import reconstruct_positions

MIN = 60_000


def t(ms, side, qty, price, rpnl=0.0, comm=0.0, oid="1"):
    return {"time": ms, "side": side, "qty": qty, "price": price,
            "realizedPnl": rpnl, "commission": comm, "orderId": oid}


def test_flip_splits_into_two_positions():
    """Разворот через ноль: одна сделка закрывает лонг и открывает шорт."""
    trades = [
        t(1 * MIN, "BUY", 1.0, 100.0),                      # открыли лонг 1.0
        t(2 * MIN, "SELL", 3.0, 110.0, rpnl=10.0),          # закрыли лонг и ушли в шорт 2.0
    ]
    out = reconstruct_positions(trades, "ETHUSDT")

    assert len(out) == 1, "закрытая позиция должна появиться в истории"
    closed = out[0]
    assert closed["side"] == "LONG" and closed["status"] == "closed"
    assert closed["qty"] == 1.0 and closed["exit"] == 110.0
    assert closed["realizedPnl"] == 10.0
    assert closed["close_time"] == 2 * MIN


def test_after_flip_new_position_is_tracked_separately():
    """После разворота ведётся НОВАЯ позиция: своя сторона и своё время открытия."""
    trades = [
        t(1 * MIN, "BUY", 1.0, 100.0),
        t(2 * MIN, "SELL", 3.0, 110.0, rpnl=10.0),          # разворот в шорт 2.0
        t(3 * MIN, "BUY", 1.0, 105.0, rpnl=5.0),            # частично закрыли шорт
    ]
    out = reconstruct_positions(trades, "ETHUSDT")

    assert len(out) == 2
    partial = [p for p in out if p["status"] == "partial"][0]
    assert partial["side"] == "SHORT", "новая позиция после разворота — шорт, а не старый лонг"
    assert partial["open_time"] == 2 * MIN, "время открытия — от разворота, а не от первой сделки"
    assert partial["qty"] == 1.0


def test_two_flips_give_three_positions():
    """Боевой сценарий: два разворота за неделю → три позиции, а не одна вечная."""
    trades = [
        t(1 * MIN, "BUY", 1.0, 100.0),
        t(2 * MIN, "SELL", 2.0, 110.0, rpnl=10.0),          # → шорт 1.0
        t(3 * MIN, "BUY", 2.0, 105.0, rpnl=5.0),            # → лонг 1.0
        t(4 * MIN, "SELL", 0.5, 120.0, rpnl=7.5),           # сократили лонг
    ]
    out = reconstruct_positions(trades, "ETHUSDT")

    assert len(out) == 3
    assert [p["side"] for p in out] == ["LONG", "SHORT", "LONG"]
    assert [p["status"] for p in out] == ["closed", "closed", "partial"]


def test_plain_close_still_works():
    """Обычное закрытие в ноль (без разворота) не сломано."""
    trades = [
        t(1 * MIN, "BUY", 2.0, 100.0),
        t(5 * MIN, "SELL", 2.0, 110.0, rpnl=20.0),
    ]
    out = reconstruct_positions(trades, "ETHUSDT")

    assert len(out) == 1
    assert out[0]["status"] == "closed" and out[0]["side"] == "LONG"
    assert out[0]["duration_min"] == 4
    assert out[0]["truncated"] is False


def test_partial_reduction_keeps_one_position():
    """Сокращение без выхода в ноль — та же позиция, не новая запись."""
    trades = [
        t(1 * MIN, "BUY", 2.0, 100.0),
        t(2 * MIN, "SELL", 0.5, 110.0, rpnl=5.0),
    ]
    out = reconstruct_positions(trades, "ETHUSDT")

    assert len(out) == 1
    assert out[0]["status"] == "partial" and out[0]["qty"] == 1.5
    assert out[0]["open_time"] == 1 * MIN


def test_start_pos_seeds_reconstruction():
    """Лента начинается посреди открытой позиции: стартовое нетто берётся с биржи,
    иначе сторона и объём разъезжаются с реальностью."""
    trades = [t(1 * MIN, "SELL", 2.0, 110.0, rpnl=20.0)]     # закрывает лонг 2.0, открытый ДО ленты
    out = reconstruct_positions(trades, "ETHUSDT", start_pos=2.0, truncated=True)

    assert len(out) == 1
    assert out[0]["side"] == "LONG" and out[0]["status"] == "closed"
    assert out[0]["qty"] == 2.0, "объём закрытия учитывает набранное до начала ленты"
    assert out[0]["truncated"] is True
    assert out[0]["entry"] is None, "средняя входа неизвестна — не выдумываем ноль"


def test_bot_attribution_follows_opening_order():
    """Метка «бот/ручная» берётся от сделки, ОТКРЫВШЕЙ позицию, в том числе после разворота."""
    trades = [
        t(1 * MIN, "BUY", 1.0, 100.0, oid="manual-1"),
        t(2 * MIN, "SELL", 2.0, 110.0, rpnl=10.0, oid="bot-7"),   # разворот бот-ордером
        t(3 * MIN, "BUY", 0.5, 105.0, rpnl=2.5, oid="manual-2"),
    ]
    out = reconstruct_positions(trades, "ETHUSDT", bot_ids={"bot-7"})

    assert out[0]["bot"] is False, "лонг открыт вручную"
    assert out[1]["bot"] is True, "шорт открыт бот-ордером на развороте"
