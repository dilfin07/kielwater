#!/usr/bin/env python3
"""mktable.py — собрать HTML-таблицу по данным enrich.py.

Одна страница без зависимостей: спарклайны рисуются инлайновым SVG, переключатель окна
(неделя/месяц/квартал/год/всё) меняет и кривую, и колонку PnL одновременно — иначе легко
сравнить месячную прибыль с годовой кривой и сделать неверный вывод.

Пометки (звезда, статус, заметка) живут в localStorage: переживают перезагрузку, но
только в этом браузере — для переноса есть выгрузка в CSV.

  python3 mktable.py --src /tmp/enriched.json --out /tmp/traders.html
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/enriched.json")
    ap.add_argument("--out", default="/tmp/traders.html")
    a = ap.parse_args()

    src = json.load(open(a.src))
    rows = []
    for addr, r in src.items():
        if r.get("err"):
            continue
        rows.append({
            "a": addr,
            "cv": {k: [[p[0], round(p[1], 2)] for p in v] for k, v in (r.get("curves") or {}).items()},
            "pnl": r.get("pnl") or {},
            "acct": r.get("acct_now") or 0,
            "perp": r.get("perp") or 0, "spot": r.get("spot") or 0,
            "bank": r.get("bank") or 0, "basis": r.get("basis") or 0,
            "upnl": r.get("upnl") or 0, "free": r.get("free_margin") or 0,
            "mur": r.get("margin_ratio") or 0, "ntl": r.get("ntl") or 0,
            "np": r.get("n_pos") or 0,
            "pos": [{"c": p["coin"], "s": p["szi"], "e": p["entry"], "u": p["upnl"],
                     "l": p["lev"], "q": p["liq"]} for p in (r.get("positions") or [])],
            "st": r.get("style") or "—",
            "hold": r.get("median_hold_min"),
            "fpd": r.get("fills_per_day") or 0,
            "tk": r.get("taker") or 0,
            "cn": r.get("coins") or 0,
            "rt": r.get("round_trips") or 0,
            "vw": r.get("vlm_week") or 0,
            "sh": ((r.get("curve_stats") or {}).get("allTime") or {}).get("sharpe"),
            "sb": ((r.get("curve_stats") or {}).get("allTime") or {}).get("stability"),
            "dd": ((r.get("curve_stats") or {}).get("allTime") or {}).get("cur_dd_pct"),
            "sp": ((r.get("curve_stats") or {}).get("allTime") or {}).get("span_days"),
        })
    rows.sort(key=lambda x: -(x["sh"] or 0))
    data = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)

    html = TEMPLATE.replace("__DATA__", data).replace("__N__", str(len(rows)))
    open(a.out, "w").write(html)
    print("строк: %d → %s (%d КБ)" % (len(rows), a.out, len(html) // 1024))


TEMPLATE = r"""<title>Трейдеры Hyperliquid — отбор по кривой</title>
<style>
  :root{--bg:#0E0F11;--card:#17181B;--line:#26282D;--fg:#D5D7DB;--fg2:#EDEFF2;--dim:#7C848F;
        --blue:#4DA3FF;--green:#3FBF6F;--red:#F0554B;--amber:#E0A21A;--grape:#A78BFA;--gold:#F5C542;
        --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
        --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  body{margin:0;padding:clamp(12px,2vw,26px);background:var(--bg);color:var(--fg);
       font-family:var(--sans);font-size:13.5px;line-height:1.5;-webkit-font-smoothing:antialiased}
  h1{font-size:clamp(18px,2.4vw,24px);font-weight:700;letter-spacing:-.02em;margin:0 0 4px;color:var(--fg2)}
  .sub{color:var(--dim);margin:0 0 14px;font-size:13px}
  .bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
  .grp{display:flex;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:7px;overflow:hidden}
  button{background:var(--card);border:0;color:var(--fg);padding:6px 12px;font-size:13px;
         cursor:pointer;font-family:inherit}
  button:hover{color:var(--fg2)}
  button.on{background:#1E2A38;color:var(--blue)}
  .btn{border:1px solid var(--line);border-radius:6px}
  .btn.act{border-color:var(--green);color:var(--green)}
  input{background:var(--card);border:1px solid var(--line);color:var(--fg);border-radius:6px;
        padding:6px 10px;font-size:13px;font-family:var(--mono);min-width:200px}
  #cnt{color:var(--dim)}
  .tw{overflow:auto;max-height:76vh;border:1px solid var(--line);border-radius:8px}
  table{border-collapse:collapse;width:100%;background:var(--card)}
  th{position:sticky;top:0;z-index:2;background:#1C1E22;text-align:left;padding:8px 10px;
     font-weight:500;color:var(--dim);font-size:11.5px;letter-spacing:.03em;white-space:nowrap;
     cursor:pointer;border-bottom:1px solid var(--line);user-select:none}
  th:hover{color:var(--fg2)} th.pin{cursor:default}
  th.num,td.num{text-align:right}
  td{padding:5px 10px;border-bottom:1px solid #1F2126;white-space:nowrap;font-variant-numeric:tabular-nums}
  tr:hover td{background:#1B1D21} tr.mk td{background:#1A1E1B}
  .ad{font-family:var(--mono);font-size:12px;color:var(--fg2);cursor:pointer}
  .ad:hover{color:var(--blue)}
  .pos{color:var(--green)} .neg{color:var(--red)} .mut{color:var(--dim)}
  .tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:600}
  .t-скальпер{background:#33291A;color:var(--amber)}
  .t-интрадей{background:#1E2A33;color:#69B7E8}
  .t-свинг{background:#1E3026;color:var(--green)}
  .t-позиционный{background:#241E33;color:var(--grape)}
  .t---{background:#232529;color:var(--dim)}
  .star{cursor:pointer;font-size:14px;color:#3A3D44}.star.on{color:var(--gold)}
  .note-in{width:150px;background:transparent;border:1px solid transparent;border-radius:5px;
           padding:2px 6px;font-size:12px;color:var(--fg)}
  .note-in:hover{border-color:var(--line)}.note-in:focus{border-color:var(--blue);background:#111214;outline:none}
  select.st{background:var(--card);border:1px solid var(--line);color:var(--fg);border-radius:5px;font-size:12px;padding:2px 5px}
  a.hd{color:var(--blue);text-decoration:none;font-size:12px}a.hd:hover{text-decoration:underline}
  .exp{background:#131418;padding:10px 14px;border-bottom:1px solid var(--line)}
  .kv{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:8px}
  .kv div{display:flex;flex-direction:column}
  .kv span:first-child{font-size:10.5px;color:var(--dim)}
  .kv span:last-child{font-size:13px;color:var(--fg2)}
  .pz{display:flex;gap:10px;flex-wrap:wrap}
  .pz div{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:7px 10px;font-size:12px}
  .note{color:var(--dim);font-size:12.5px;margin:12px 0 0;max-width:90ch}
  .note b{color:var(--fg2)}
</style>

<h1>Трейдеры Hyperliquid — отбор по форме кривой</h1>
<p class="sub">__N__ адресов: положительная кривая, шарп &gt; 1, ≥60 % плюсовых отрезков истории,
просадка от пика &lt; 25 %, счёт от $50k, оборот за неделю от $200k, история от полугода.
Отобрано из 6 538 измеренных.</p>

<div class="bar">
  <span class="mut">окно:</span>
  <div class="grp" id="win">
    <button data-w="week">неделя</button>
    <button data-w="month">месяц</button>
    <button data-w="quarter">квартал</button>
    <button data-w="year">год</button>
    <button data-w="allTime" class="on">всё время</button>
  </div>
  <span class="mut" style="margin-left:8px">стиль:</span>
  <div class="grp" id="sty">
    <button data-s="" class="on">все</button>
    <button data-s="скальпер">скальпер</button>
    <button data-s="интрадей">интрадей</button>
    <button data-s="свинг">свинг</button>
    <button data-s="позиционный">позиционный</button>
  </div>
  <button class="btn" id="onlypos">только с позициями</button>
  <button class="btn" id="onlymark">★ отмеченные</button>
  <input id="q" placeholder="поиск по адресу…">
  <span id="cnt"></span>
  <span style="flex:1"></span>
  <button class="btn act" id="copy">Скопировать отмеченные</button>
  <button class="btn" id="csv">CSV в буфер</button>
</div>

<div class="tw"><table>
<thead><tr>
  <th class="pin">★</th><th data-k="a">адрес</th><th class="pin">кривая</th>
  <th class="num" data-k="_pnl">PnL окна</th><th class="num" data-k="acct">капитал</th>
  <th class="num" data-k="np">поз.</th><th class="num" data-k="upnl">uPnL</th>
  <th data-k="st">стиль</th><th class="num" data-k="hold">удержание</th>
  <th class="num" data-k="sh">шарп</th><th class="num" data-k="sb">устойч</th>
  <th class="num" data-k="mur">маржа</th><th class="num" data-k="sp">дней</th>
  <th class="pin">заметка</th><th class="pin"></th>
</tr></thead><tbody id="tb"></tbody></table></div>

<p class="note"><b>Окно меняет и кривую, и PnL одновременно</b> — иначе легко сравнить месячную
прибыль с годовой картинкой. Квартал и год нарезаны из общей истории, неделя и месяц — готовые
ряды биржи.</p>
<p class="note"><b>Стиль</b> — по медианному удержанию позиции: до часа скальпер, до восьми
интрадей, до трёх суток свинг, дальше позиционный. За скальпером копир с задержкой не успеет.
Клик по строке раскрывает позиции и детали счёта.</p>

<script>
const R = __DATA__;
const KEY = 'hl_traders_marks';
let store = {}; try { store = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) {} };
const g = a => store[a] || {};
const marked = a => { const s = g(a); return !!(s.fav || s.st || (s.note || '').trim()); };

let win = 'allTime', sty = '', q = '', onlyPos = false, onlyMark = false, sortK = 'sh', dir = -1;
const tb = document.getElementById('tb'), cnt = document.getElementById('cnt');
const money = n => (n < 0 ? '−$' : '$') + Math.abs(Math.round(n)).toLocaleString('ru-RU').replace(/,/g, ' ');
const hold = m => m == null ? '—' : m < 60 ? Math.round(m) + ' м' : m < 1440 ? (m / 60).toFixed(1) + ' ч' : (m / 1440).toFixed(1) + ' д';

function spark(cv, w, width = 150, height = 34) {
  const c = (cv || {})[w];
  if (!c || c.length < 2) return '<span class="mut" style="font-size:11px">нет данных</span>';
  const ys = c.map(p => p[1]), lo = Math.min(...ys), hi = Math.max(...ys);
  const rng = (hi - lo) || 1, n = c.length;
  const X = i => (i / (n - 1)) * (width - 2) + 1;
  const Y = v => height - 2 - ((v - lo) / rng) * (height - 4);
  const d = c.map((p, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(' ');
  const up = ys[ys.length - 1] >= ys[0];
  const col = up ? 'var(--green)' : 'var(--red)';
  const zeroY = (lo < 0 && hi > 0) ? Y(0).toFixed(1) : null;
  return `<svg width="${width}" height="${height}" style="display:block">
    ${zeroY ? `<line x1="0" x2="${width}" y1="${zeroY}" y2="${zeroY}" stroke="var(--line)" stroke-width="1"/>` : ''}
    <path d="${d} L${X(n - 1).toFixed(1)} ${height} L${X(0).toFixed(1)} ${height} Z" fill="${col}" opacity=".13"/>
    <path d="${d}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/>
    <circle cx="${X(n - 1).toFixed(1)}" cy="${Y(ys[ys.length - 1]).toFixed(1)}" r="2.2" fill="${col}"/>
  </svg>`;
}

function val(r, k) { return k === '_pnl' ? (r.pnl[win] ?? -1e18) : r[k]; }

function visible() {
  return R.filter(r => (!sty || r.st === sty) && (!q || r.a.toLowerCase().includes(q))
    && (!onlyPos || r.np > 0) && (!onlyMark || marked(r.a)));
}

function render() {
  const rows = visible().sort((x, y) => {
    const A = val(x, sortK), B = val(y, sortK);
    return (typeof A === 'number' ? (A || 0) - (B || 0) : String(A).localeCompare(String(B))) * dir;
  });
  cnt.textContent = rows.length + ' из ' + R.length;
  tb.innerHTML = rows.map(r => {
    const s = g(r.a), p = r.pnl[win];
    const opts = ['', 'смотреть', 'в копир', 'мимо'].map(v =>
      `<option value="${v}"${s.st === v ? ' selected' : ''}>${v || '—'}</option>`).join('');
    return `<tr class="${marked(r.a) ? 'mk' : ''}" data-a="${r.a}">
      <td><span class="star ${s.fav ? 'on' : ''}" data-act="fav">${s.fav ? '★' : '☆'}</span></td>
      <td><span class="ad" data-act="copy">${r.a.slice(0, 8)}…${r.a.slice(-4)}</span></td>
      <td data-act="exp">${spark(r.cv, win)}</td>
      <td class="num ${p == null ? 'mut' : p >= 0 ? 'pos' : 'neg'}">${p == null ? '—' : money(p)}</td>
      <td class="num">${money(r.acct)}</td>
      <td class="num ${r.np ? '' : 'mut'}">${r.np}</td>
      <td class="num ${r.upnl >= 0 ? 'pos' : 'neg'}">${r.np ? money(r.upnl) : '—'}</td>
      <td><span class="tag t-${r.st}">${r.st}</span></td>
      <td class="num">${hold(r.hold)}</td>
      <td class="num">${r.sh ?? '—'}</td>
      <td class="num">${r.sb ?? '—'}%</td>
      <td class="num">${r.mur}%</td>
      <td class="num mut">${Math.round(r.sp || 0)}</td>
      <td><input class="note-in" data-act="note" placeholder="—" value="${(s.note || '').replace(/"/g, '&quot;')}"></td>
      <td><a class="hd" href="https://hyperdash.com/address/${r.a}" target="_blank" rel="noreferrer">Hyperdash ↗</a></td>
    </tr>`;
  }).join('');
}

tb.addEventListener('click', e => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const tr = el.closest('tr'), a = tr.dataset.a, act = el.dataset.act;
  if (act === 'fav') { store[a] = { ...g(a), fav: !g(a).fav }; save(); render(); }
  else if (act === 'copy') { navigator.clipboard.writeText(a); el.style.color = 'var(--green)'; setTimeout(() => el.style.color = '', 700); }
  else if (act === 'exp') {
    const nx = tr.nextElementSibling;
    if (nx && nx.classList.contains('expr')) { nx.remove(); return; }
    const r = R.find(x => x.a === a);
    const kv = [['перп', money(r.perp)], ['спот', money(r.spot)], ['банк', money(r.bank)],
      ['база пропорции', money(r.basis)], ['свободная маржа', money(r.free)], ['нотионал', money(r.ntl)],
      ['монет', r.cn], ['сделок в день', r.fpd], ['доля тейкера', r.tk], ['раундтрипов', r.rt],
      ['оборот/нед', money(r.vw)], ['просадка сейчас', (r.dd ?? '—') + '%']]
      .map(([k, v]) => `<div><span>${k}</span><span>${v}</span></div>`).join('');
    const pz = r.pos.length ? r.pos.map(p =>
      `<div><b>${p.c}</b> ${p.s > 0 ? 'LONG' : 'SHORT'} ${Math.abs(p.s)} · вход ${p.e} · ${p.l}× ·
       <span class="${p.u >= 0 ? 'pos' : 'neg'}">${money(p.u)}</span> · ликв ${Math.round(p.q)}</div>`).join('')
      : '<div class="mut">открытых позиций нет</div>';
    tr.insertAdjacentHTML('afterend', `<tr class="expr"><td colspan="15" class="exp"><div class="kv">${kv}</div><div class="pz">${pz}</div></td></tr>`);
  }
});
tb.addEventListener('change', e => {
  const el = e.target.closest('[data-act="st"]'); if (!el) return;
  const a = el.closest('tr').dataset.a; store[a] = { ...g(a), st: el.value }; save(); render();
});
tb.addEventListener('input', e => {
  const el = e.target.closest('[data-act="note"]'); if (!el) return;
  const tr = el.closest('tr'); store[tr.dataset.a] = { ...g(tr.dataset.a), note: el.value }; save();
  tr.classList.toggle('mk', marked(tr.dataset.a));
});
document.querySelectorAll('#win button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#win button').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); win = b.dataset.w; render();
});
document.querySelectorAll('#sty button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#sty button').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); sty = b.dataset.s; render();
});
document.getElementById('onlypos').onclick = e => { onlyPos = !onlyPos; e.target.classList.toggle('act', onlyPos); render(); };
document.getElementById('onlymark').onclick = e => { onlyMark = !onlyMark; e.target.classList.toggle('act', onlyMark); render(); };
document.getElementById('q').oninput = e => { q = e.target.value.trim().toLowerCase(); render(); };
document.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => {
  const k = th.dataset.k; dir = (k === sortK) ? -dir : -1; sortK = k; render();
});
document.getElementById('copy').onclick = e => {
  const l = R.filter(r => marked(r.a)).map(r => r.a).join('\n');
  navigator.clipboard.writeText(l);
  e.target.textContent = 'Скопировано: ' + (l ? l.split('\n').length : 0);
  setTimeout(() => e.target.textContent = 'Скопировать отмеченные', 1400);
};
document.getElementById('csv').onclick = () => {
  const h = 'address,pnl_week,pnl_month,pnl_quarter,pnl_year,pnl_all,acct,positions,upnl,style,hold_min,sharpe,stability,margin_pct,days,fav,status,note';
  const b = R.map(r => { const s = g(r.a);
    return [r.a, r.pnl.week ?? '', r.pnl.month ?? '', r.pnl.quarter ?? '', r.pnl.year ?? '', r.pnl.allTime ?? '',
      r.acct, r.np, r.upnl, r.st, r.hold ?? '', r.sh ?? '', r.sb ?? '', r.mur, Math.round(r.sp || 0),
      s.fav ? 1 : 0, s.st || '', '"' + (s.note || '').replace(/"/g, '""') + '"'].join(',');
  }).join('\n');
  navigator.clipboard.writeText(h + '\n' + b);
  const btn = document.getElementById('csv');
  btn.textContent = 'CSV скопирован'; setTimeout(() => btn.textContent = 'CSV в буфер', 1500);
};
render();
</script>
"""


if __name__ == "__main__":
    main()
