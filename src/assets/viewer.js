/* WARNO Replay Analyzer -- offline viewer.
   DATA is injected above this script by the analyzer. No network access anywhere. */
(function () {
'use strict';

var D = window.DATA;
var M = D.matches || [];
var DIV = D.divisions || {};
var UNI = D.units || {};
var EMB = D.emblems || {};
var AVA = D.avatars || {};

/* ------------------------------------------------------------------ helpers */

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function el(tag, attrs, kids) {
  var n = document.createElement(tag);
  for (var k in attrs || {}) {
    if (k === 'class') n.className = attrs[k];
    else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  }
  (kids || []).forEach(function (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return n;
}
var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtDate(iso) { var d = new Date(iso); return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
function fmtTime(iso) { var d = new Date(iso); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); }
function pad(n) { return (n < 10 ? '0' : '') + n; }
function fmtDur(s) { return s == null ? '—' : Math.floor(s / 60) + ':' + pad(s % 60); }
function wrClass(v) { return v == null ? 'neutral' : v >= 55 ? 'win' : v <= 45 ? 'loss' : 'neutral'; }

/* Names come out of the game's own string table, so they are shown verbatim --
   re-casing them turns "K.d.A." into "K.D.A." and "DIVMOB" into "Divmob". */
function division(id) {
  var d = DIV[String(id)];
  return {
    name: (d && d.name) || (id == null ? '—' : 'Division #' + id),
    alliance: (d && d.alliance) || '', country: (d && d.country) || '', type: (d && d.type) || '',
    emblem: (d && EMB[d.emblem]) || ''
  };
}
function unit(id) {
  var u = UNI[String(id)];
  return {
    name: (u && u.name) || '#' + id,
    cat: (u && u.category) || 'other', country: (u && u.country) || ''
  };
}
function dot(alliance) { return '<span class="dot ' + esc(alliance || '') + '"></span>'; }
/* Steam avatar, when --avatars was used and the profile resolved. */
function face(steamId, size) {
  var b64 = steamId && AVA[steamId];
  if (!b64) return '';
  return '<img class="ava" alt="" style="width:' + size + 'px;height:' + size
    + 'px;" src="data:image/jpeg;base64,' + b64 + '">';
}

/* The division's own emblem when we have it, otherwise the alliance colour. */
function badge(d, size) {
  if (!d.emblem) return dot(d.alliance);
  return '<img class="emb" alt="" style="width:' + size + 'px;height:' + size + 'px;" src="data:image/png;base64,'
    + d.emblem + '">';
}

/* ------------------------------------------------------------------- state */

/* Defaults aim at "real games I played": no AI, no rage-quits in the first ten
   minutes, nothing without a result, nothing I only downloaded. */
function freshFilters() {
  return {
    q: '', types: { ranked: true, casual: true, vs_ai: false },
    results: { win: true, loss: true, draw: true, aborted: false, none: false },
    minDur: 10, divA: [], divB: [], plA: [], plB: [], map: '', from: '', to: '',
    sizes: { 1: true, 2: true, 3: true, 4: true },
    oppElo: null            /* [min, max]; null = whole range */
  };
}

/* Mean ELO of the players facing `p`, ignoring AI and unrated accounts. */
function opponentElo(m, p) {
  if (!p) return null;
  var sum = 0, n = 0;
  m.players.forEach(function (x) {
    if (x.alliance !== p.alliance && !x.ai && x.elo != null) { sum += x.elo; n++; }
  });
  return n ? sum / n : null;
}

/* Slider bounds, from ranked matches only -- that is where the filter bites. */
var ELO_RANGE = (function () {
  var lo = null, hi = null;
  M.forEach(function (m) {
    if (m.type !== 'ranked') return;
    m.players.forEach(function (p) {
      if (p.ai || p.elo == null) return;
      if (lo == null || p.elo < lo) lo = p.elo;
      if (hi == null || p.elo > hi) hi = p.elo;
    });
  });
  if (lo == null) return [0, 0];
  return [Math.floor(lo / 50) * 50, Math.ceil(hi / 50) * 50];
})();
var S = {
  f: freshFilters(), sort: { key: 'date', dir: -1 }, page: 0, pageSize: 50,
  expanded: null, openDecks: {}, tabs: [], active: 'matches', owner: null,
  reportSort: {}          /* report table bucket -> {key, dir} */
};

/* Which of these players is "you"?  Best evidence first: a Steam account that
   has signed in on this PC, then who saved the most replays, then who simply
   shows up most often. */
function detectOwner() {
  var steam = {}, byName = {}, saved = {}, seen = {}, appear = {};
  (D.localSteamIds || []).forEach(function (s) { steam[s] = true; });
  var matched = null;
  M.forEach(function (m) {
    m.players.forEach(function (p) {
      if (p.ai || !p.userId) return;
      if (!byName[p.userId]) byName[p.userId] = p.name;   /* matches are newest-first */
      appear[p.userId] = (appear[p.userId] || 0) + 1;
      if (!matched && p.steamId && steam[p.steamId]) matched = p.userId;
      seen[p.userId] = true;
    });
    var lp = m.localPlayer != null ? m.players[m.localPlayer] : null;
    if (lp && !lp.ai && lp.userId) saved[lp.userId] = (saved[lp.userId] || 0) + 1;
  });
  if (matched) return { id: matched, name: byName[matched] };
  var pool = Object.keys(saved).length ? saved : appear, best = null;
  for (var id in pool) if (!best || pool[id] > pool[best]) best = id;
  return best ? { id: best, name: byName[best] } : { id: '', name: '—' };
}

/* Nicknames change; matches arrive newest-first, so the first one wins. */
var PLAYERS = (function () {
  var by = {};
  M.forEach(function (m) {
    m.players.forEach(function (p) {
      if (p.ai || !p.userId) return;
      var e = by[p.userId] || (by[p.userId] = { id: p.userId, name: p.name, steamId: p.steamId, n: 0 });
      e.n++;
      if (!e.steamId) e.steamId = p.steamId;
    });
  });
  return Object.keys(by).map(function (k) { return by[k]; })
    .sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name); });
})();

var PLAYER_BY_ID = (function () {
  var m = {};
  PLAYERS.forEach(function (p) { m[p.id] = p.name; });
  return m;
})();
function playerName(id) { return PLAYER_BY_ID[id] || ''; }

var DIVOPTS = (function () {
  var seen = {};
  M.forEach(function (m) {
    m.players.forEach(function (p) {
      if (p.deck && p.deck.divisionId != null) seen[p.deck.divisionId] = true;
    });
  });
  return Object.keys(seen).map(function (id) {
    var d = division(id);
    return { id: id, name: d.name, alliance: d.alliance, emblem: d.emblem, div: d };
  }).sort(function (a, b) { return a.name.localeCompare(b.name); });
})();

var MAPOPTS = (function () {
  var seen = {};
  M.forEach(function (m) { seen[m.map.name] = true; });
  return Object.keys(seen).sort();
})();

var TYPECOUNT = (function () {
  var c = { ranked: 0, casual: 0, vs_ai: 0 };
  M.forEach(function (m) { c[m.type] = (c[m.type] || 0) + 1; });
  return c;
})();

/* --------------------------------------------------------------- selectors */

function me(m) {
  var id = S.owner.id;
  for (var i = 0; i < m.players.length; i++) if (m.players[i].userId === id) return m.players[i];
  return null;
}
function outcome(m, p) {
  if (!p) return 'none';
  if (!m.result.present || m.result.winnerAlliance == null) return 'aborted';
  if (m.result.winnerAlliance === 'draw') return 'draw';
  return p.alliance === m.result.winnerAlliance ? 'win' : 'loss';
}
/* Team A vs team B, either way round: every listed key must sit on one side. */
function sidesMatch(m, listA, listB, keyOf) {
  if (!listA.length && !listB.length) return true;
  var sides = {};
  m.players.forEach(function (p) {
    var k = keyOf(p);
    if (k != null) (sides[p.alliance] = sides[p.alliance] || {})[k] = true;
  });
  var keys = Object.keys(sides);
  function has(side, list) { return list.every(function (v) { return side && side[v]; }); }
  if (!listA.length || !listB.length) {
    var list = listA.length ? listA : listB;
    return keys.some(function (k) { return has(sides[k], list); });
  }
  for (var i = 0; i < keys.length; i++)
    for (var j = 0; j < keys.length; j++)
      if (i !== j && has(sides[keys[i]], listA) && has(sides[keys[j]], listB)) return true;
  return false;
}
function passes(m, f) {
  if (!f.types[m.type]) return false;
  if (!f.sizes[Math.min(4, m.teamSize || 1)]) return false;
  if (!f.results[outcome(m, me(m))]) return false;
  if (f.minDur > 0 && m.result.duration != null && m.result.duration < f.minDur * 60) return false;
  /* Opponent ELO only means something on the ladder, so leave other types alone. */
  if (f.oppElo && m.type === 'ranked') {
    var oe = opponentElo(m, me(m));
    if (oe != null && (oe < f.oppElo[0] || oe > f.oppElo[1])) return false;
  }
  if (f.q) {
    var q = f.q.toLowerCase();
    var hit = m.players.some(function (p) {
      return p.name.toLowerCase().indexOf(q) >= 0 || p.userId === f.q;
    });
    if (!hit) return false;
  }
  if (!sidesMatch(m, f.divA, f.divB, function (p) {
    return p.deck && p.deck.divisionId != null ? String(p.deck.divisionId) : null;
  })) return false;
  if (!sidesMatch(m, f.plA, f.plB, function (p) { return p.userId || null; })) return false;
  if (f.map && m.map.name !== f.map) return false;
  var day = m.date.slice(0, 10);
  if (f.from && day < f.from) return false;
  if (f.to && day > f.to) return false;
  return true;
}
function sortVal(m, key) {
  var p = me(m);
  switch (key) {
    case 'date': return m.date;
    case 'type': return m.type;
    case 'map': return m.map.name;
    case 'size': return m.teamSize || 1;
    case 'myDiv': return p && p.deck ? division(p.deck.divisionId).name : '';
    case 'oppDiv': {
      if (!p) return '';
      var o = m.players.filter(function (x) { return x.alliance !== p.alliance && x.deck; })[0];
      return o ? division(o.deck.divisionId).name : '';
    }
    case 'result': return { win: 3, draw: 2, loss: 1, aborted: 0, none: -1 }[outcome(m, p)];
    case 'dur': return m.result.duration == null ? -1 : m.result.duration;
    case 'elo': return p && p.elo != null ? p.elo : -1;
  }
  return 0;
}
var _cacheKey = null, _cached = null;
function filtered() {
  var key = JSON.stringify(S.f) + '|' + S.sort.key + '|' + S.sort.dir + '|' + S.owner.id;
  if (key === _cacheKey) return _cached;
  var list = M.filter(function (m) { return passes(m, S.f); });
  var k = S.sort.key, dir = S.sort.dir;
  list.sort(function (a, b) {
    var x = sortVal(a, k), y = sortVal(b, k);
    if (x < y) return -dir;
    if (x > y) return dir;
    return b.date.localeCompare(a.date);
  });
  _cacheKey = key; _cached = list;
  return list;
}

/* ------------------------------------------------------------------- decks */

var CAT_ORDER = ['log', 'inf', 'art', 'tank', 'rec', 'aa', 'hel', 'air', 'tr', 'other'];
var CAT_LABEL = {
  log: 'LOGISTICS', inf: 'INFANTRY', art: 'ARTILLERY', tank: 'TANKS', rec: 'RECON',
  aa: 'ANTI-AIR', hel: 'HELICOPTERS', air: 'AIRCRAFT', tr: 'TRANSPORTS', other: 'OTHER'
};
var VETCOL = ['var(--faint2)', 'var(--vet1)', 'var(--vet2)', 'var(--vet3)'];

function deckGroups(deck) {
  if (!deck || deck.error || !deck.cards) return [];
  var byCat = {};
  deck.cards.forEach(function (c) {
    var u = unit(c[1]);
    var g = byCat[u.cat] || (byCat[u.cat] = { n: 0, items: {}, order: [] });
    var key = c[1] + '|' + c[0] + '|' + c[2];
    g.n++;
    if (!g.items[key]) {
      g.items[key] = { name: u.name, xp: c[0], tr: c[2] ? unit(c[2]).name : null, n: 0 };
      g.order.push(key);
    }
    g.items[key].n++;
  });
  return CAT_ORDER.filter(function (c) { return byCat[c]; }).map(function (c) {
    var g = byCat[c];
    var items = g.order.map(function (k) { return g.items[k]; })
      .sort(function (a, b) { return b.xp - a.xp || a.name.localeCompare(b.name); });
    return { label: CAT_LABEL[c], count: g.n, items: items };
  });
}
function deckSummary(deck) {
  if (!deck || deck.error || !deck.cards || !deck.cards.length) return null;
  var cards = deck.cards, bucket = [0, 0, 0, 0], sum = 0;
  cards.forEach(function (c) { var v = Math.min(3, c[0]); bucket[v]++; sum += v; });
  var parts = [];
  if (bucket[3]) parts.push(bucket[3] + ' elite');
  if (bucket[2]) parts.push(bucket[2] + ' veteran');
  if (bucket[1]) parts.push(bucket[1] + ' hardened');
  if (bucket[0]) parts.push(bucket[0] + ' trained');
  return { total: cards.length, avg: (sum / cards.length).toFixed(2), summary: parts.join(' · ') };
}

/* ------------------------------------------------------------------ sidebar */

var side = {};   /* live nodes we update in place so typing never loses focus */

function buildSidebar() {
  var root = el('div', { class: 'card side' });

  function section(kids) { var s = el('div', { class: 'sec' }, kids); root.appendChild(s); return s; }
  function label(t) { return el('div', { class: 'lbl' }, [t]); }

  section([
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;' }, [
      el('div', { class: 'eyebrow' }, ['FILTERS']),
      el('div', { class: 'link', onclick: function () { S.f = freshFilters(); S.page = 0; syncSidebar(); render(); } }, ['Reset all'])
    ]),
    label('Perspective'),
    side.owner = el('select', {
      onchange: function () {
        var v = this.value;
        var p = PLAYERS.filter(function (x) { return x.id === v; })[0];
        if (p) { S.owner = { id: p.id, name: p.name }; S.page = 0; syncSidebar(); render(); }
      }
    }),
    side.ownerReport = el('button', {
      class: 'target',
      onclick: function () { openReport(S.owner.id, S.owner.name); }
    }),
    el('div', { class: 'hint', style: 'margin-top:4px;' }, ['Win/loss and the report tally are read from this player’s side.'])
  ]);

  section([
    label('Player search'),
    side.q = el('input', {
      type: 'text', placeholder: 'Contains… (nick or Eugen ID)',
      oninput: function () { S.f.q = this.value; S.page = 0; syncTarget(); render(); }
    }),
    side.qPick = el('select', {
      style: 'margin-top:5px;',
      onchange: function () {
        var v = this.value; this.value = '';
        var p = PLAYERS.filter(function (x) { return x.id === v; })[0];
        if (p) { S.f.q = p.name; side.q.value = p.name; S.page = 0; syncTarget(); render(); }
      }
    }),
    side.target = el('button', {
      class: 'target', style: 'display:none;',
      onclick: function () { if (side.targetPlayer) openReport(side.targetPlayer.id, side.targetPlayer.name); }
    }),
    side.qHint = el('div', { class: 'hint', style: 'margin-top:4px;' }, ['Matches any player in the lobby'])
  ]);

  side.plA = sideList('plA', 'TEAM A', 'player');
  side.plB = sideList('plB', 'TEAM B', 'player');
  section([
    el('div', { style: 'display:flex;align-items:baseline;justify-content:space-between;margin-bottom:5px;' }, [
      el('div', { class: 'lbl', style: 'margin:0;' }, ['Players by side']),
      el('div', { class: 'hint' }, ['sides interchangeable'])
    ]),
    side.plA.node, side.plB.node,
    el('div', { class: 'hint' }, ['Leave empty to ignore. Fill both to pin an exact matchup.'])
  ]);

  section([
    label('Match type'),
    side.types = el('div', {})
  ]);
  section([
    label('My result'),
    side.results = el('div', {})
  ]);

  section([
    el('div', { style: 'display:flex;justify-content:space-between;' }, [
      el('div', { class: 'lbl' }, ['Min duration']),
      side.durVal = el('div', { class: 'mono', style: 'font-size:11px;color:var(--accent);' }, ['off'])
    ]),
    side.dur = el('input', {
      type: 'range', min: '0', max: '40', step: '1', value: '0',
      oninput: function () { S.f.minDur = +this.value; S.page = 0; side.durVal.textContent = S.f.minDur ? '≥ ' + S.f.minDur + ' min' : 'off'; render(); }
    }),
    el('div', { class: 'hint' }, ['Applies to matches with a recorded time'])
  ]);

  section([
    el('div', { style: 'display:flex;justify-content:space-between;' }, [
      el('div', { class: 'lbl' }, ['Opponent ELO']),
      side.oppEloVal = el('div', { class: 'mono', style: 'font-size:11px;color:var(--accent);' }, ['off'])
    ]),
    side.oppEloLo = el('input', {
      type: 'range', min: ELO_RANGE[0], max: ELO_RANGE[1], step: '25', value: ELO_RANGE[0],
      oninput: function () { onEloSlide(+this.value, null); }
    }),
    side.oppEloHi = el('input', {
      type: 'range', min: ELO_RANGE[0], max: ELO_RANGE[1], step: '25', value: ELO_RANGE[1],
      oninput: function () { onEloSlide(null, +this.value); }
    }),
    el('div', { class: 'hint' }, ['Ranked matches only — other match types are left untouched'])
  ]);

  side.divA = sideList('divA', 'TEAM A', 'division');
  side.divB = sideList('divB', 'TEAM B', 'division');
  section([
    el('div', { style: 'display:flex;align-items:baseline;justify-content:space-between;margin-bottom:5px;' }, [
      el('div', { class: 'lbl', style: 'margin:0;' }, ['Divisions in match']),
      el('div', { class: 'hint' }, ['sides interchangeable'])
    ]),
    side.divA.node, side.divB.node,
    el('div', { class: 'hint' }, ['All listed divisions must be present on their side.'])
  ]);

  section([
    label('Map'),
    side.map = el('select', { onchange: function () { S.f.map = this.value; S.page = 0; render(); } })
  ]);

  section([
    label('Match size'),
    side.sizes = el('div', { class: 'sizes' })
  ]);

  section([
    label('Date range'),
    el('div', { style: 'display:flex;flex-direction:column;gap:5px;' }, [
      side.from = el('input', { type: 'date', onchange: function () { S.f.from = this.value; S.page = 0; render(); } }),
      side.to = el('input', { type: 'date', onchange: function () { S.f.to = this.value; S.page = 0; render(); } })
    ])
  ]);

  /* one-time option lists */
  fill(side.owner, PLAYERS.map(function (p) { return { v: p.id, t: p.name + ' — ' + p.n + (p.n === 1 ? ' game' : ' games') }; }));
  fill(side.qPick, [{ v: '', t: 'Or pick from list (by games)…' }].concat(
    PLAYERS.map(function (p) { return { v: p.id, t: p.name + ' — ' + p.n + (p.n === 1 ? ' game' : ' games') }; })));
  fill(side.map, [{ v: '', t: 'Any map' }].concat(MAPOPTS.map(function (m) { return { v: m, t: m }; })));

  [1, 2, 3, 4].forEach(function (n) {
    side.sizes.appendChild(el('button', {
      'data-size': n,
      onclick: function () { S.f.sizes[n] = !S.f.sizes[n]; S.page = 0; syncSidebar(); render(); }
    }, [n + 'v' + n]));
  });

  [['ranked', 'Ranked (1v1 duel)'], ['casual', 'Casual multiplayer'], ['vs_ai', 'vs AI / solo']]
    .forEach(function (t) {
      var cb = el('input', {
        type: 'checkbox', checked: 'checked',
        onchange: function () { S.f.types[t[0]] = this.checked; S.page = 0; render(); }
      });
      side.types.appendChild(el('label', { class: 'check' }, [
        cb, el('span', {}, [t[1]]), el('span', { class: 'n' }, [String(TYPECOUNT[t[0]] || 0)])
      ]));
    });

  [['win', 'Wins'], ['loss', 'Losses'], ['draw', 'Draws'], ['aborted', 'Aborted / no result'],
   ['none', 'Not my match']].forEach(function (t) {
    var cb = el('input', {
      type: 'checkbox', checked: 'checked',
      onchange: function () { S.f.results[t[0]] = this.checked; S.page = 0; render(); }
    });
    side.results.appendChild(el('label', { class: 'check' }, [cb, el('span', {}, [t[1]])]));
  });

  return root;
}

