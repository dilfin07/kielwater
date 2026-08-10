import { api as mock } from './mockClient'

// Реальный клиент к бэкенду hl-copier (через Vite-прокси /api → Pi).
// ПЕРЕЕЗД ИДЁТ ПОЭКРАННО: чтения (monitors/status/logs/config/journal…) живые, редкие
// остатки — мягкий фолбэк на мок. Мутации: безопасные (алерты/монитор/настройки/счёт/цель
// копирования) живые; опасные для торговли идут в UI за подтверждением; add/remove счёта и
// прочее ещё не перенесённое — blocked() (no-op к живому боту).

const TOKEN_KEY = 'hlc_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY))

async function j(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const t = getToken()
  if (t) headers.Authorization = 'Bearer ' + t
  const r = await fetch('/api' + path, { ...opts, headers })
  if (r.status === 401) { setToken(''); window.dispatchEvent(new Event('hlc-unauth')); throw new Error('unauth') }
  if (!r.ok) throw new Error('http ' + r.status)
  return r.json()
}
const jpost = (path, body) => j(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })

// публичные (без токена)
export const authStatus = () => fetch('/api/auth_status').then((r) => r.json())
export const login = (password) => jpost('/login', { password })

// ---- форматтеры (как в боевом web) ----
const usd = (v) => (v == null ? '—' : `$${Math.round(v).toLocaleString('en-US')}`)
const signed = (v) => (v == null ? '—' : `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
const px = (x) => (x ? x.toLocaleString('en-US', { maximumFractionDigits: x < 10 ? 5 : 2 }) : '—')

// ---- адаптеры: форма реального API → форма, которую ждут вьюхи ----
function adaptMonitors(data) {
  return (data?.monitors || []).map((m) => ({
    id: m.address,
    name: m.name || (m.address || '').slice(0, 8),
    addr: m.address,
    perp: usd(m.equity),
    spot: usd(m.spot_usd),
    bank: usd(m.bank),          // перп + спот: сколько у трейдера всего денег
    base: usd(m.basis),         // база пропорции = max(перп, спот) — по ней считается наш размер
    upnl: signed(m.uPnl),
    free: usd(m.free_margin),
    mur: Math.round((m.margin_ratio ?? 0) * 100) / 100,
    pos: (m.positions || []).length,
    copying: !!m.copying,
    alerts: !!m.alerts,
    positions: (m.positions || []).map((p) => ({
      coin: p.coin,
      dex: p.dex || null,        // builder-dex (HIP-3: TradFi-акции/индексы), напр. 'xyz'
      price: px(p.entry),
      side: p.side,
      marginType: p.lev_type === 'isolated' ? 'Iso' : 'Cross',
      lev: `${p.lev}×`,
      notional: usd(p.position_value),
      upnl: signed(p.uPnl),
      upnlPct: `${p.roe >= 0 ? '+' : ''}${p.roe}%`,
      margin: usd(p.margin),
    })),
  }))
}

function adaptLogs(data) {
  // бэк отдаёт oldest→newest; нам нужно newest-first; ts ISO → HH:MM:SS
  return (data?.logs || []).slice().reverse().map((l) => ({ ts: (l.ts || '').slice(11, 19), level: l.level, msg: l.msg }))
}

function adaptAccounts(cfg) {
  const accs = cfg?.accounts || []
  if (!accs.length) return [{ id: 'main', label: 'Основной', type: 'futures', network: cfg?.network || 'mainnet', key_env: 'BINANCE', balance: '—', hasKeys: true }]
  return accs.map((a) => ({
    id: a.id, label: a.label || a.id, type: a.type || 'futures', network: a.network || 'mainnet',
    key_env: a.key_env || 'BINANCE', balance: '—', hasKeys: a.has_keys ?? a.hasKeys ?? false,
    lastActive: a.last_active || 0,
  }))
}

function adaptOverview(acct) {
  return {
    unreal: signed(acct?.uPnl), leverage: `${acct?.leverage ?? 0}×`,
    marginUse: `${acct?.margin_usage ?? 0}%`, yearPnl: signed(acct?.realized_total),
    realized: signed(acct?.realized_total), realizedPct: '—',
  }
}

function buildCurve(daily) {
  let acc = 0
  return Object.keys(daily).sort().map((k) => ({ d: k.slice(5), pnl: Math.round((acc += daily[k]) * 100) / 100 }))
}

function adaptPositions(s) {
  return (s?.positions || []).map((p) => {
    const neg = p.side === 'SHORT'
    return {
      sym: p.symbol, perp: 'бессроч', lev: `${p.leverage}×`, positionSide: p.positionSide,
      side: neg ? 'ШОРТ' : 'ЛОНГ', sideRaw: p.side,
      size: `${neg ? '−' : '+'}${px(p.notional)}`, sizeUnit: 'USDT',
      entry: px(p.entry), breakeven: '—', mark: px(p.mark), liq: px(p.liq),
      marginRatio: '—', margin: px(p.margin), marginType: '—',
      pnl: `${p.uPnl >= 0 ? '+' : '−'}${Math.abs(p.uPnl).toLocaleString('en-US', { maximumFractionDigits: 2 })}`,
      pnlUnit: 'USDT', pnlPos: p.uPnl >= 0,
      roi: `${p.roi >= 0 ? '+' : ''}${p.roi}%`, funding: '—', fundingPct: '',
    }
  })
}

function adaptTrades(data) {
  return (data?.positions || []).map((p) => {
    const notional = (p.entry || 0) * (p.qty || 0)
    const pct = notional ? (p.realizedPnl / notional) * 100 : 0
    const d = new Date(p.close_time)
    const pad = (n) => String(n).padStart(2, '0')
    const dt = `${pad(d.getDate())}.${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`
    const pos = (p.realizedPnl || 0) >= 0
    return {
      dt, sym: p.symbol, side: p.side, bot: !!p.bot,
      pnl: `${pos ? '+' : '−'}$${Math.abs(p.realizedPnl || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })}`,
      pct: `${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`,
      fee: `$${(p.commission || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })}`,
      turn: `$${Math.round(notional).toLocaleString('en-US')}`,
    }
  })
}

// исполнения бота (фактические трейды) из /api/fills — всегда наполнено, у каждого флаг bot
function adaptFills(data) {
  return (data?.fills || []).map((f) => {
    const d = new Date(f.time)
    const pad = (n) => String(n).padStart(2, '0')
    const dt = `${pad(d.getDate())}.${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`
    const dtFull = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}, ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    const pnl = f.realizedPnl || 0
    // тип действия из fill: pnl≠0 → закрытие (реализован PnL), иначе открытие/добор.
    // SELL закрывает лонг / открывает шорт; BUY закрывает шорт / открывает лонг.
    const closing = pnl !== 0
    const long = closing ? f.side === 'SELL' : f.side === 'BUY'
    const action = `${closing ? 'close' : 'open'}-${long ? 'long' : 'short'}`
    return {
      dt, dtFull, sym: f.symbol, side: f.side, bot: !!f.bot,
      action, qty: f.qty, priceRaw: f.price, pnlRaw: pnl, notional: (f.qty || 0) * (f.price || 0),
      pnl: pnl ? `${pnl >= 0 ? '+' : '−'}$${Math.abs(pnl).toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '—',
      price: px(f.price),
      fee: `$${(f.commission || 0).toLocaleString('en-US', { maximumFractionDigits: 4 })}`,
      turn: `$${Math.round((f.qty || 0) * (f.price || 0)).toLocaleString('en-US')}`,
    }
  })
}

