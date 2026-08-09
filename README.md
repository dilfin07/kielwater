# Kielwater

**Copytrade Hyperliquid → Binance USDT-M Futures — with a real risk core.**

*Kielwater — the wake a ship leaves behind its keel. You trade in the lead's wake.*

Kielwater mirrors a Hyperliquid lead trader's positions onto *your* Binance
Futures account at an **honest proportion to your capital**, then wraps that with a
risk layer that exchange copy-trading doesn't give you. It's more than a copier:
it also ships an address **monitor**, a trading **journal**, a web **dashboard**, and
trader-**research** tools.

> 🇬🇧 English · [🇷🇺 Русский](README.ru.md) · Full docs read fine on GitHub without
> running anything — see [Documentation](#documentation).
>
> ℹ️ Formerly **hypermirror** — renamed to avoid confusion with an unrelated service of
> that name. Same project, same authors; old links redirect here.

---

## Why it's different from exchange copy-trading

Exchange copiers give you a fixed ratio and a dumb `-N%` stop. Kielwater gives you a
**risk core** — eight ordered filters between *what the lead does* and *what you do*:

- **Honest proportion** — `your_notional / your_equity ≈ lead_notional / lead_base`,
  not a blind fixed ratio. The lead's base is `max(perp equity, spot USDC)`.
- **Gross leverage cap** — clamp your *total* exposure (e.g. lead at 467% → you at 3×).
  Set to `0` for a full, uncapped mirror.
- **Per-position leverage cap** + **margin buffer** — never use 100% of margin
  (avoids Binance `-2019 Margin insufficient`).
- **Favorability gate** — don't chase entries worse than the lead's average; protects
  *your* fill price. Exits and reductions are never gated.
- **Start freeze** — on adopt, don't jump into a position the lead is already deep in profit on.
- **auto-sync off** — follow only *new* lead moves; your manual trims are respected, not
  bought back.
- **Exchange = source of truth** — positions are read from Binance `positionRisk`, so there
  are no ghost/zombie positions the bot thinks it holds but the exchange doesn't.

📊 **Visual architecture map** (levers, conditions, what's UI-configurable vs hardcoded):
[`hl-copier/docs/copier-architecture.html`](hl-copier/docs/copier-architecture.html) — open it in a browser.

---

## Components

| Directory | What it is |
|---|---|
| [`hl-copier/`](hl-copier/) | The core: reconciliation engine, server + REST API, Binance execution (signed REST, stdlib `urllib`+`hmac`), Telegram bot, local watchdog. |
| [`hl-copier-mcp/`](hl-copier-mcp/) | MCP server for AI agents (Claude Code, etc.): `status`, `verify_close`, `check_errors`, `notify_tg`, and more. |
| [`ui-prototype/`](ui-prototype/) | Web dashboard (React + Mantine). Builds into `hl-copier/web/v2/`. |
| [`trader-watch/`](trader-watch/) | Research: shortlist Hyperliquid traders, classify, compute stats from public on-chain data. |

---

## How it works

- **Source** — Hyperliquid public API (no keys required): lead positions, leverage, equity.
- **Execution** — Binance USDT-M Futures via signed REST.
- **Sizing** — honest proportion (see above), then the risk pipeline, then reconciliation.
- **Reconciliation** — every tick the bot diffs *desired* (proportional to the lead) against
  your *actual* Binance position and places only the delta. Maker-first execution with a
  taker fallback; a full close always goes taker to guarantee the exit.
- **Modes** — mirror or fixed leverage; per-account settings; coin whitelist; builder-dex skip.

Full logic: [`hl-copier/docs/COPIER-CORE.md`](hl-copier/docs/COPIER-CORE.md).

---

## Quick start

**Requirements:** Python 3.11+, Node 18+ (only to build the dashboard), a Binance Futures
account with an API key (futures trading enabled). A Telegram bot is optional (for alerts).

```bash
# 1. clone
git clone https://github.com/dilfin07/kielwater.git
cd kielwater/hl-copier

# 2. python env + deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. secrets — copy the template and fill it in
cp .env.example .env
#   set: BINANCE_API_KEY / BINANCE_API_SECRET
#        TELEGRAM_BOT_TOKEN   (optional, for alerts)
#        UI_PASSWORD          (dashboard login)

# 4. config — copy the example and pick your lead trader(s)
cp config/config.example.json config/config.json
#   set targets[].address to the Hyperliquid wallet you want to copy,
#   and tune leverage_cap / favorability / execution_mode to taste.

# 5. (optional) build the dashboard
cd ../ui-prototype && npm install && \
  VITE_API=live npx vite build --base=/v2/ --outDir ../hl-copier/web/v2 --emptyOutDir && cd ../hl-copier

# 6. run
python3 tools/serve.py --port 8787 --host 127.0.0.1
```

> ⚠️ `VITE_API=live` is required: without it the dashboard builds in **mock mode**
> and shows made-up account, positions and PnL instead of real backend data.


Open **http://localhost:8787/v2** and log in with `UI_PASSWORD`. Start in **DRY** mode,
watch the plan it produces, then switch to **LIVE** when you're comfortable.

> ⚠️ Never run two LIVE instances against the same Binance account — you'll get duplicate orders.

---

## Configuration

All risk levers live in `config/config.json` (per-account) and are editable from the
dashboard's **Settings**. The essentials:

| Key | What it does |
|---|---|
| `targets[]` | Hyperliquid lead wallet(s) to copy, with optional weights. |
| `leverage_cap` | Cap on your *gross* exposure (× equity). `0` = uncapped full mirror. |
| `mirror_max_leverage` | Per-position leverage cap in mirror mode. |
| `size_multiplier` | Scale the lead's proportion (1 = one-to-one, 0.5 = half, 2 = double). |
| `favorability_gate` / `favorability_tol_pct` | Don't add above the lead's average by more than `tol%`. |
| `execution_mode` | `maker` (limit-first) or `taker` (market). |
| `auto_sync` | `off` (default) follows only new lead moves; `on` also catches up drift. |
| `coin_whitelist` / `skip_builder_dexs` | Restrict which markets are copied. |

Reference: [`hl-copier/docs/OPERATIONS.md`](hl-copier/docs/OPERATIONS.md).

---

## Deploy

Runs happily on a small always-on box (a Raspberry Pi is plenty) via a `systemd` user
service. See [`hl-copier/docs/OPERATIONS.md`](hl-copier/docs/OPERATIONS.md) for the unit
file, the watchdog timer, and safe-deploy notes (deploys never touch live
`.env` / `config.json` / `runtime/`).

---

## Documentation

All readable on GitHub without running the service:

- 📊 [Architecture & risk core (visual)](hl-copier/docs/copier-architecture.html) — open in a browser
- [**Configuration reference** — every setting, default & interaction](hl-copier/docs/CONFIGURATION.md)
- [Copier core — how sizing, caps & reconciliation work](hl-copier/docs/COPIER-CORE.md)
- [Maker execution design](hl-copier/docs/MAKER-EXECUTION.md)
- [Monitor — watching traders](hl-copier/docs/MONITOR.md)
- [Operations — modes, config, deploy](hl-copier/docs/OPERATIONS.md)
- [Pipeline analysis — latency & resilience](hl-copier/docs/PIPELINE-ANALYSIS.md)

> The deep docs are being translated to English; some are still in Russian. The
> architecture map and this README are the fastest way in.

---

## Security

- Secrets live only in `.env` (git-ignored). Templates are `*/.env.example`.
- Your real targets/values go in `config/config.json`, which is git-ignored — only
  `config.example.json` is tracked.
- Bring your own Binance API key; restrict it to futures trading and, ideally, to your IP.
- The bot never moves your funds anywhere except placing orders on your own account.

---

## Support the project

Binance referral link: [**binance.com/register?ref=718442076**](https://www.binance.com/register?ref=718442076)
(code `718442076`). Forks are welcome to swap in their own code
in [`ui-prototype/src/constants.js`](ui-prototype/src/constants.js).

---

## Disclaimer

Trading leveraged futures is risky and can lose money fast. Kielwater is provided **as-is**,
with no warranty and no guarantee of profit. You are solely responsible for your keys, your
configuration, and your trades. Not financial advice.

## License

[MIT](LICENSE) © 2026 dilfin07