/* Two plain sliders standing in for a range control; keep them from crossing. */
function onEloSlide(lo, hi) {
  var cur = S.f.oppElo || ELO_RANGE.slice();
  if (lo != null) cur = [Math.min(lo, cur[1]), cur[1]];
  if (hi != null) cur = [cur[0], Math.max(hi, cur[0])];
  S.f.oppElo = (cur[0] <= ELO_RANGE[0] && cur[1] >= ELO_RANGE[1]) ? null : cur;
  S.page = 0;
  syncEloSliders();
  render();
}

function syncEloSliders() {
  var r = S.f.oppElo || ELO_RANGE;
  side.oppEloLo.value = r[0];
  side.oppEloHi.value = r[1];
  side.oppEloVal.textContent = S.f.oppElo ? (r[0] + ' – ' + r[1]) : 'off';
}

function fill(select, opts) {
  select.innerHTML = opts.map(function (o) {
    return '<option value="' + esc(o.v) + '">' + esc(o.t) + '</option>';
  }).join('');
}

/* A chip row + "add" control bound to one of the side-filter arrays.
   Players use a native <select>; divisions get a custom list, because an
   <option> cannot carry the division emblem. */
function sideList(key, label, kind) {
  var chips = el('div', { class: 'chips' });
  var sl = { chips: chips, key: key, kind: kind };

  function pick(v) {
    if (v && S.f[key].indexOf(v) < 0) { S.f[key].push(v); S.page = 0; syncSidebar(); render(); }
  }

  var control;
  if (kind === 'division') {
    sl.button = el('button', {
      class: 'picker-btn',
      onclick: function () { togglePicker(sl); }
    });
    sl.search = el('input', {
      type: 'text', class: 'picker-search', placeholder: 'Filter divisions…',
      oninput: function () { filterPicker(sl, this.value); }
    });
    sl.list = el('div', { class: 'picker-list' });
    sl.panel = el('div', { class: 'picker-panel', hidden: 'hidden' }, [sl.search, sl.list]);
    buildPickerList(sl, pick);
    control = el('div', { class: 'picker' }, [sl.button, sl.panel]);
  } else {
    sl.sel = el('select', {
      onchange: function () { var v = this.value; this.value = ''; pick(v); }
    });
    control = sl.sel;
  }

  sl.node = el('div', { style: 'margin-bottom:7px;' }, [
    el('div', { style: 'font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--faint);margin-bottom:4px;' }, [label]),
    chips, control
  ]);
  return sl;
}

