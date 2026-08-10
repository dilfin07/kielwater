// Имитация данных бэка. При миграции на реальный API эти моки заменяются ответами
// эндпоинтов — формы данных совпадают, компоненты/хуки не меняются.

const CURVE = [0, -4, -7, -11, -18, -26, -33, -38, -41, -44, -47, -49, -51, -128, -150, -158, -168, -178, -188, -184, -188.56]
  .map((v, i) => ({ d: `Д${i + 1}`, pnl: Number(v.toFixed(2)) }))

// год дневного PnL: дата -> значение (диверг. −/+), стабильно
const HEAT = (() => {
  const out = {}
  const start = new Date('2025-06-24')
  for (let i = 0; i < 365; i++) {
    const dd = new Date(start)
    dd.setDate(start.getDate() + i)
    out[dd.toISOString().slice(0, 10)] = ((i * 9301 + 49297) % 233280) / 233280 < 0.22 ? 0 : Math.round((((i * 9301 + 49297) % 233280) / 233280 - 0.5) * 180)
  }
  return out
})()

export const MOCK = {
  activeAccount: 'main',
  balance: '$651.18',

  services: [
    { key: 'hl', label: 'Hyperliquid', state: 'ok', note: 'ws · 0с' },
    { key: 'bn', label: 'Binance', state: 'ok', note: 'tick 0с' },
    { key: 'copier', label: 'Копир', state: 'ok', note: 'LIVE · ws' },
    { key: 'mon', label: 'Монитор', state: 'warn', note: 'ws переподключ.' },
  ],

  logs: [
    { ts: '21:48:44', level: 'hb', msg: 'heartbeat: LIVE · ws · эквити $646.57 · позиций 1 · RUNNING' },
    { ts: '21:48:12', level: 'trade', msg: 'Скопировано · pension-usdt · ETH SHORT ДОЛИВ 0.013 @ 1732.79' },
    { ts: '21:47:55', level: 'target', msg: '🎯 ETH SHORT ДОЛИВ 9.6353 @ 1730.00' },
    { ts: '21:47:38', level: 'hb', msg: 'heartbeat: LIVE · ws · эквити $646.78 · позиций 1 · RUNNING' },
    { ts: '21:47:02', level: 'skip', msg: '⏭️ пропуск ETHUSDT/SHORT: favorability 1729.01 хуже входа цели 1735.63' },
    { ts: '21:46:31', level: 'monitor', msg: '👁 в наблюдение · BTC SHORT: ➖ СОКРАТИЛ 1.18 @ 64,300' },
    { ts: '21:46:10', level: 'monitor', msg: '👁 сейчас копирую · HYPE LONG: сводка 21 сделок ($1,695)' },
    { ts: '21:45:24', level: 'error', msg: 'WS обрыв — переподключаюсь' },
    { ts: '21:45:27', level: 'info', msg: 'WS подключён · подписок 7' },
    { ts: '21:44:50', level: 'skip', msg: '⏭️ пропуск ETHUSDT/SHORT: dead-band $0 < min $20' },
    { ts: '21:44:18', level: 'trade', msg: 'Скопировано · pension-usdt · ETH SHORT ДОЛИВ 0.009 @ 1731.40' },
    { ts: '21:43:02', level: 'target', msg: '🎯 ETH SHORT ДОЛИВ 2.189 @ 1730.00' },
    { ts: '21:42:31', level: 'hb', msg: 'heartbeat: LIVE · ws · эквити $646.96 · позиций 1 · RUNNING' },
  ],

  monitors: [
    { id: 'copynow', name: 'сейчас копирую', addr: '0x1111111111111111111111111111111111111111', onchain: null, perp: '$12,294,577', spot: '$49,986', bank: '$49,986', base: '$12,344,563', upnl: '+$45,000', free: '$8,278,643', mur: 1.1, pos: 7, copying: false, alerts: true, positions: [{ coin: 'HYPE', side: 'LONG', price: '67.41', marginType: 'Cross', lev: '3×', notional: '$170,200', upnl: '+$2,600', upnlPct: '+1.6%', margin: '$56,700' }, { coin: 'BTC', side: 'LONG', price: '64,179', marginType: 'Cross', lev: '5×', notional: '$1,027,000', upnl: '+$1,800', upnlPct: '+0.2%', margin: '$205,400' }] },
    { id: '58bro', name: '58bro.eth', addr: '0x2222222222222222222222222222222222222222', onchain: '58BRO', perp: '$1,020,571', spot: '$2,536,748', bank: '$2,536,748', base: '$3,557,319', upnl: '+$1,544,208', free: '$0', mur: 47.08, pos: 3, copying: false, alerts: true, positions: [] },
    { id: 'pension', name: 'pension-usdt', addr: '0x3333333333333333333333333333333333333333', onchain: 'PENISI', perp: '$32,219,642', spot: '$40,518,131', bank: '$40,518,131', base: '$72,737,773', upnl: '+$3,565,774', free: '$4,502,975', mur: 86.02, pos: 1, copying: true, alerts: true, positions: [{ coin: 'ETH', side: 'SHORT', price: '1,734.31', marginType: 'Cross', lev: '3×', notional: '$86,715,500', upnl: '+$3,565,774', upnlPct: '+12.5%', margin: '$28,905,000' }] },
    { id: 'sving1', name: 'интересный-свинговик', addr: '0x4444444444444444444444444444444444444444', onchain: null, perp: '$999,322', spot: '$1,997,933', bank: '$1,997,933', base: '$2,997,255', upnl: '+$1,081,001', free: '$0', mur: 100, pos: 2, copying: false, alerts: true, positions: [] },
    { id: 'sving2', name: 'интересный-свинг', addr: '0x5555555555555555555555555555555555555555', onchain: null, perp: '$3,858,513', spot: '$7,067,992', bank: '$7,067,992', base: '$10,926,505', upnl: '+$3,466,199', free: '$3,008,433', mur: 9.07, pos: 2, copying: false, alerts: true, positions: [] },
    { id: 'disc', name: 'в наблюдение', addr: '0x6666666666666666666666666666666666666666', onchain: null, perp: '$565,747', spot: '$565,747', bank: '$565,747', base: '$1,131,494', upnl: '+$46,717', free: '$0', mur: 100, pos: 1, copying: false, alerts: true, positions: [{ coin: 'BTC', side: 'SHORT', price: '64,390', marginType: 'Iso', lev: '3×', notional: '$1,513,200', upnl: '+$44,830', upnlPct: '+8.6%', margin: '$504,400' }] },
    { id: 'daytrade', name: 'day-trade', addr: '0x7777777777777777777777777777777777777777', onchain: null, perp: '$0', spot: '$0', bank: '$0', base: '$0', upnl: '+$0', free: '$0', mur: 0, pos: 0, copying: false, alerts: false, positions: [] },
    { id: 'wombat', name: 'wombat', addr: '0x8888888888888888888888888888888888888888', onchain: null, perp: '$187,377', spot: '$665,430', bank: '$665,430', base: '$852,807', upnl: '+$151,495', free: '$0', mur: 37.84, pos: 3, copying: false, alerts: true, positions: [
      { coin: 'BTC', side: 'SHORT', price: '66,850', marginType: 'Cross', lev: '9×', notional: '$1,094,486', upnl: '+$120,000', upnlPct: '+11.0%', margin: '$121,600' },
      { coin: 'SPCX', dex: 'xyz', side: 'SHORT', price: '161.52', marginType: 'Cross', lev: '5×', notional: '$854,189', upnl: '+$31,000', upnlPct: '+3.6%', margin: '$170,800' },
      { coin: 'SP500', dex: 'xyz', side: 'SHORT', price: '7,303', marginType: 'Cross', lev: '3×', notional: '$366,790', upnl: '+$8,400', upnlPct: '+2.3%', margin: '$122,260' },
    ] },
  ],

  accounts: [
    { id: 'main', label: 'Основной', type: 'futures', network: 'mainnet', key_env: 'BINANCE', balance: '$651.18', hasKeys: true },
    { id: 'copy', label: 'Копи-портфель', type: 'copy', network: 'mainnet', key_env: 'BINANCE_COPY', balance: '—', hasKeys: false },
  ],

  // полный конфиг (имена полей 1-в-1 с реальным config.json) — для чтения/записи Настроек
  config: {
    execution_mode: 'maker',
    leverage_mode: 'mirror', fixed_leverage: 3, mirror_max_leverage: 5,
    leverage_cap: 3, max_notional_per_coin_usd: 1000,
    data_mode: 'ws', poll_interval_sec: 5,
    start_skip_open: 'profitable', start_skip_profit_pct: 5,
    favorability_gate: true, favorability_tol_pct: 1,
    auto_sync: false, manage_only_bot_positions: false,
    coin_whitelist: ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'HYPE', 'SUI'],
    monitor_instant_notional_usd: 50000, monitor_coalesce_max_sec: 60, monitor_coalesce_quiet_sec: 45,
    telegram: { enabled: true, chat_id: '', has_token: false },
    auth_enabled: false, has_ui_password: false, has_keys: true,
    active_account: 'main',
    accounts: [
      { id: 'main', label: 'Основной', key_env: 'BINANCE', type: 'futures', network: 'mainnet' },
      { id: 'copy', label: 'Копи-портфель', key_env: 'BINANCE_COPY', type: 'copy', network: 'mainnet',
        overrides: { execution_mode: 'maker', leverage_mode: 'fixed', leverage_cap: 5 } },
    ],
  },

  target: { name: 'pension-usdt', addr: '0x0ddf9bae2af4…', coin: 'ETH', side: 'SHORT', risk: '0.81×', leadRisk: '0.84×', avg: '1,735.48', leadAvg: '1,734.31', live: true },

  overview: { unreal: '+$30.63', leverage: '1.06×', marginUse: '35.32%', yearPnl: '+$137.87', realized: '−$188.56', realizedPct: '−0.22%' },

  journal: {
    curve: CURVE,
    heat: HEAT,
    open: [{
      sym: 'ETHUSDT', perp: 'бессроч', lev: '3×', side: 'ШОРТ',
      size: '−689.31', sizeUnit: 'USDT', entry: '1,735.14', breakeven: '1,746.25', mark: '1,664.99', liq: '3,216.02',
      marginRatio: '0.43%', margin: '229.77', marginType: 'Кросс', pnl: '+29.04', pnlUnit: 'USDT', roi: '+12.6%', funding: '+0.0158', fundingPct: '0.0023%',
    }],
    trades: [
      { dt: '24.06 · 15:46', sym: 'ETHUSDT', side: 'SELL', bot: true, pnl: '+$8.20', price: '1,732.79', fee: '$0.12', turn: '$480' },
      { dt: '24.06 · 12:33', sym: 'BTCUSDT', side: 'BUY', bot: true, pnl: '—', price: '64,179', fee: '$0.08', turn: '$160' },
      { dt: '23.06 · 20:11', sym: 'ETHUSDT', side: 'BUY', bot: true, pnl: '−$5.10', price: '1,728.40', fee: '$0.20', turn: '$390' },
      { dt: '23.06 · 14:02', sym: 'SOLUSDT', side: 'SELL', bot: true, pnl: '+$1.80', price: '142.10', fee: '$0.06', turn: '$210' },
      { dt: '22.06 · 11:02', sym: 'HYPEUSDT', side: 'BUY', bot: false, pnl: '—', price: '67.41', fee: '$0.05', turn: '$120' },
      { dt: '21.06 · 18:30', sym: 'XMRUSDT', side: 'SELL', bot: true, pnl: '−$0.50', price: '307.28', fee: '$0.04', turn: '$95' },
    ],
  },
}