// баннер цели: реальный копируемый трейдер + сравнение пропорции (наш риск/средняя ↔ лид)
function adaptTarget(mons, status) {
  const m = (mons?.monitors || []).find((x) => x.copying)
  if (!m) return null
  const lead = (m.positions || [])[0] || {}
  const ourEq = status?.services?.binance?.equity
  const ourPos = (status?.positions || []).find((p) => (p.symbol || '').startsWith(lead.coin || '∅'))
  const leadRisk = lead.position_value && m.equity ? lead.position_value / m.equity : null
  const ourRisk = ourPos && ourEq ? Math.abs(ourPos.notional) / ourEq : null
  return {
    name: m.name || (m.address || '').slice(0, 8),
    addr: `${(m.address || '').slice(0, 14)}…`,
    coin: lead.coin || '—', side: lead.side || '—',
    risk: ourRisk != null ? `${ourRisk.toFixed(2)}×` : '—',
    leadRisk: leadRisk != null ? `${leadRisk.toFixed(2)}×` : '—',
    avg: ourPos?.entry != null ? px(ourPos.entry) : '—',
    leadAvg: lead.entry != null ? px(lead.entry) : '—',
    live: true,
  }
}

function adaptServices(s) {
  const sv = (s && s.services) || {}
  const hl = sv.hyperliquid || {}, bn = sv.binance || {}, cp = sv.copier || {}, mn = sv.monitoring || {}
  return [
    { key: 'hl', label: 'Hyperliquid', state: hl.state || 'off', note: hl.transport === 'ws' ? `ws×${hl.ws_streams ?? 0}` : 'rest' },
    { key: 'bn', label: 'Binance', state: bn.state || 'off', note: bn.state === 'off' ? '—' : (bn.network === 'mainnet' ? 'main' : bn.network || '?') },
    { key: 'copier', label: 'Копир', state: cp.state || 'off', note: !cp.running ? 'стоп' : `${cp.live ? 'LIVE' : 'DRY'} · ${cp.mode === 'ws' ? 'ws' : 'опрос'}` },
    { key: 'mon', label: 'Монитор', state: mn.state || 'off', note: mn.state === 'off' ? '0' : `${mn.count ?? 0} адр` },
  ]
}