function buildPickerList(sl, pick) {
  [['NATO', 'NATO'], ['PACT', 'PACT'], ['', 'Unknown alliance']].forEach(function (g) {
    var opts = DIVOPTS.filter(function (o) { return (o.alliance || '') === g[0]; });
    if (!opts.length) return;
    sl.list.appendChild(el('div', { class: 'picker-group' }, [g[1]]));
    opts.forEach(function (o) {
      var row = el('button', {
        class: 'picker-opt', 'data-name': o.name.toLowerCase(), 'data-id': o.id,
        onclick: function () { closePicker(); pick(o.id); }
      });
      row.innerHTML = badge(o.div, 20) + '<span>' + esc(o.name) + '</span>';
      sl.list.appendChild(row);
    });
  });
}

var openPicker = null;
function closePicker() {
  if (openPicker) { openPicker.panel.hidden = true; openPicker = null; }
}
function togglePicker(sl) {
  var wasOpen = openPicker === sl;
  closePicker();
  if (wasOpen) return;
  sl.panel.hidden = false;
  openPicker = sl;
  sl.search.value = '';
  filterPicker(sl, '');
  sl.search.focus();
}
function filterPicker(sl, text) {
  var q = text.trim().toLowerCase();
  var visible = 0;
  Array.prototype.forEach.call(sl.list.children, function (node) {
    if (node.className === 'picker-group') { node.hidden = !!q; return; }
    var hit = !q || node.getAttribute('data-name').indexOf(q) >= 0;
    node.hidden = !hit;
    if (hit) visible++;
  });
  sl.list.scrollTop = 0;
  return visible;
}

