"""Монитор адресов: опрос + WS-алерты + backstop-дифф + CRUD/связка с копиром (mixin).

Состояние (self.cfg, self.hl, self._mon_view/_mon_snap/_mon_alert_seen,
self._fill_stream, self.lock) живёт в Controller. Здесь только методы.
Подмешивается в Controller через наследование. См. docs/MONITOR-AUDIT.md.
"""
import html
import json
import os
import threading
import time

from copier.config import CONFIG_DIR
from copier.hl.rest import MAINNET as HL_MAIN, TESTNET as HL_TEST


class MonitorMixin:
    _MON_ACT = {"OPEN": "🟢 Opened", "INCREASE": "➕ Added", "REDUCE": "➖ Reduced",
                "CLOSE": "⚪ Closed", "FLIP": "🔄 Flipped", "LEVERAGE_CHANGE": "⚙️ changed leverage"}
    MON_DEDUP_SEC = 60   # окно дедупа: если WS уже прислал алерт, backstop-опрос его не дублирует

    @staticmethod
    def _mon_parse(state):
        """Возвращает (view, diff_snap). view — для UI, diff_snap — для алертов."""
        def f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        ms = state.get("marginSummary", {})
        eq = f(ms.get("accountValue"))
        margin_used = f(ms.get("totalMarginUsed"))
        withdrawable = f(state.get("withdrawable"))
        rich, diff_snap, tot = [], {}, 0.0
        for ap in state.get("assetPositions", []):
            p = ap.get("position", {})
            raw = p.get("coin")
            szi = f(p.get("szi"))
            if not raw or szi == 0:
                continue
            # builder-deployed перп-dex (HIP-3): coin приходит как 'xyz:SP500' → dex='xyz', coin='SP500'
            dexname, coin = raw.split(":", 1) if ":" in raw else (None, raw)
            lev = p.get("leverage", {}) or {}
            notional = f(p.get("positionValue"))
            upnl = f(p.get("unrealizedPnl"))
            tot += upnl
            side = "LONG" if szi > 0 else "SHORT"
            diff_snap[raw] = {"size": szi, "side": side, "lev": f(lev.get("value")),
                              "exposure_pct": (notional / eq * 100) if eq else 0}
            rich.append({
                "coin": coin, "dex": dexname, "side": side, "lev": f(lev.get("value")),
                "lev_type": lev.get("type", "cross"), "entry": f(p.get("entryPx")),
                "position_value": round(notional, 2), "uPnl": round(upnl, 2),
                "roe": round(f(p.get("returnOnEquity")) * 100, 1), "margin": round(f(p.get("marginUsed")), 2),
            })
        # free_margin — СВОБОДНАЯ маржа (эквити минус занятое), а не withdrawable: последний
        # у кросс-позиций почти всегда 0 (деньги заперты залогом), и карточка показывала «$0»
        # там, где у трейдера реально миллионы свободного плеча.
        view = {"equity": round(eq), "uPnl": round(tot, 2),
                "free_margin": round(eq - margin_used), "withdrawable": round(withdrawable),
                "margin_ratio": round(margin_used / eq * 100, 2) if eq else 0, "positions": rich}
        return view, diff_snap

    def _monitor_worker(self):
        """Фоновое обновление данных монитора + НАДЁЖНЫЕ алерты по диффу снимков (раз в N сек).

        Алерты идут отсюда (опрос), а не из WS: WS может молча отвалиться (429/reset),
        а опрос работает всегда. WS оставлен только для мгновенных строк в UI-логе.
        """
        while True:
            try:
                if not self._fill_stream:      # init WS не удался (или ещё не было) → ретрай отсюда
                    self._start_monitor_ws()   # сам троттлится кулдауном в _ensure_fill_stream
                self._poll_monitors()
            except Exception as e:
                self.log(f"[mon] poll cycle: {e}", "error")
            time.sleep(int(self.cfg.get("monitor_interval_sec", 30)))

    BUILDER_POLL_SEC = 300   # билдер-дексы (акции/индексы) опрашиваются реже основного перп-dex

    def _builder_monitor_worker(self):
        """Фон: реже основного поллинга собирает позиции наблюдаемых адресов на
        builder-deployed перп-dexs (HIP-3: TradFi-акции/индексы). Кэш в self._mon_builder."""
        while True:
            try:
                if not self._builder_dexs:                 # None или [] → пробуем снова (не кэшим пустоту навсегда)
                    self._builder_dexs = self.hl.perp_dexs()
                for m in (self.cfg.get("monitors") or []):
                    addr = m["address"]
                    positions, snap, ok = [], {}, True
                    for dx in (self._builder_dexs or []):
                        try:
                            v, s = self._mon_parse(self.hl.clearinghouse_state(addr, dex=dx))
                            positions += v.get("positions", [])
                            snap.update(s)
                        except Exception:
                            ok = False                     # сбой запроса (таймаут/429) — снимок неполный
                    # ОБНОВЛЯЕМ кэш только если все дексы ответили; при сбоях держим последний хороший
                    # (иначе позиции «мигают»: пустой цикл затирает живые данные до след. удачного)
                    if ok:
                        self._mon_builder[addr] = {"positions": positions, "snap": snap}
            except Exception as e:
                self.log(f"builder-dex monitor error: {e}", "error", tg=False)
            time.sleep(self.BUILDER_POLL_SEC)

    def _poll_monitors(self):
        for m in (self.cfg.get("monitors") or []):
            addr = m["address"]
            try:
                view, snap = self._mon_parse(self.hl.clearinghouse_state(addr))
            except Exception:
                continue
            # позиции на builder-dexs (HIP-3) — из фонового кэша, мерджим в общий вид/снимок
            b = self._mon_builder.get(addr) or {}
            if b.get("positions"):
                view["positions"] = view["positions"] + b["positions"]
                snap.update(b.get("snap") or {})
            copying = any(t["address"].lower() == addr.lower() for t in (self.cfg.get("targets") or []))
            spot = self._target_spot_usd(addr)                 # спот-кэш (USDC/USDT) для базы пропорции
            self._mon_view[addr] = {
                "address": addr, "name": m.get("name") or addr[:8],
                "alerts": m.get("alerts", True), "copying": copying, **view,
                "spot_usd": round(spot),
                # basis — БАЗА ПРОПОРЦИИ (max), а не весь капитал: на HL кросс-марже спот-USDC
                # и есть залог перпа, поэтому сумма считала бы одни деньги дважды. Проверено
                # обратным счётом от цены ликвидации: max расходится с залогом биржи на ~2%,
                # сумма — на +36%. bank отдаём отдельно, чтобы «сколько у него всего» было видно.
                "basis": round(max(view.get("equity") or 0, spot)),
                "bank": round((view.get("equity") or 0) + spot),
            }
            try:
                self._diff_monitor_alerts(m, addr, view, snap)
            except Exception as e:
                self.log(f"[mon] diff {addr[:8]}: {e}", "error")

    def _diff_monitor_alerts(self, m, addr, view, snap):
        """BACKSTOP: сравнивает снимок позиций с предыдущим и шлёт алерт ТОЛЬКО если
        мгновенный WS-алерт по этому изменению не прилетел (страховка на случай обрыва WS).
        Первый снимок адреса — baseline (без алертов), чтобы не было шторма на старте."""
        prev = self._mon_snap.get(addr)
        self._mon_snap[addr] = snap
        if prev is None or not m.get("alerts", True):
            return
        from copier.core.events import classify_net_change
        min_delta = float(self.cfg.get("monitor_min_delta_pct", 5))
        for coin in (set(prev) | set(snap)):
            if ":" in coin:
                continue
            for action, cur, pr in classify_net_change(prev.get(coin), snap.get(coin), min_delta):
                if time.time() - self._mon_alert_seen.get((addr.lower(), coin, action), 0) < self.MON_DEDUP_SEC:
                    continue   # WS уже прислал мгновенный алерт — не дублируем
                ctx = next((p for p in view.get("positions", []) if p["coin"] == coin), {})
                ref = cur or pr or {}
                name = m.get("name") or addr[:8]
                self._last_mon_event_ts = time.time()
                self.log(f"👁 {name} · {coin} {ref.get('side', '')}: "
                         f"{self._MON_ACT.get(action, action)} (backstop)", "monitor")
                self._tg_send(self._fmt_monitor_alert_snap(m, coin, action, cur, pr, ctx,
                                                           view.get("equity")),
                              kind="monitor", ttl=self._mon_ttl())

    # ---- WebSocket алерты монитора (мгновенно по филлам) ----
    FILL_STREAM_RETRY_SEC = 300   # неудачный init WS кэшируется на столько; потом ретрай (не навсегда)

    def _ensure_fill_stream(self):
        """Ленивый init WS-стрима филлов. Возвращает FillStream или falsy (None/False) —
        вызывающие (_start_monitor_ws, add_monitor, _status) полагаются на falsy.

        Неудача init НЕ фатальна навсегда: False кэшируется на FILL_STREAM_RETRY_SEC,
        затем пробуем снова (ретрай дёргает _monitor_worker). Иначе разовый сбой на старте
        выключал мгновенные алерты на весь процесс — оставался только backstop-опрос."""
        if self._fill_stream is not None and self._fill_stream is not False:
            return self._fill_stream
        if self._fill_stream is False and time.time() - self._fill_stream_fail_ts < self.FILL_STREAM_RETRY_SEC:
            return False                       # кулдаун после неудачи — не долбим init каждый вызов
        try:
            import hyperliquid  # noqa: F401
            from copier.hl.ws import FillStream
            base = HL_TEST if self.cfg.get("network") == "testnet" else HL_MAIN
            self._fill_stream = FillStream(self._on_monitor_fill, base, log=self.log,
                                           on_reconnect=self._on_monitor_ws_reconnect)
            self.log("monitor: WS subscription active (instant alerts)", "info")
        except Exception as e:
            first = self._fill_stream is None  # повторные неудачи — только в UI-лог, без TG-спама
            self._fill_stream = False
            self._fill_stream_fail_ts = time.time()
            self.log(f"[mon] WS unavailable (needs .venv; retry in {self.FILL_STREAM_RETRY_SEC}s): {e}",
                     "error", tg=first)
        return self._fill_stream

    def _on_monitor_ws_reconnect(self):
        """После (пере)подключения WS догоняем пропуски за время обрыва через backstop-опрос."""
        threading.Thread(target=self._poll_monitors, daemon=True).start()

    def _start_monitor_ws(self):
        fs = self._ensure_fill_stream()
        if fs:
            for m in (self.cfg.get("monitors") or []):
                fs.add(m["address"])
            fs.start()                # запускаем устойчивый цикл (коннект + watchdog + реконнект)

    def _on_monitor_fill(self, addr, fill):
        m = next((x for x in (self.cfg.get("monitors") or [])
                  if x["address"].lower() == addr.lower()), None)
        if not m or not m.get("alerts", True):
            return
        from copier.core.events import classify_fill
        e = classify_fill(fill)
        if ":" in e["coin"]:
            return
        e["otype"] = "Market" if fill.get("crossed") else "Limit"
        view = self._mon_view.get(addr, {})
        ctx = next((p for p in view.get("positions", []) if p["coin"] == e["coin"]), {})
        short = (f"👁 {m.get('name') or addr[:8]} · {e['coin']} {e['side']}: "
                 f"{self._MON_ACT.get(e['action'], e['action'])} {e['sz']:g} @ ${e['px']:,.4g}")
        self.log(short, "monitor")
        self._last_mon_event_ts = time.time()
        self._mon_alert_seen[(addr.lower(), e["coin"], e["action"])] = time.time()  # для дедупа с backstop-опросом
        # anti-spam: терминальное (откр/закр/разворот) и крупное — мгновенно; мелкий TWAP — в сводку
        terminal = e["action"] in ("OPEN", "CLOSE", "FLIP")
        instant_ntl = float(self.cfg.get("monitor_instant_notional_usd", 10000))
        if terminal or e["value"] >= instant_ntl:
            self._flush_mon_bucket(addr, e["coin"])                              # сбросить накопленную мелочь до крупного
            self._tg_send(self._fmt_monitor_alert(m, e, ctx, view.get("equity")),  # мгновенный WS-алерт
                          kind="monitor", ttl=self._mon_ttl())
        else:
            self._mon_accumulate(addr, m, e, ctx, view.get("equity"))            # копим в сводку

    # ---- коалесинг мелких TWAP-филлов в одну сводку (в стиле Slate "Order Summary") ----
    def _mon_accumulate(self, addr, m, e, ctx, equity):
        now = time.time()
        key = (addr.lower(), e["coin"])
        with self.lock:
            b = self._mon_pending.get(key)
            if not b:
                b = {"m": m, "addr": addr, "coin": e["coin"], "side": e["side"], "action": e["action"],
                     "otype": e.get("otype"), "mixed": False, "before": e["before"], "after": e["after"],
                     "count": 0, "val_sum": 0.0, "sz_sum": 0.0, "pxsz_sum": 0.0, "pnl_sum": 0.0,
                     "pos_value": ctx.get("position_value"), "lev": ctx.get("lev"),
                     "equity": equity, "first_recv": now}
                self._mon_pending[key] = b
            if e["action"] != b["action"]:
                b["mixed"] = True
            if e.get("otype") != b.get("otype"):
                b["otype"] = "Market/Limit"
            b["side"], b["after"] = e["side"], e["after"]
            b["count"] += 1
            b["val_sum"] += e["value"]
            b["sz_sum"] += abs(e["sz"])
            b["pxsz_sum"] += e["px"] * abs(e["sz"])
            cp = e.get("closedPnl")
            try:
                b["pnl_sum"] += float(cp) if cp not in (None, "", "0", "0.0") else 0.0
            except (TypeError, ValueError):
                pass
            if ctx.get("position_value"):
                b["pos_value"] = ctx["position_value"]
            if ctx.get("lev"):
                b["lev"] = ctx["lev"]
            b["equity"] = equity or b["equity"]
            b["last_recv"] = now

    def _mon_flush_worker(self):
        """Фон: флашит созревшие сводки (тишина quiet_sec или потолок max_sec)."""
        while True:
            time.sleep(5)
            try:
                self._flush_ready_buckets()
            except Exception as e:
                import traceback
                self.log(f"[mon-flush] crash: {type(e).__name__}: {e} | "
                         f"{traceback.format_exc().strip().splitlines()[-1][:160]}", "error", tg=False)

    def _mon_ttl(self):
        """Сколько секунд монитор-алерт живёт в очереди отправки перед дропом по TTL.
        0 = НЕ дропать (дефолт). Для наблюдения за чужими алерт полезен даже с задержкой.

        УСТОЙЧИВО К None: в конфиге ключ мог быть = null (напр. из UI-сохранения) → тогда
        .get(key, 0) вернёт None, а float(None) РАНЬШЕ КРАШИЛ _mon_ttl → падала отправка
        КАЖДОГО монитор-алерта (👁 логировался, но _tg_send не вызывался — «тишина днями»)."""
        v = self.cfg.get("monitor_alert_ttl_sec", 0)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _flush_ready_buckets(self):
        quiet = float(self.cfg.get("monitor_coalesce_quiet_sec", 45))
        mx = float(self.cfg.get("monitor_coalesce_max_sec", 300))
        now = time.time()
        ready = []
        with self.lock:
            for key, b in list(self._mon_pending.items()):
                if (now - b["last_recv"] >= quiet) or (now - b["first_recv"] >= mx):
                    ready.append(self._mon_pending.pop(key))
        for b in ready:
            self._emit_bucket(b)

    def _flush_mon_bucket(self, addr, coin):
        with self.lock:
            b = self._mon_pending.pop((addr.lower(), coin), None)
        if b:
            self._emit_bucket(b)

    def _emit_bucket(self, b):
        if not b.get("count") or not b["m"].get("alerts", True):
            return
        self._last_mon_event_ts = time.time()
        self.log(f"👁 {b['m'].get('name') or b['addr'][:8]} · {b['coin']} {b['side']}: "
                 f"summary {b['count']} trades (${b['val_sum']:,.0f})", "monitor")
        try:
            self._tg_send(self._fmt_monitor_alert_agg(b), kind="monitor", ttl=self._mon_ttl())
        except Exception as e:
            import traceback
            self.log(f"monitor-summary send CRASH: {type(e).__name__}: {e} | {traceback.format_exc()[-400:]}", "error", tg=False)

    def _fmt_monitor_alert_agg(self, b):
        ACT = {"OPEN": "Opened", "INCREASE": "Added", "REDUCE": "Reduced",
               "CLOSE": "Closed", "FLIP": "Flipped"}
        m = b["m"]
        # метку счёта задаёт пользователь: «Копи & Ко» сломала бы HTML-разметку → 400
        title = html.escape(str(m.get("name") or m["address"][:8]), quote=False)
        side = b["side"]
        dot = "🔴" if side == "SHORT" else "🟢"
        vwap = b["pxsz_sum"] / b["sz_sum"] if b["sz_sum"] else 0.0
        val = b["val_sum"]
        vs = f"${val/1e6:.2f}M" if val >= 1e6 else (f"${val/1e3:.1f}K" if val >= 1e3 else f"${val:.0f}")
        before, after = abs(b["before"]), abs(b["after"])
        netpct = ((after - before) / before * 100) if before else 100.0
        posval = b.get("pos_value") or (after * vwap)
        pos_pct = (val / posval * 100) if posval else 0.0
        act = "Activity" if b.get("mixed") else ACT.get(b["action"], b["action"])
        win_min = (b["last_recv"] - b["first_recv"]) / 60.0
        # НЕ "<1 мин": сводка уходит с parse_mode=HTML, Telegram видит в "<1" открывающий тег
        # → 400 «Unsupported start tag "1"», и сообщение не доставляется вовсе.
        wins = f"~{win_min:.0f} min" if win_min >= 1 else "less than 1 min"
        lines = [
            f"📊 <b>Order Summary</b> · {title}",
            f"<code>{m['address']}</code>",
            "────────────",
            f"{dot} <b>{b['coin']}</b> ({'Short' if side == 'SHORT' else 'Long'} · {act})",
            f"• Type: {b.get('otype') or '—'}",
            f"• Volume: {vs} · {b['count']} trades",
            f"• % of position: {pos_pct:.2f}%",
            f"• Size: {before:g} → {after:g} ({netpct:+.2f}%)",
            f"• Avg price (VWAP): ${vwap:,.6g}",
        ]
        if abs(b.get("pnl_sum") or 0) > 0:
            lines.append(f"• Σ PnL: {b['pnl_sum']:+.2f}")
        lines.append(f"🕒 window {wins}")
        return "\n".join(lines)

    def _fmt_monitor_alert(self, m, e, ctx, equity):
        import datetime
        ACT = {"OPEN": "Opened", "INCREASE": "Added", "REDUCE": "Reduced",
               "CLOSE": "Closed", "FLIP": "Flipped"}
        # метку счёта задаёт пользователь: «Копи & Ко» сломала бы HTML-разметку → 400
        title = html.escape(str(m.get("name") or m["address"][:8]), quote=False)
        dot = "🔴" if e["side"] == "SHORT" else "🟢"
        mt = "Isolated" if ctx.get("lev_type") == "isolated" else "Cross"
        val = e["value"]
        vs = f"${val/1e6:.2f}M" if val >= 1e6 else (f"${val/1e3:.1f}K" if val >= 1e3 else f"${val:.0f}")
        t = datetime.datetime.fromtimestamp(e["time"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"👁 <b>Watched</b> · {title}",
            f"<code>{m['address']}</code>",
            "────────────",
            f"{dot} <b>{e['coin']}</b> ({mt} · {'Short' if e['side']=='SHORT' else 'Long'} · {ACT.get(e['action'], e['action'])})",
            f"• Size: {e['before']:g} → {e['after']:g} ({e['pct']:+.2f}%)",
            f"• Order volume: {vs}",
            f"• Avg price: ${e['px']:,.6g}",
        ]
        if equity and ctx.get("lev"):
            exp = abs(e["after"]) * e["px"] / equity * 100
            lines.append(f"• Exposure: {exp:.1f}% · {ctx['lev']:.0f}x")
        cp = e.get("closedPnl")
        if cp not in (None, "0.0", "0") and e["action"] in ("REDUCE", "CLOSE", "FLIP"):
            lines.append(f"• PnL: {float(cp):+.2f}")
        lines.append(f"📅 {t} UTC")
        return "\n".join(lines)

    def _fmt_monitor_alert_snap(self, m, coin, action, cur, prev, ctx, equity):
        """Алерт по диффу снимков (путь опроса). Без px/PnL филла — данные из позиции."""
        ACT = {"OPEN": "Opened", "INCREASE": "Added", "REDUCE": "Reduced",
               "CLOSE": "Closed", "FLIP": "Flipped", "LEVERAGE_CHANGE": "Leverage change"}
        ref = cur or prev or {}
        side = ref.get("side", "")
        # метку счёта задаёт пользователь: «Копи & Ко» сломала бы HTML-разметку → 400
        title = html.escape(str(m.get("name") or m["address"][:8]), quote=False)
        dot = "🔴" if side == "SHORT" else "🟢"
        mt = "Isolated" if ctx.get("lev_type") == "isolated" else "Cross"
        before = abs(prev["size"]) if prev else 0.0
        after = abs(cur["size"]) if cur else 0.0
        pct = ((after - before) / before * 100) if before else 100.0
        lines = [
            f"👁 <b>Watched</b> · {title}",
            f"<code>{m['address']}</code>",
            "────────────",
            f"{dot} <b>{coin}</b> ({mt} · {'Short' if side == 'SHORT' else 'Long'} · {ACT.get(action, action)})",
            f"• Size: {before:g} → {after:g} ({pct:+.2f}%)",
        ]
        notional = ctx.get("position_value")
        if notional:
            nv = (f"${notional/1e6:.2f}M" if notional >= 1e6
                  else (f"${notional/1e3:.1f}K" if notional >= 1e3 else f"${notional:.0f}"))
            lines.append(f"• Current volume: {nv}")
        if ctx.get("entry"):
            lines.append(f"• Entry: ${ctx['entry']:,.6g}")
        if action == "LEVERAGE_CHANGE" and prev and cur:
            lines.append(f"• Leverage: {prev['lev']:.0f}x → {cur['lev']:.0f}x")
        elif equity and (cur or {}).get("lev"):
            lines.append(f"• Exposure: {cur.get('exposure_pct', 0):.1f}% · {cur['lev']:.0f}x")
        if ctx.get("uPnl") is not None and action in ("REDUCE", "CLOSE", "FLIP"):
            lines.append(f"• Position uPnL: {ctx['uPnl']:+.2f}")
        lines.append("📡 via poll (~30s)")
        return "\n".join(lines)

    def _refresh_copying_flags(self):
        """Мгновенно перещёлкнуть флаг copying во вью мониторов, не дожидаясь
        фонового опроса — иначе бейдж «копир» в UI отстаёт на цикл поллинга."""
        tgts = {t.get("address", "").lower() for t in (self.cfg.get("targets") or [])}
        for a, v in self._mon_view.items():
            if isinstance(v, dict):
                v["copying"] = a.lower() in tgts

    def set_copy_target(self, address):
        """Сделать адрес ЕДИНСТВЕННОЙ целью копирования (замыкает монитор↔копир)."""
        address = (address or "").strip()
        if not address:
            return {"error": "пустой адрес"}
        name = next((m.get("name") for m in (self.cfg.get("monitors") or [])
                     if m["address"].lower() == address.lower()), None) or address[:10]
        prev = next((t.get("address") for t in (self.cfg.get("targets") or [])), None)
        with self.lock:
            self._set_active_targets([{"address": address, "weight": 1.0, "label": name}])
            self._refresh_copying_flags()
        self.log(f"copier: target → {name} (press Start LIVE to copy)", "info")
        # если копир уже работает и цель сменилась — закрыть старую сессию журнала и открыть новую
        if self.running and prev and prev.lower() != address.lower():
            self._close_session("target_changed")
            self._journal_on_start()
        return {"ok": True}

    def clear_copy_target(self):
        """Убрать цель и остановить бота (без ликвидации — позиции остаются)."""
        self.stop()                       # закроет сессию журнала как 'stopped'
        self._restamp_last_reason("cleared")
        with self.lock:
            self._set_active_targets([])
            self._refresh_copying_flags()
        self.log("copier: target cleared, bot stopped", "info")
        return {"ok": True}

    def get_monitors(self):
        order = [m["address"] for m in (self.cfg.get("monitors") or [])]
        return [self._mon_view.get(a, {"address": a,
                "name": next((m.get("name") for m in self.cfg["monitors"] if m["address"] == a), a[:8]),
                "positions": []}) for a in order]

    def add_monitor(self, address, name):
        address = (address or "").strip()
        if not address:
            return {"error": "пустой адрес"}
        with self.lock:
            mons = self._cfg_raw.setdefault("monitors", [])   # monitors — глобальные (сырой конфиг)
            if any(m["address"].lower() == address.lower() for m in mons):
                return {"error": "адрес уже в мониторе"}
            mons.append({"address": address, "name": (name or "").strip(), "alerts": True})
            self.cfg["monitors"] = mons
            self._save_raw()
        self.log(f"monitor: added {name or address[:10]}", "info")
        threading.Thread(target=self._poll_monitors, daemon=True).start()  # сразу подтянуть данные
        fs = self._ensure_fill_stream()                                    # подписать на WS-алерты
        if fs:
            fs.add(address)
        return {"ok": True}

    def refresh_monitor(self, address):
        """Свежий запрос по одному адресу (для раскрытой строки). Базу алертов не трогает."""
        m = next((x for x in (self.cfg.get("monitors") or [])
                  if x["address"].lower() == (address or "").lower()), None)
        if not m:
            return {"error": "не найден"}
        try:
            view, _ = self._mon_parse(self.hl.clearinghouse_state(m["address"]))
        except Exception as e:
            return {"error": str(e)}
        copying = any(t["address"].lower() == m["address"].lower() for t in (self.cfg.get("targets") or []))
        mon = {"address": m["address"], "name": m.get("name") or m["address"][:8],
               "alerts": m.get("alerts", True), "copying": copying, **view}
        self._mon_view[m["address"]] = mon
        return {"monitor": mon}

    def toggle_monitor(self, address):
        with self.lock:
            for m in self._cfg_raw.get("monitors", []):
                if m["address"].lower() == (address or "").lower():
                    m["alerts"] = not m.get("alerts", True)
            self._save_raw()
        if address in self._mon_view:
            self._mon_view[address]["alerts"] = next(
                (m.get("alerts", True) for m in self.cfg.get("monitors", []) if m["address"] == address), True)
        return {"ok": True}

    def remove_monitor(self, address):
        with self.lock:
            self._cfg_raw["monitors"] = [m for m in (self._cfg_raw.get("monitors") or [])
                                         if m["address"].lower() != (address or "").lower()]
            self.cfg["monitors"] = self._cfg_raw["monitors"]
            self._save_raw()
        # вычистить in-memory вью (без учёта регистра) и отписать WS, иначе живой стрим тянет филлы удалённого
        for k in [a for a in self._mon_view if a.lower() == (address or "").lower()]:
            self._mon_view.pop(k, None)
        fs = self._fill_stream
        if fs:
            fs.remove(address)
        return {"ok": True}