// read-only гард: ни одна мутация не уходит к живому боту
const blocked = async () => { console.warn('[live] read-only режим: мутация заблокирована (смотрим на боевой Pi)'); return false }

export const api = {
  ...mock, // target пока из мока (best-effort live ниже переопределяет)

  // перенесено на live:
  monitors: () => j('/monitors').then(adaptMonitors),
  services: () => j('/status').then(adaptServices).catch(() => adaptServices(null)),
  logs: () => j('/logs').then(adaptLogs),
  accounts: () => j('/config').then(adaptAccounts),
  overview: () => j('/account_stats').then(adaptOverview),
  meta: () => Promise.all([
    j('/status').catch(() => ({})),
    j('/config').catch(() => ({})),
  ]).then(([s, c]) => ({
    balance: usd(s?.services?.binance?.equity),
    activeAccount: c?.active_account || 'main',
    running: !!s?.services?.copier?.running,
    live: !!s?.services?.copier?.live,
    mode: s?.services?.copier?.mode || s?.data_mode || 'ws',
  })),
  // цель копирования — реальный трейдер + сравнение пропорции
  target: async () => {
    const [mons, status] = await Promise.all([j('/monitors').catch(() => ({})), j('/status').catch(() => ({}))])
    return adaptTarget(mons, status)
  },
  // журнал: всё живое — кривая+хитмап (account_stats), открытые (status), сделки = исполнения бота (fills)
  journal: async () => {
    const [acct, status, fl, ph] = await Promise.all([
      j('/account_stats').catch(() => ({})),
      j('/status').catch(() => ({})),
      j('/fills').catch(() => ({})),
      j('/position_history').catch(() => ({})),
    ])
    const daily = acct?.daily || {}
    const mj = await mock.journal()
    return {
      curve: Object.keys(daily).length ? buildCurve(daily) : mj.curve,
      heat: Object.keys(daily).length ? daily : mj.heat,
      open: 'positions' in (status || {}) ? adaptPositions(status) : mj.open,
      trades: 'fills' in (fl || {}) ? adaptFills(fl) : mj.trades,
      analytics: ph?.analytics || null,   // risk-метрики от биржевых закрытых сделок
      closed: Array.isArray(ph?.positions) ? ph.positions : [],   // закрытые позиции (история)
    }
  },

  config: () => j('/config'),

  // --- настроечные мутации (разрешены в live) ---
  saveConfig: (cfg) => jpost('/config', cfg),
  saveTelegram: ({ token, chat_id, enabled }) => jpost('/telegram', { token, chat_id, enabled }),
  testTelegram: () => jpost('/telegram_test', {}),
  saveAuth: ({ password, enabled }) => jpost('/ui_auth', { password, enabled }),
  setActiveAccount: (id) => jpost('/active_account', { id }),
  switchActive: (id) => jpost('/active_account', { id }),
  // действия бота — реальные (двигают деньги)
  startBot: ({ live = false, mode = 'ws' } = {}) => jpost('/start', { live, mode }),
  stopBot: () => jpost('/stop', {}),
  closePosition: ({ symbol, positionSide }) => jpost('/close', { symbol, position_side: positionSide }),
  deleteAccount: async (id) => {
    const cfg = await j('/config')
    cfg.accounts = (cfg.accounts || []).filter((a) => a.id !== id)
    if (cfg.active_account === id) cfg.active_account = 'main'
    return jpost('/config', cfg)
  },
  addAccountKeys: async ({ account, api_key, api_secret }) => {
    const cfg = await j('/config')
    const others = (cfg.accounts || []).filter((a) => a.key_env !== account.key_env && a.id !== account.id)
    await jpost('/config', { ...cfg, accounts: [...others, account] })
    if (api_key && api_secret) await jpost('/keys', { api_key, api_secret, key_env: account.key_env })
    return { ok: true }
  },

  // --- монитор: алерты/добавление/удаление — безопасно (не трогают торговлю) ---
  toggleMonitor: (id, field) => (field === 'alerts' ? jpost('/monitor_toggle', { address: id }) : blocked()),
  addMonitor: (rec) => jpost('/monitor_add', { address: rec.addr || rec.id, name: rec.name || '' }),
  removeMonitor: (id) => jpost('/monitor_remove', { address: id }),
  // цель копирования — живые эндпоинты (в UI за подтверждающей модалкой, т.к. меняют торговлю)
  setCopyTarget: (addr) => jpost('/copy_set', { address: addr }),
  clearCopyTarget: () => jpost('/copy_clear', {}),
  // мутации счетов — заблокированы (add/remove счёта делается через addAccountKeys в настройках)
  addAccount: blocked, removeAccount: blocked,
}