function syncSideList(sl) {
  var list = S.f[sl.key];
  var isDiv = sl.kind === 'division';
  sl.chips.innerHTML = '';
  sl.chips.style.display = list.length ? '' : 'none';
  list.forEach(function (v) {
    var d = isDiv ? division(v) : null;
    var name = isDiv ? d.name : (PLAYERS.filter(function (p) { return p.id === v; })[0] || { name: v }).name;
    var chip = el('div', { class: 'chip', onclick: function () {
      S.f[sl.key] = S.f[sl.key].filter(function (x) { return x !== v; });
      S.page = 0; syncSidebar(); render();
    } }, []);
    chip.innerHTML = (isDiv ? badge(d, 16) : '') + '<span>' + esc(name) + '</span><span class="x">×</span>';
    sl.chips.appendChild(chip);
  });

  var placeholder = list.length ? 'Add another…' : (isDiv ? 'Any division…' : 'Any player…');
  if (isDiv) {
    sl.button.innerHTML = '<span>' + esc(placeholder) + '</span><span class="caret">▾</span>';
    Array.prototype.forEach.call(sl.list.children, function (node) {
      if (node.className !== 'picker-group') {
        node.classList.toggle('chosen', list.indexOf(node.getAttribute('data-id')) >= 0);
      }
    });
  } else {
    sl.sel.innerHTML = '<option value="">' + esc(placeholder) + '</option>' + PLAYERS.map(function (p) {
      return '<option value="' + esc(p.id) + '">' + esc(p.name) + ' — ' + p.n + '</option>';
    }).join('');
  }
}

function syncTarget() {
  var q = S.f.q.trim().toLowerCase(), found = null;
  if (q) {
    var hits = PLAYERS.filter(function (p) {
      return p.name.toLowerCase().indexOf(q) >= 0 || p.id === S.f.q.trim();
    });
    var exact = hits.filter(function (p) { return p.name.toLowerCase() === q; });
    found = exact.length === 1 ? exact[0] : (hits.length === 1 ? hits[0] : null);
  }
  side.targetPlayer = found;
  side.target.style.display = found ? '' : 'none';
  if (found) {
    side.target.innerHTML = '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">Report: '
      + esc(found.name) + '</span><span style="color:var(--faint);font-size:12px;">→</span>';
    side.qHint.textContent = found.n + ' matches in replays · opens in a new tab';
  } else {
    side.qHint.textContent = 'Matches any player in the lobby';
  }
}

function syncSidebar() {
  side.owner.value = S.owner.id;
  side.ownerReport.innerHTML = '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
    + 'Full report: ' + esc(S.owner.name) + '</span><span style="color:var(--faint);font-size:12px;">→</span>';
  side.ownerReport.style.display = S.owner.id ? '' : 'none';
  side.q.value = S.f.q;
  side.dur.value = S.f.minDur;
  side.durVal.textContent = S.f.minDur ? '≥ ' + S.f.minDur + ' min' : 'off';
  syncEloSliders();
  side.map.value = S.f.map;
  side.from.value = S.f.from;
  side.to.value = S.f.to;
  Array.prototype.forEach.call(side.types.querySelectorAll('input'), function (cb, i) {
    cb.checked = S.f.types[['ranked', 'casual', 'vs_ai'][i]];
  });
  Array.prototype.forEach.call(side.results.querySelectorAll('input'), function (cb, i) {
    cb.checked = S.f.results[['win', 'loss', 'draw', 'aborted', 'none'][i]];
  });
  Array.prototype.forEach.call(side.sizes.children, function (b) {
    b.className = S.f.sizes[b.getAttribute('data-size')] ? 'on' : '';
  });
  [side.plA, side.plB, side.divA, side.divB].forEach(syncSideList);
  syncTarget();
}

/* -------------------------------------------------------------- match table */

var COLS = [
  ['date', 'DATE'], ['type', 'TYPE'], ['map', 'MAP'], ['size', 'SIZE'],
  ['myDiv', 'MY DIVISION'], ['oppDiv', 'OPPONENT'], ['result', 'RESULT'],
  ['dur', 'TIME', 1], ['elo', 'ELO YOU / OPP', 1]
];
var RESULT_TAG = { win: 'W', loss: 'L', draw: 'D', aborted: 'AB', none: '–' };
var MAGNITUDE = { 0: 'total', 1: 'major', 2: 'minor', 4: 'minor', 5: 'major', 6: 'total' };
var VICTORY = ['Total defeat', 'Major defeat', 'Minor defeat', 'Draw', 'Minor victory', 'Major victory', 'Total victory'];

function rowHtml(m) {
  var p = me(m), out = outcome(m, p);
  var myDiv = p && p.deck ? division(p.deck.divisionId) : { name: '—', alliance: '', emblem: '' };
  var opps = p ? m.players.filter(function (x) { return x.alliance !== p.alliance; }) : m.players;
  var oppNames = [], oppDiv = { alliance: '', emblem: '' };
  opps.forEach(function (x) {
    var d = x.deck ? division(x.deck.divisionId) : null;
    if (d) { if (oppNames.indexOf(d.name) < 0) oppNames.push(d.name); if (!oppNames[1]) oppDiv = d; }
  });
  var oppLabel = oppNames.length > 1 ? oppNames[0] + ' +' + (oppNames.length - 1) : (oppNames[0] || '—');
  var withElo = opps.filter(function (x) { return !x.ai && x.elo != null; });
  var oppElo = withElo.length ? withElo.reduce(function (a, x) { return a + x.elo; }, 0) / withElo.length : null;
  var showElo = p && p.elo != null && oppElo != null;
  var open = S.expanded === m.id;

  var h = '<div class="rowbox' + (open ? ' open' : '') + '">'
    + '<div class="grid row" data-match="' + esc(m.id) + '">'
    + '<div><div style="font-size:12.5px;">' + fmtDate(m.date) + '</div><div class="sub mono">' + fmtTime(m.date) + '</div></div>'
    + '<div><span class="tag ' + m.type + '">' + { ranked: 'Ranked', casual: 'Casual', vs_ai: 'vs AI' }[m.type] + '</span></div>'
    + '<div class="ell" title="' + esc(m.map.raw) + '">' + esc(m.map.name) + '</div>'
    + '<div class="mono" style="font-size:11.5px;color:var(--sub);">' + m.teamSize + 'v' + m.teamSize + '</div>'
    + '<div class="withdot">' + badge(myDiv, 18) + '<span class="ell">' + esc(myDiv.name) + '</span></div>'
    + '<div class="withdot">' + badge(oppDiv, 18) + '<span class="ell">' + esc(oppLabel) + '</span></div>'
    + '<div><span class="tag ' + RESULT_TAG[out] + '">' + RESULT_TAG[out] + '</span>'
    + '<span class="sub" style="margin-left:5px;">'
    + (out === 'none' ? 'not in match' : m.result.present ? (MAGNITUDE[m.result.victoryRaw] || '') : 'no result')
    + '</span></div>'
    + '<div class="r mono" style="font-size:12px;color:var(--sub);">' + fmtDur(m.result.duration) + '</div>'
    + '<div class="r mono" style="font-size:12px;">'
    + (showElo ? Math.round(p.elo) + ' <span style="color:var(--faint2);font-size:10px;">vs</span> '
        + '<span style="color:var(--sub);">' + Math.round(oppElo) + '</span>' : '')
    + '</div></div>';
  if (open) h += detailHtml(m);
  return h + '</div>';
}

function detailHtml(m) {
  var p = me(m);
  var vic = m.result.present ? (VICTORY[m.result.victoryRaw] || '?') : 'Aborted — no result block in the file';
  var bits = [m.file, 'v' + m.version, m.map.mode || 'unknown mode', m.map.size || '?',
    'income ' + (m.config.incomeRate || '?'), (m.config.initMoney || '?') + ' pts start',
    'score cap ' + (m.config.scoreLimit || '?'), vic];
  if (m.server) bits.push('lobby: ' + m.server);
  if (m.mods) bits.push('MODS: ' + m.mods);
  if (m.dateSource === 'file date') bits.push('date from file timestamp');
  /* Victory is stored from the saving player's point of view, so say whose. */
  var anchor = m.result.anchor != null ? m.players[m.result.anchor] : null;
  if (anchor && m.result.present) {
    bits.push('result recorded from ' + anchor.name + '’s side'
      + (m.result.anchorSource === 'ingameId' ? ' (guessed — replay not saved by you)' : ''));
  }

  var alliances = [];
  m.players.forEach(function (x) { if (alliances.indexOf(x.alliance) < 0) alliances.push(x.alliance); });
  alliances.sort(function (a, b) { return a - b; });
  if (p) alliances.sort(function (a, b) { return (a === p.alliance ? -1 : 0) - (b === p.alliance ? -1 : 0); });

  var allOpen = m.players.every(function (_, i) { return S.openDecks[m.id + ':' + i]; });

  var h = '<div class="detail"><div class="metaline">'
    + '<div class="mono" style="font-size:11px;color:var(--faint);flex:1;">' + esc(bits.join(' · ')) + '</div>'
    + '<button class="mini" data-alldecks="' + esc(m.id) + '">' + (allOpen ? 'Hide all decks' : 'Show all decks') + '</button>'
    + '</div><div class="teams">';

  alliances.forEach(function (al) {
    h += '<div class="team"><h4>TEAM ' + (al + 1) + (p && al === p.alliance ? ' — YOUR SIDE' : '')
      + (m.result.present && m.result.winnerAlliance === al ? '<span class="badge winner">WINNER</span>' : '')
      + '</h4>';
    m.players.forEach(function (x, i) {
      if (x.alliance !== al) return;
      h += playerHtml(m, x, i, p);
    });
    h += '</div>';
  });
  return h + '</div></div>';
}

function playerHtml(m, x, i, p) {
  var key = m.id + ':' + i, open = !!S.openDecks[key];
  var d = x.deck ? division(x.deck.divisionId)
                 : { name: 'No deck', alliance: '', country: '', type: '', emblem: '' };
  var h = '<div class="pcard"><div class="prow">'
    + face(x.steamId, 20)
    + '<div class="pname">' + esc(x.name) + '</div>'
    + (p && x.userId === p.userId ? '<span class="badge you">YOU</span>' : '')
    + (x.ai ? '<span class="badge ai">AI</span>' : '')
    + '<div style="flex:1;"></div>'
    + '<div class="mono" style="font-size:11px;color:var(--faint);">'
    + (x.elo != null ? Math.round(x.elo) + ' ELO' : 'no ELO')
    + (x.level != null ? ' · lvl ' + x.level : '') + '</div></div>'
    + '<div class="prow" style="margin-top:6px;">' + badge(d, 30)
    + '<span style="font-size:12.5px;color:var(--sub);flex:1;">' + esc(d.name)
    + (d.country ? ' <span class="sub">' + esc(d.country) + (d.type ? ' · ' + esc(d.type) : '') + '</span>' : '')
    + (x.deck && x.deck.modded ? ' · modded' : '') + '</span>';
  if (x.deck) h += '<button class="mini" data-deck="' + esc(key) + '">' + (open ? 'Hide deck' : 'Deck ▾') + '</button>';
  if (!x.ai && x.userId) h += '<button class="mini grey" data-report="' + esc(x.userId) + '" data-name="' + esc(x.name) + '">Report</button>';
  h += '</div>';

  if (open && x.deck) {
    var sum = deckSummary(x.deck);
    h += '<div class="deck">';
    if (sum) {
      h += '<div class="decksum"><span class="mono" style="font-weight:600;color:var(--sub);">' + sum.total + '</span><span>cards</span>'
        + '<span style="color:var(--line-strong);">·</span><span>avg vet</span>'
        + '<span class="mono" style="font-weight:600;color:var(--vet);">' + sum.avg + '</span>'
        + '<span style="color:var(--line-strong);">·</span><span>' + esc(sum.summary) + '</span>'
        + (x.deck.truncated ? '<span class="pill">TRUNCATED</span>' : '') + '</div>';
    } else {
      h += '<div class="decksum">Deck string could not be decoded.</div>';
    }
    h += '<div class="cats">';
    deckGroups(x.deck).forEach(function (g) {
      h += '<div class="cat"><div class="h"><span>' + g.label + '</span><span>' + g.count + '</span></div>';
      g.items.forEach(function (u) {
        h += '<div class="unit"><div class="l1"><span class="n">' + esc(u.name) + '</span>'
          + (u.n > 1 ? '<span class="x">×' + u.n + '</span>' : '')
          + '<span class="pips" style="color:' + (VETCOL[u.xp] || VETCOL[0]) + ';">'
          + (u.xp > 0 ? new Array(u.xp + 1).join('▲') : '—') + '</span></div>'
          + (u.tr ? '<div class="tr">▸ ' + esc(u.tr) + '</div>' : '') + '</div>';
      });
      h += '</div>';
    });
    h += '</div><div class="codebox"><input readonly value="' + esc(x.deck.code || '') + '">'
      + '<button class="mini" data-copy="' + esc(x.deck.code || '') + '">Copy code</button></div></div>';
  }
  return h + '</div>';
}

function matchesHtml() {
  var list = filtered();
  var tally = { win: 0, loss: 0, draw: 0, aborted: 0, none: 0 };
  list.forEach(function (m) { tally[outcome(m, me(m))]++; });
  var decided = tally.win + tally.loss;
  var wr = decided ? 100 * tally.win / decided : null;

  var maxPage = Math.max(0, Math.ceil(list.length / S.pageSize) - 1);
  var page = Math.min(S.page, maxPage);
  var slice = list.slice(page * S.pageSize, (page + 1) * S.pageSize);

  var h = '<div class="card main"><div class="summary">'
    + '<div><div style="display:flex;align-items:baseline;gap:7px;">'
    + '<span class="big">' + list.length + '</span>'
    + '<span style="font-size:13px;color:var(--sub);">/ ' + M.length + ' replays qualify</span></div>'
    + '<div style="font-size:11.5px;color:var(--faint);margin-top:2px;">'
    + (M.length - list.length) + ' excluded by filters · ' + tally.aborted + ' aborted in base'
    + (tally.none ? ' · ' + tally.none + ' without ' + esc(S.owner.name) : '') + '</div></div>'
    + '<div class="vrule"></div>'
    + '<div><div class="eyebrow" style="margin-bottom:3px;">' + esc(S.owner.name.toUpperCase()) + ': W – L – D</div>'
    + '<div class="tally"><span class="win">' + tally.win + '</span><span class="sep">–</span>'
    + '<span class="loss">' + tally.loss + '</span><span class="sep">–</span>'
    + '<span style="color:var(--sub);">' + tally.draw + '</span></div></div>'
    + '<div><div class="eyebrow" style="margin-bottom:3px;">WINRATE</div>'
    + '<div style="display:flex;align-items:baseline;gap:6px;">'
    + '<span class="stat21 ' + wrClass(wr) + '">' + (wr == null ? '—' : wr.toFixed(1) + '%') + '</span>'
    + '<span style="font-size:11px;color:var(--faint2);">' + decided + ' decided</span></div></div>'
    + '</div>';

  if (!list.length) {
    h += '<div class="empty">No replays pass the current filters.</div>';
  } else {
    h += '<div class="scroll"><div class="grid head">'
      + COLS.map(function (c) {
        return '<div data-sort="' + c[0] + '" class="' + (c[2] ? 'r ' : '') + (S.sort.key === c[0] ? 'on' : '') + '">'
          + c[1] + (S.sort.key === c[0] ? (S.sort.dir === 1 ? ' ▲' : ' ▼') : '') + '</div>';
      }).join('') + '</div>'
      + slice.map(rowHtml).join('') + '</div>';
  }
  h += '<div class="pager"><div class="mono" style="font-size:12px;color:var(--faint);">'
    + (list.length ? (page * S.pageSize + 1) + '–' + Math.min(list.length, (page + 1) * S.pageSize) + ' of ' + list.length : '—')
    + '</div><div style="flex:1;"></div>'
    + '<button data-page="' + (page - 1) + '"' + (page <= 0 ? ' disabled' : '') + '>← Prev</button>'
    + '<button data-page="' + (page + 1) + '"' + (page >= maxPage ? ' disabled' : '') + '>Next →</button>'
    + '</div></div>';
  return h;
}

/* ------------------------------------------------------------------ report */

function buildReport(uid, name) {
  var base = filtered().filter(function (m) {
    return m.players.some(function (p) { return p.userId === uid && !p.ai; });
  });
  function his(m) { return m.players.filter(function (p) { return p.userId === uid; })[0]; }

  var tally = { win: 0, loss: 0, draw: 0, aborted: 0 }, durations = [];
  base.forEach(function (m) {
    tally[outcome(m, his(m))]++;
    if (m.result.duration != null) durations.push(m.result.duration);
  });
  durations.sort(function (a, b) { return a - b; });
  var decided = tally.win + tally.loss;
  var wr = decided ? 100 * tally.win / decided : null;
  var avg = durations.length ? Math.round(durations.reduce(function (a, b) { return a + b; }, 0) / durations.length) : null;
  var med = durations.length ? durations[Math.floor(durations.length / 2)] : null;

  var agg = {};
  function add(bucket, key, init, counted, won) {
    var b = agg[bucket] || (agg[bucket] = { rows: {}, order: [] });
    var e = b.rows[key];
    if (!e) {
      e = b.rows[key] = { name: init.name, mark: init.mark || '', id: init.id || '', g: 0, w: 0, l: 0 };
      b.order.push(key);
    }
    e.g++;
    if (counted) { if (won) e.w++; else e.l++; }
  }
  base.forEach(function (m) {
    var p = his(m), o = outcome(m, p);
    var counted = o === 'win' || o === 'loss', won = o === 'win';
    if (p.deck) {
      var d = division(p.deck.divisionId);
      add('my', d.name, { name: d.name, mark: badge(d, 16) }, counted, won);
      var seenUnits = {};
      p.deck.cards.forEach(function (c) {
        var u = unit(c[1]);
        if (seenUnits[u.name]) return;
        seenUnits[u.name] = true;
        add('units', u.name, { name: u.name }, counted, won);
      });
    }
    var enemy = {}, enemyOrder = [];
    m.players.forEach(function (x) {
      if (x.alliance !== p.alliance && x.deck) {
        var e = division(x.deck.divisionId);
        if (!enemy[e.name]) { enemy[e.name] = e; enemyOrder.push(e.name); }
      }
    });
    enemyOrder.forEach(function (n) {
      add('vs', n, { name: n, mark: badge(enemy[n], 16) }, counted, won);
    });
    add('map', m.map.name, { name: m.map.name }, counted, won);
    m.players.forEach(function (x) {
      if (x.ai || x.userId === uid || !x.userId) return;
      /* keyed by id, not nick -- people rename themselves between matches */
      add(x.alliance === p.alliance ? 'with' : 'vsPlayer', x.userId,
          { name: playerName(x.userId) || x.name, id: x.userId, mark: face(x.steamId, 16) },
          counted, won);
    });
  });

  /* Full list for a bucket, ordered by that table's current sort. */
  function rows(bucket) {
    var b = agg[bucket];
    if (!b) return [];
    var sort = S.reportSort[bucket] || { key: 'g', dir: -1 };
    return b.order.map(function (k) { return b.rows[k]; }).sort(function (x, y) {
      var c = compareRows(x, y, sort.key) * sort.dir;
      return c || (y.g - x.g) || x.name.localeCompare(y.name);
    });
  }

  var eloGames = base.filter(function (m) { return m.type === 'ranked' && his(m).elo != null; });
  var note = 'ranked matches in base, ELO at match start';
  if (eloGames.length < 2) {
    eloGames = base.filter(function (m) { return his(m).elo != null; });
    note = 'all matches in base with a recorded ELO';
  }
  eloGames = eloGames.slice().sort(function (a, b) { return a.date.localeCompare(b.date); });
  var vals = eloGames.map(function (m) { return his(m).elo; });

  return {
    name: name, uid: uid, games: base.length, tally: tally, decided: decided, wr: wr,
    avg: avg, med: med, timed: durations.length, rows: rows, elo: vals, eloGames: eloGames, eloNote: note
  };
}

/* winrate as a fraction; null when nothing was decided, so it can sort last */
function rowWr(r) { var d = r.w + r.l; return d ? r.w / d : null; }

function compareRows(a, b, key) {
  if (key === 'name') return a.name.localeCompare(b.name);
  if (key === 'wl') return a.w - b.w;
  if (key === 'wr') {
    var x = rowWr(a), y = rowWr(b);
    if (x == null && y == null) return 0;
    if (x == null) return -1;          /* undecided rows sink either way */
    if (y == null) return 1;
    return x - y;
  }
  return a.g - b.g;
}

function tableHtml(bucket, title, sub, col, allRows, span, limit) {
  limit = limit || 14;
  var sort = S.reportSort[bucket] || { key: 'g', dir: -1 };
  function head(key, label, cls) {
    var on = sort.key === key;
    return '<div class="' + (cls || '') + (on ? ' on' : '') + '" data-rsort="' + esc(bucket)
      + '" data-rkey="' + key + '">' + label + (on ? (sort.dir === 1 ? ' ▲' : ' ▼') : '') + '</div>';
  }
  var rows = allRows.slice(0, limit);
  var h = '<div class="tbl" style="grid-column:span ' + span + ';"><h5>' + esc(title) + '</h5><div class="s">' + esc(sub) + '</div>'
    + '<div class="trow h sortable">' + head('name', col) + head('g', 'GAMES', 'num')
    + head('wl', 'W–L', 'num') + head('wr', 'WR', 'num') + '<div></div></div>';
  if (!rows.length) h += '<div class="hint" style="padding:6px 0;">No data in this base.</div>';
  rows.forEach(function (r) {
    var d = r.w + r.l, pct = d ? 100 * r.w / d : null;
    var label = r.id
      ? '<span class="linkish" data-report="' + esc(r.id) + '" data-name="' + esc(r.name) + '">' + esc(r.name) + '</span>'
      : '<span>' + esc(r.name) + '</span>';
    h += '<div class="trow"><div class="nm">' + (r.mark || '') + label + '</div>'
      + '<div class="num">' + r.g + '</div><div class="num">' + r.w + '–' + r.l + '</div>'
      + '<div class="num ' + wrClass(pct) + '" style="font-weight:600;">' + (pct == null ? '—' : pct.toFixed(0) + '%') + '</div>'
      + '<div class="bar-bg"><div style="width:' + (pct == null ? 0 : pct.toFixed(0)) + '%;background:'
      + (pct == null ? 'var(--line-strong)' : pct >= 50 ? 'var(--win)' : 'var(--loss)') + ';"></div></div></div>';
  });
  if (allRows.length > rows.length) {
    h += '<div class="hint" style="padding:6px 0 0;">showing ' + rows.length + ' of ' + allRows.length
      + ' — sort a column to bring others to the top</div>';
  }
  return h + '</div>';
}

function reportHtml(uid, name) {
  var r = buildReport(uid, name);
  var known = PLAYERS.filter(function (p) { return p.id === uid; })[0];
  var h = '<div>'
    + '<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">'
    + face(known && known.steamId, 30)
    + '<div style="font-size:22px;font-weight:700;letter-spacing:-.01em;">' + esc(r.name) + '</div>'
    + '<div class="mono" style="font-size:11.5px;color:var(--faint);">Eugen ID ' + esc(r.uid) + '</div></div>'
    + '<div style="font-size:12.5px;color:var(--sub);margin-bottom:16px;">Based on the current filter base: '
    + '<span class="mono" style="font-weight:600;">' + r.games + '</span> matches with this player'
    + ' · adjust filters on the Matches tab to change the base</div>';

  var tiles = [
    ['GAMES IN BASE', String(r.games), r.tally.aborted + ' aborted excluded from WR', 'neutral'],
    ['WINRATE', r.wr == null ? '—' : r.wr.toFixed(1) + '%', r.decided + ' decided games', wrClass(r.wr)],
    ['RECORD', r.tally.win + '–' + r.tally.loss + '–' + r.tally.draw, 'W–L–D', 'neutral'],
    ['AVG DURATION', fmtDur(r.avg), r.timed + ' timed games', 'neutral'],
    ['MEDIAN DURATION', fmtDur(r.med), 'half end sooner', 'neutral']
  ];
  h += '<div class="tiles">' + tiles.map(function (t) {
    return '<div class="tile"><div class="k">' + t[0] + '</div><div class="stat21 ' + t[3] + '">' + t[1] + '</div><div class="s">' + esc(t[2]) + '</div></div>';
  }).join('') + '</div>';

  if (r.elo.length >= 2) {
    var mn = Math.min.apply(null, r.elo), mx = Math.max.apply(null, r.elo), span = (mx - mn) || 1;
    var pts = r.elo.map(function (v, i) {
      return (i / (r.elo.length - 1) * 640).toFixed(1) + ',' + (156 - (v - mn) / span * 142).toFixed(1);
    }).join(' ');
    h += '<div class="panel"><div style="display:flex;align-items:baseline;gap:10px;margin-bottom:8px;">'
      + '<div style="font-size:12px;font-weight:700;">ELO over time</div>'
      + '<div style="font-size:11px;color:var(--faint2);">' + esc(r.eloNote) + '</div><div style="flex:1;"></div>'
      + '<div class="mono" style="font-size:11px;color:var(--sub);">' + Math.round(r.elo[0]) + ' → ' + Math.round(r.elo[r.elo.length - 1]) + '</div></div>'
      + '<div style="position:relative;"><svg viewBox="0 0 640 170" preserveAspectRatio="none" style="width:100%;height:170px;display:block;">'
      + '<line x1="0" y1="14" x2="640" y2="14" stroke="var(--line2)"></line>'
      + '<line x1="0" y1="85" x2="640" y2="85" stroke="var(--line2)"></line>'
      + '<line x1="0" y1="156" x2="640" y2="156" stroke="var(--line2)"></line>'
      + '<polyline points="' + pts + '" fill="none" stroke="var(--accent)" stroke-width="1.6" vector-effect="non-scaling-stroke"></polyline></svg>'
      + '<div class="mono" style="position:absolute;top:2px;left:0;font-size:10px;color:var(--faint2);">' + Math.round(mx) + '</div>'
      + '<div class="mono" style="position:absolute;bottom:2px;left:0;font-size:10px;color:var(--faint2);">' + Math.round(mn) + '</div></div>'
      + '<div class="mono" style="display:flex;justify-content:space-between;font-size:10.5px;color:var(--faint2);margin-top:4px;">'
      + '<span>' + fmtDate(r.eloGames[0].date) + '</span><span>' + fmtDate(r.eloGames[r.eloGames.length - 1].date) + '</span></div></div>';
  }

  h += '<div class="tblgrid">'
    + tableHtml('my', 'Winrate by own division', 'What this player picks, and how it goes', 'DIVISION', r.rows('my'), 2)
    + tableHtml('vs', 'Winrate vs enemy division', 'Each enemy division counted once per match', 'AGAINST', r.rows('vs'), 2)
    + tableHtml('map', 'Winrate by map', 'All match types in base', 'MAP', r.rows('map'), 2)
    + tableHtml('with', 'Winrate with', 'Games sharing a team with this player', 'TEAMMATE', r.rows('with'), 2)
    + tableHtml('vsPlayer', 'Winrate against', 'Games on the opposing team', 'OPPONENT', r.rows('vsPlayer'), 2)
    + tableHtml('units', 'Most-picked units', 'Decks containing the unit, at any veterancy', 'UNIT', r.rows('units'), 2, 20)
    + '</div></div>';
  return h;
}

/* ------------------------------------------------------------------ render */

function openReport(uid, name) {
  var known = PLAYERS.filter(function (p) { return p.id === uid; })[0];
  if (known) name = known.name;
  if (!S.tabs.some(function (t) { return t.uid === uid; })) S.tabs.push({ uid: uid, name: name });
  S.active = 'r:' + uid;
  render();
}
function toast(msg) {
  var t = document.getElementById('toast');
  t.textContent = msg; t.className = 'on';
  clearTimeout(toast._t);
  toast._t = setTimeout(function () { t.className = ''; }, 1900);
}

function renderTabs() {
  var box = document.getElementById('tabs');
  box.innerHTML = '<button class="tab' + (S.active === 'matches' ? ' on' : '') + '" data-tab="matches">Matches</button>'
    + S.tabs.map(function (t) {
      return '<button class="tab' + (S.active === 'r:' + t.uid ? ' on' : '') + '" data-tab="r:' + esc(t.uid) + '">'
        + esc(t.name) + '<span class="x" data-close="' + esc(t.uid) + '">×</span></button>';
    }).join('');
}

function render() {
  renderTabs();
  var main = document.getElementById('content');
  var onMatches = S.active === 'matches';
  /* the report reads the same filter base, but shows it full width */
  document.querySelector('.layout').classList.toggle('full', !onMatches);
  document.getElementById('side').style.display = onMatches ? '' : 'none';
  if (onMatches) {
    main.innerHTML = matchesHtml();
  } else {
    var tab = S.tabs.filter(function (t) { return 'r:' + t.uid === S.active; })[0];
    main.innerHTML = tab ? reportHtml(tab.uid, tab.name) : '';
  }
}

/* -------------------------------------------------------------------- boot */

function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('warno-analyzer-theme', t); } catch (e) {}
  document.getElementById('theme').textContent = t === 'dark' ? '◐ Light' : '◐ Dark';
}

function boot() {
  var stored = null;
  try { stored = localStorage.getItem('warno-analyzer-theme'); } catch (e) {}
  setTheme(stored || 'dark');

  S.owner = detectOwner();
  document.getElementById('src').textContent = (D.sourceDirs || []).join('  ·  ');
  document.getElementById('src').title = 'Names: ' + (D.dataSource || 'unknown');
  document.getElementById('dataset').textContent =
    M.length + ' replays · ' + (D.errors && D.errors.length ? D.errors.length + ' unreadable · ' : '')
    + 'generated ' + fmtDate(D.generatedAt);

  document.getElementById('side').appendChild(buildSidebar());
  syncSidebar();
  render();

  document.getElementById('theme').addEventListener('click', function () {
    setTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });

  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') closePicker();
  });

  document.body.addEventListener('click', function (ev) {
    var t = ev.target, node;
    if (!t || !t.closest) return;
    if (openPicker && !t.closest('.picker')) closePicker();
    if ((node = t.closest('[data-close]'))) {
      ev.stopPropagation();
      var uid = node.getAttribute('data-close');
      S.tabs = S.tabs.filter(function (x) { return x.uid !== uid; });
      if (S.active === 'r:' + uid) S.active = 'matches';
      return render();
    }
    if ((node = t.closest('[data-tab]'))) { S.active = node.getAttribute('data-tab'); return render(); }
    if ((node = t.closest('[data-sort]'))) {
      var k = node.getAttribute('data-sort');
      S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (k === 'date' || k === 'elo' || k === 'dur' || k === 'result' ? -1 : 1) };
      S.page = 0; S.expanded = null;
      return render();
    }
    if ((node = t.closest('[data-page]'))) { S.page = +node.getAttribute('data-page'); S.expanded = null; return render(); }
    if ((node = t.closest('[data-rsort]'))) {
      var bucket = node.getAttribute('data-rsort'), rkey = node.getAttribute('data-rkey');
      var cur = S.reportSort[bucket] || { key: 'g', dir: -1 };
      S.reportSort[bucket] = { key: rkey, dir: cur.key === rkey ? -cur.dir : (rkey === 'name' ? 1 : -1) };
      return render();
    }
    if ((node = t.closest('[data-copy]'))) {
      ev.stopPropagation();
      var code = node.getAttribute('data-copy');
      if (navigator.clipboard) navigator.clipboard.writeText(code);
      else { var i = document.createElement('textarea'); i.value = code; document.body.appendChild(i); i.select(); document.execCommand('copy'); i.remove(); }
      return toast('Deck code copied — import it in the WARNO armory');
    }
    if ((node = t.closest('[data-report]'))) {
      ev.stopPropagation();
      return openReport(node.getAttribute('data-report'), node.getAttribute('data-name'));
    }
    if ((node = t.closest('[data-deck]'))) {
      ev.stopPropagation();
      var dk = node.getAttribute('data-deck');
      S.openDecks[dk] = !S.openDecks[dk];
      return render();
    }
    if ((node = t.closest('[data-alldecks]'))) {
      ev.stopPropagation();
      var mid = node.getAttribute('data-alldecks');
      var match = M.filter(function (m) { return m.id === mid; })[0];
      var all = match.players.every(function (_, i) { return S.openDecks[mid + ':' + i]; });
      match.players.forEach(function (_, i) { S.openDecks[mid + ':' + i] = !all; });
      return render();
    }
    if (t.closest('.codebox')) return;
    if ((node = t.closest('[data-match]'))) {
      var id = node.getAttribute('data-match');
      S.expanded = S.expanded === id ? null : id;
      return render();
    }
  });
}

document.addEventListener('DOMContentLoaded', boot);
})();
