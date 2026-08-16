/* =========================================================================
   TI 2026 Match Predictor — frontend
   ========================================================================= */
'use strict';

const $  = (id) => document.getElementById(id);
const api = async (path, opts) => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
};

const emptySide = () => ({
  team: null,
  heroes: [null, null, null, null, null],
  // OpenDota account id per slot, aligned with `heroes`
  players: [null, null, null, null, null],
});

const state = {
  teams: [],
  heroes: [],
  heroById: new Map(),
  pick: { a: emptySide(), b: emptySide() },
  // attr '*' = show every hero; 'all' is Dota's Universal attribute
  modal: { side: null, slot: null, attr: '*', q: '' },
  playerModal: { side: null, slot: null },
  historyScope: 'ti',
  lastResult: null,
};

/* Liquipedia's role names, in the order a draft is usually read. */
const ROLE_ORDER = ['carry', 'mid', 'offlane', 'soft support', 'hard support'];
const roleRank = (role) => {
  const i = ROLE_ORDER.indexOf((role || '').toLowerCase());
  return i < 0 ? ROLE_ORDER.length : i;
};

const fmtPct = (x) => `${(x * 100).toFixed(1)}%`;
const other  = (side) => (side === 'a' ? 'b' : 'a');

function toast(msg, ms = 3200) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), ms);
}

/* =========================================================================
   Boot
   ========================================================================= */
async function boot() {
  wireEvents();
  await Promise.allSettled([loadStatus(), loadTeams(), loadHeroes(), loadSchedule(), loadHistory('ti')]);
  renderSide('a');
  renderSide('b');
}

async function loadStatus() {
  try {
    const s = await api('/api/status');
    const t = s.tournament || {};
    if (t.name) {
      const bits = [t.city && t.country ? `${t.city}, ${t.country}` : '',
                    t.start_date && t.end_date ? `${t.start_date} → ${t.end_date}` : '',
                    t.patch ? `patch ${t.patch}` : '',
                    t.team_number ? `${t.team_number} teams` : ''].filter(Boolean);
      $('tournament-meta').textContent = bits.join(' · ');
    } else {
      $('tournament-meta').textContent = 'Chưa có dữ liệu giải — bấm "Cập nhật dữ liệu".';
    }

    const pill = $('data-pill');
    const drafted = s.matches_with_drafts || 0;
    const eloAt = s.updated?.history;
    const eloAgeH = eloAt ? (Date.now() / 1000 - eloAt) / 3600 : null;

    pill.classList.remove('stale', 'bad');
    if (!s.ti_teams) pill.classList.add('bad');
    else if (!s.matches || drafted < 100 || (eloAgeH !== null && eloAgeH > 12)) pill.classList.add('stale');

    $('data-pill-text').textContent =
      `${s.ti_teams} teams · ${s.matches} trận · ${drafted} draft`;

    const stamp = (t) => (t ? new Date(t * 1000).toLocaleString('vi-VN') : 'chưa chạy');
    pill.title =
      `Đội & lịch: ${stamp(s.updated?.core)}\n` +
      `Elo (lịch sử trận): ${stamp(eloAt)}\n` +
      `Tuyển thủ & hero: ${stamp(s.updated?.players)} (${s.players_with_heroes || 0}/${s.players || 0} người có dữ liệu)\n` +
      `Draft hero: ${stamp(s.updated?.drafts)}\n` +
      `Kết quả series: ${stamp(s.updated?.results)}\n` +
      `Trọng số mô hình: ${s.weights?.source === 'fitted'
        ? `đã fit trên ${s.weights.trained_on} trận (team ${s.weights.team}, hero ${s.weights.hero}, matchup ${s.weights.matchup})`
        : 'mặc định trong config'}`;

    if (s.job && s.job.running) pollRefresh();
  } catch (err) {
    $('data-pill').classList.add('bad');
    $('data-pill-text').textContent = 'không kết nối được';
  }
}

async function loadTeams() {
  const data = await api('/api/teams');
  state.teams = data.teams;
  buildTeamMenu('a');
  buildTeamMenu('b');
  if (!state.teams.length) toast('Chưa có team nào — hãy bấm "Cập nhật dữ liệu".', 6000);
}

async function loadHeroes() {
  const data = await api('/api/heroes');
  state.heroes = data.heroes;
  state.heroById = new Map(data.heroes.map((h) => [h.id, h]));
}

async function loadSchedule() {
  try {
    const data = await api('/api/schedule');
    const strip = $('schedule-strip');
    strip.innerHTML = '';
    if (!data.matches.length) {
      strip.innerHTML = '<p class="muted small">Chưa có lịch thi đấu.</p>';
      return;
    }
    for (const m of data.matches) {
      const score = (m.score_a !== null && m.score_b !== null)
        ? `${m.score_a} : ${m.score_b}` : 'vs';
      const card = document.createElement('button');
      card.className = 'sched-card';
      card.innerHTML = `
        <div class="sched-top">
          <span class="sched-status ${m.status}">${m.status}</span>
          <span class="muted">${escapeHtml(m.stage || '')}</span>
        </div>
        <div class="sched-teams">
          <span class="t">${escapeHtml(m.team_a)}</span>
          <span class="sc">${score}</span>
          <span class="t" style="text-align:right">${escapeHtml(m.team_b)}</span>
        </div>`;
      card.addEventListener('click', () => loadFixture(m.team_a, m.team_b, m.slug_a, m.slug_b));
      strip.appendChild(card);
    }
  } catch (err) { /* schedule is optional */ }
}

/* =========================================================================
   Match history
   ========================================================================= */
async function loadHistory(scope = state.historyScope) {
  state.historyScope = scope;
  for (const b of $('history-tabs').children) b.classList.toggle('on', b.dataset.scope === scope);

  const box = $('history-body');

  if (scope === 'teams') {
    const { a, b } = state.pick;
    if (!a.team || !b.team) {
      box.innerHTML = '<p class="history-empty">Chọn Team A và Team B ở trên để xem lịch sử từng ván của 2 đội.</p>';
      return;
    }
  }

  box.innerHTML = '<p class="muted small">Đang tải…</p>';
  try {
    const params = new URLSearchParams({ scope, limit: scope === 'teams' ? 15 : 60 });
    if (scope === 'teams') {
      params.set('team_a', state.pick.a.team.slug);
      params.set('team_b', state.pick.b.team.slug);
      params.set('line_minutes', parseFloat($('line-input').value) || 41);
    }
    const data = await api(`/api/results?${params}`);
    if (scope === 'teams') renderTeamHistory(data);
    else renderSeriesHistory(data);
  } catch (err) {
    box.innerHTML = `<p class="history-empty">Không tải được lịch sử: ${escapeHtml(err.message)}</p>`;
  }
}

function renderSeriesHistory(data) {
  const box = $('history-body');
  if (!data.series.length) {
    box.innerHTML = '<p class="history-empty">Chưa có dữ liệu — bấm "Cập nhật dữ liệu" để tải kho kết quả.</p>';
    return;
  }
  box.innerHTML = `
    <div class="series-list">
      ${data.series.map((s) => {
        const aWon = s.score_a > s.score_b;
        const bWon = s.score_b > s.score_a;
        return `
        <a class="series-row" href="${escapeHtml(s.url || '#')}" target="_blank" rel="noopener">
          <span class="sr-date">${escapeHtml(s.played_on || 'hôm nay')}</span>
          <span class="sr-tour">${escapeHtml(s.tournament || '')}</span>
          <span class="sr-teams">
            <b class="${aWon ? 'won' : ''}">${escapeHtml(s.team_a)}</b>
            <span class="sr-score">${s.score_a} : ${s.score_b}</span>
            <b class="${bWon ? 'won' : ''}">${escapeHtml(s.team_b)}</b>
          </span>
        </a>`;
      }).join('')}
    </div>
    <p class="muted small" style="margin-top:10px">
      ${data.series.length} series · nguồn hawk.live${data.scope === 'ti' ? ' · lọc theo The International 2026' : ''}
    </p>`;
}

function renderTeamHistory(data) {
  const box = $('history-body');
  const s = data.over_under_summary;
  const line = data.line_minutes;

  const gameRows = (side) => {
    if (!side.games.length) {
      return '<p class="history-empty">Không có dữ liệu ván đấu cho đội này.</p>';
    }
    return side.games.map((g) => `
      <div class="game-row">
        <span class="g-res ${g.won ? 'w' : 'l'}">${g.won ? 'W' : 'L'}</span>
        <span class="g-opp">${escapeHtml(g.opponent)}</span>
        <span class="g-league">${escapeHtml(g.league || '')}</span>
        <span class="g-dur">${g.duration_min}′</span>
        <span class="g-ou ${g.over ? 'over' : 'under'}">${g.over ? 'O' : 'U'}</span>
      </div>`).join('');
  };

  const rate = s.over_rate === null ? null : (s.over_rate * 100).toFixed(0);
  box.innerHTML = `
    <div class="ou-summary">
      <div class="ous-main">
        <span class="ous-value">${rate === null ? '—' : rate + '%'}</span>
        <span class="ous-label">số ván vượt ${line}′<br><span class="muted">${s.over}/${s.games} ván gần đây của 2 đội</span></span>
      </div>
      <div class="ous-bar">
        <div class="ous-fill" style="width:${s.over_rate === null ? 0 : s.over_rate * 100}%"></div>
      </div>
      <div class="ous-legend"><span class="under">UNDER ${s.under}</span><span class="over">OVER ${s.over}</span></div>
    </div>
    <div class="team-history-grid">
      <div class="th-col">
        <h3 class="th-head a">${escapeHtml(data.a.name)}</h3>
        ${gameRows(data.a)}
      </div>
      <div class="th-col">
        <h3 class="th-head b">${escapeHtml(data.b.name)}</h3>
        ${gameRows(data.b)}
      </div>
    </div>
    <p class="muted small" style="margin-top:10px">
      Từng ván (không phải series) từ OpenDota · O = vượt ${line}′, U = dưới ${line}′ ·
      đối đầu trực tiếp: ${data.head_to_head.a_wins}–${data.head_to_head.b_wins}
    </p>`;
}

/* Match a GosuGamers name back onto a team in the dropdown. */
function loadFixture(nameA, nameB, slugA, slugB) {
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  // The backend resolves each fixture to a slug when it stores it, using the
  // alias table that knows "BoomBoys" is BetBoom.  Matching on the display
  // name here is only the fallback for rows stored before that existed.
  const find = (name, slug) => {
    if (slug) {
      const bySlug = state.teams.find((t) => t.slug === slug);
      if (bySlug) return bySlug;
    }
    const n = norm(name);
    return state.teams.find((t) => norm(t.name) === n)
        || state.teams.find((t) => norm(t.name).includes(n) || n.includes(norm(t.name)));
  };
  const ta = find(nameA, slugA), tb = find(nameB, slugB);
  if (!ta || !tb) { toast('Không khớp được team trong danh sách tham dự.'); return; }
  selectTeam('a', ta.slug);
  selectTeam('b', tb.slug);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* =========================================================================
   Team dropdowns
   ========================================================================= */
function buildTeamMenu(side) {
  const menu = $(`team-menu-${side}`);
  menu.innerHTML = `
    <div class="team-search-wrap">
      <input type="search" class="team-search" id="team-search-${side}"
             placeholder="Tìm team hoặc tuyển thủ…" autocomplete="off">
    </div>
    <div class="team-opts" id="team-opts-${side}"></div>`;

  // clicks inside the menu must not reach the document-level "close" handler
  menu.addEventListener('click', (e) => e.stopPropagation());

  const search = $(`team-search-${side}`);
  search.addEventListener('input', () => renderTeamOptions(side));
  search.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const first = menu.querySelector('.team-opt:not(.disabled)');
      if (first) { selectTeam(side, first.dataset.slug); closeMenus(); }
    } else if (e.key === 'Escape') {
      closeMenus();
    }
  });

  renderTeamOptions(side);
}

/* Filter the dropdown by team name, player name or qualification route. */
function renderTeamOptions(side) {
  const box = $(`team-opts-${side}`);
  const q = ($(`team-search-${side}`)?.value || '').trim().toLowerCase();
  box.innerHTML = '';

  const matches = state.teams.filter((t) => {
    if (!q) return true;
    if (t.name.toLowerCase().includes(q)) return true;
    if ((t.qualification || '').toLowerCase().includes(q)) return true;
    return (t.players || []).some((p) => p.name.toLowerCase().includes(q));
  });

  if (!matches.length) {
    box.innerHTML = '<p class="team-empty">Không có team nào khớp.</p>';
    return;
  }

  for (const t of matches) {
    // show which player matched, so searching "yatoro" explains itself
    const hitPlayer = q && !t.name.toLowerCase().includes(q)
      ? (t.players || []).find((p) => p.name.toLowerCase().includes(q))
      : null;
    const btn = document.createElement('button');
    btn.className = 'team-opt';
    btn.type = 'button';
    btn.dataset.slug = t.slug;
    btn.innerHTML = `
      ${t.logo_url ? `<img src="${t.logo_url}" alt="" onerror="this.remove()">` : '<span style="width:24px"></span>'}
      <span class="nm">${highlight(t.name, q)}${hitPlayer ? `<em class="hit">${escapeHtml(hitPlayer.name)}</em>` : ''}</span>
      <span class="rt">${Math.round(t.rating)}</span>`;
    btn.addEventListener('click', () => { selectTeam(side, t.slug); closeMenus(); });
    box.appendChild(btn);
  }
  syncMenuDisabled();
}

function highlight(text, q) {
  if (!q) return escapeHtml(text);
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return escapeHtml(text);
  return escapeHtml(text.slice(0, i))
       + `<mark>${escapeHtml(text.slice(i, i + q.length))}</mark>`
       + escapeHtml(text.slice(i + q.length));
}

function syncMenuDisabled() {
  for (const side of ['a', 'b']) {
    const taken = state.pick[other(side)].team?.slug;
    for (const opt of $(`team-menu-${side}`).querySelectorAll('.team-opt')) {
      opt.classList.toggle('disabled', opt.dataset.slug === taken);
    }
  }
}

/* The five current players, in role order — what the team is most likely to
   field.  The user can still change any slot. */
function defaultLineup(team) {
  const pool = (team.roster || []).filter((p) => p.resolved);
  // OpenDota's "current member" flag lags a roster move, so a team with fewer
  // than five current players is topped up with its most-played others.
  const five = pool.filter((p) => p.current)
    .sort((x, y) => roleRank(x.role) - roleRank(y.role))
    .concat(pool.filter((p) => !p.current))
    .slice(0, 5);
  return [0, 1, 2, 3, 4].map((i) => five[i]?.account_id ?? null);
}

function selectTeam(side, slug) {
  const team = state.teams.find((t) => t.slug === slug);
  if (!team) return;
  if (state.pick[other(side)].team?.slug === slug) {
    toast('Team này đã được chọn ở phía bên kia.');
    return;
  }
  state.pick[side].team = team;
  state.pick[side].players = defaultLineup(team);
  renderSide(side);
  syncMenuDisabled();
  updatePredictButton();
  if (state.historyScope === 'teams') loadHistory('teams');
}

function closeMenus() {
  $('team-menu-a').hidden = true;
  $('team-menu-b').hidden = true;
}

/* =========================================================================
   Rendering a side
   ========================================================================= */
function renderSide(side) {
  const { team, heroes } = state.pick[side];

  $(`team-name-${side}`).textContent = team ? team.name : (side === 'a' ? 'Chọn team A' : 'Chọn team B');
  const logo = $(`team-logo-${side}`);
  if (team && team.logo_url) { logo.src = team.logo_url; logo.hidden = false; }
  else { logo.hidden = true; }

  $(`rating-${side}`).textContent = team ? `Elo ${Math.round(team.rating)}` : '—';

  const meta = $(`team-meta-${side}`);
  if (team) {
    const winPct = team.games ? Math.round((team.wins / team.games) * 100) : null;
    meta.innerHTML = [
      team.qualification ? `<span>${escapeHtml(team.qualification)}</span>` : '',
      team.games ? `<span>${team.wins}/${team.games} trận (${winPct}%)</span>` : '<span>chưa có lịch sử trận</span>',
      team.players?.length ? `<span title="${escapeHtml(team.players.map((p) => `${p.role}: ${p.name}`).join(' · '))}">${escapeHtml(team.players.filter((p) => !/coach/i.test(p.role)).map((p) => p.name).join(', '))}</span>` : '',
    ].filter(Boolean).join('');
  } else {
    meta.innerHTML = '';
  }

  const wrap = $(`picks-${side}`);
  wrap.innerHTML = '';
  heroes.forEach((hid, i) => {
    const col = document.createElement('div');
    col.className = 'pick-col';

    const slot = document.createElement('div');
    slot.className = 'slot' + (hid ? ' filled' : '');
    if (hid) {
      const h = state.heroById.get(hid);
      slot.innerHTML = `
        <img src="${h.img}" alt="${escapeHtml(h.name)}">
        <span class="wr">${(h.winrate * 100).toFixed(0)}%</span>
        <button class="rm" title="Bỏ hero">×</button>
        <span class="cap">${escapeHtml(h.name)}</span>`;
      slot.querySelector('.rm').addEventListener('click', (e) => {
        e.stopPropagation();
        state.pick[side].heroes[i] = null;
        renderSide(side);
        updatePredictButton();
      });
    } else {
      slot.innerHTML = '<span class="plus">+</span>';
    }
    slot.addEventListener('click', () => openHeroModal(side, i));
    col.appendChild(slot);

    const p = rosterEntry(side, state.pick[side].players[i]);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'slot-player' + (p ? '' : ' empty');
    btn.title = p ? `${p.role || 'tuyển thủ'} · ${p.total_games} trận trong dữ liệu`
                  : 'Chọn tuyển thủ cầm hero này';
    btn.textContent = p ? p.name : '+ tuyển thủ';
    btn.addEventListener('click', (e) => { e.stopPropagation(); openPlayerModal(side, i); });
    col.appendChild(btn);

    wrap.appendChild(col);
  });
}

function rosterEntry(side, accountId) {
  if (!accountId) return null;
  return (state.pick[side].team?.roster || []).find((p) => p.account_id === accountId) || null;
}

function updatePredictButton() {
  $('btn-predict').disabled = !(state.pick.a.team && state.pick.b.team);
}

/* =========================================================================
   Hero picker
   ========================================================================= */
function openHeroModal(side, slot) {
  state.modal = { side, slot, attr: '*', q: '' };
  $('hero-modal-title').textContent =
    `Chọn hero — ${state.pick[side].team ? state.pick[side].team.name : (side === 'a' ? 'Team A' : 'Team B')}`;
  $('hero-modal-sub').textContent = `Vị trí ${slot + 1}/5 · % là tỉ lệ thắng ước tính của hero`;
  $('hero-search').value = '';
  for (const b of $('attr-tabs').children) b.classList.toggle('on', b.dataset.attr === '*');
  renderHeroGrid();
  $('hero-modal').classList.remove('hidden');
  setTimeout(() => $('hero-search').focus(), 30);
}

function closeHeroModal() { $('hero-modal').classList.add('hidden'); }

function renderHeroGrid() {
  const { attr, q } = state.modal;
  const taken = new Set([...state.pick.a.heroes, ...state.pick.b.heroes].filter(Boolean));
  const needle = q.trim().toLowerCase();

  const list = state.heroes.filter((h) => {
    if (attr !== '*' && h.attr !== attr) return false;
    if (!needle) return true;
    return h.name.toLowerCase().includes(needle)
        || (h.roles || []).some((r) => r.toLowerCase().includes(needle));
  });

  const grid = $('hero-grid');
  grid.innerHTML = '';
  if (!list.length) {
    grid.innerHTML = '<p class="muted small">Không tìm thấy hero nào.</p>';
    return;
  }
  for (const h of list) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'hero-card' + (taken.has(h.id) ? ' taken' : '');
    const wr = h.winrate;
    const barColor = wr >= 0.52 ? 'var(--radiant)' : wr <= 0.48 ? 'var(--dire)' : '#3b4967';
    card.innerHTML = `
      <img src="${h.img}" alt="" loading="lazy">
      <span class="attr-dot attr-${h.attr}"></span>
      <span class="wr">${(wr * 100).toFixed(0)}</span>
      <span class="bar" style="background:${barColor}"></span>
      <span class="nm">${escapeHtml(h.name)}</span>`;
    card.addEventListener('click', () => {
      const { side, slot } = state.modal;
      state.pick[side].heroes[slot] = h.id;
      renderSide(side);
      updatePredictButton();
      closeHeroModal();
    });
    grid.appendChild(card);
  }
}

/* =========================================================================
   Player picker
   ========================================================================= */
async function openPlayerModal(side, slot) {
  const team = state.pick[side].team;
  if (!team) { toast('Hãy chọn team trước.'); return; }

  state.playerModal = { side, slot };
  const heroId = state.pick[side].heroes[slot];
  const hero = heroId ? state.heroById.get(heroId) : null;
  $('player-modal-title').textContent = `Tuyển thủ — ${team.name}`;
  $('player-modal-sub').textContent = hero
    ? `Vị trí ${slot + 1}/5 · ${hero.name} · % là tỉ lệ thắng của tuyển thủ trên hero này`
    : `Vị trí ${slot + 1}/5 · chọn hero trước để xem tỉ lệ thắng trên hero đó`;
  $('player-list').innerHTML = '<p class="muted small" style="padding:14px">Đang tải…</p>';
  $('player-modal').classList.remove('hidden');

  try {
    // asking for the hero as well makes the list answer "who plays this hero"
    const data = await api(`/api/roster/${encodeURIComponent(team.slug)}` +
                           (heroId ? `?hero_id=${heroId}` : ''));
    renderPlayerList(data.roster, !!heroId);
  } catch (err) {
    $('player-list').innerHTML =
      `<p class="muted small" style="padding:14px">Không tải được đội hình: ${escapeHtml(err.message)}</p>`;
  }
}

function closePlayerModal() { $('player-modal').classList.add('hidden'); }

function renderPlayerList(roster, withHero) {
  const { side, slot } = state.playerModal;
  const box = $('player-list');
  const taken = new Set(state.pick[side].players.filter((p, i) => p && i !== slot));
  const current = state.pick[side].players[slot];

  const rows = [];
  rows.push(`<button class="player-row none${current ? '' : ' on'}" data-account="">
      <span class="pr-name">Không gán</span>
      <span class="pr-note">bỏ qua yếu tố tuyển thủ ở vị trí này</span>
    </button>`);

  if (!roster.length) {
    rows.push('<p class="muted small" style="padding:12px">Chưa có dữ liệu đội hình — bấm '
            + '"Cập nhật dữ liệu" để tải danh sách tuyển thủ.</p>');
  }

  for (const p of roster) {
    if (!p.resolved) {
      rows.push(`<div class="player-row disabled">
          <span class="pr-name">${escapeHtml(p.name)}</span>
          <span class="pr-note">${escapeHtml(p.role || '')} · chưa khớp được với OpenDota</span>
        </div>`);
      continue;
    }
    const isTaken = taken.has(p.account_id);
    const stat = withHero
      ? (p.hero_games >= 3
          ? `${p.hero_games} trận · ${(p.hero_winrate * 100).toFixed(0)}% (nền ${(p.base_winrate * 100).toFixed(0)}%)`
          : `${p.hero_games || 0} trận trên hero này`)
      : `${p.total_games.toLocaleString('vi-VN')} trận trong dữ liệu`;
    const edge = withHero && p.hero_games >= 3
      ? `<span class="pr-edge ${p.edge >= 0 ? 'pos' : 'neg'}">${signed(p.edge)}</span>` : '';
    rows.push(`
      <button class="player-row${isTaken ? ' disabled' : ''}${current === p.account_id ? ' on' : ''}"
              data-account="${p.account_id}">
        <span class="pr-name">${escapeHtml(p.name)}${p.current ? '' : ' <em>(cũ)</em>'}</span>
        <span class="pr-role">${escapeHtml(p.role || '')}</span>
        <span class="pr-note">${escapeHtml(stat)}${isTaken ? ' · đã xếp ở ô khác' : ''}</span>
        ${edge}
      </button>`);
  }

  box.innerHTML = rows.join('');
  for (const el of box.querySelectorAll('button.player-row:not(.disabled)')) {
    el.addEventListener('click', () => {
      const raw = el.dataset.account;
      state.pick[side].players[slot] = raw ? Number(raw) : null;
      renderSide(side);
      closePlayerModal();
    });
  }
}

/* =========================================================================
   Predict
   ========================================================================= */
async function predict() {
  const { a, b } = state.pick;
  if (!a.team || !b.team) return;

  const btn = $('btn-predict');
  const label = btn.querySelector('span');
  btn.disabled = true;
  label.textContent = 'ĐANG TÍNH…';
  // the first prediction for a new set of heroes downloads their head-to-head
  // records from OpenDota (rate limited, ~1s each), so say what is happening
  const slowHint = setTimeout(() => { label.textContent = 'ĐANG TẢI KHẮC CHẾ…'; }, 3000);

  // heroes and players have to stay paired, so filled slots are packed together
  const pack = (s) => {
    const heroes = [], players = [];
    s.heroes.forEach((h, i) => { if (h) { heroes.push(h); players.push(s.players[i] || null); } });
    return { heroes, players };
  };
  const pa = pack(a), pb = pack(b);

  try {
    const result = await api('/api/predict', {
      method: 'POST',
      body: JSON.stringify({
        team_a: a.team.slug,
        team_b: b.team.slug,
        heroes_a: pa.heroes,
        heroes_b: pb.heroes,
        players_a: pa.players,
        players_b: pb.players,
        line_minutes: parseFloat($('line-input').value) || 41,
      }),
    });
    state.lastResult = result;
    renderResult(result);
  } catch (err) {
    toast(`Lỗi dự đoán: ${err.message}`, 5000);
  } finally {
    clearTimeout(slowHint);
    btn.disabled = false;
    label.textContent = 'DỰ ĐOÁN';
  }
}

function renderResult(r) {
  const nameA = state.pick.a.team.name;
  const nameB = state.pick.b.team.name;
  $('result').classList.remove('hidden');

  /* --- win probability --- */
  const pa = r.win_probability.a, pb = r.win_probability.b;
  $('win-fill-a').style.width = `${pa * 100}%`;
  $('win-fill-b').style.width = `${pb * 100}%`;
  $('win-pct-a').textContent = fmtPct(pa);
  $('win-pct-b').textContent = fmtPct(pb);
  $('win-name-a').textContent = nameA;
  $('win-name-b').textContent = nameB;

  const chip = $('confidence-chip');
  chip.className = `chip ${r.confidence}`;
  chip.textContent = { high: 'độ tin cậy cao', medium: 'độ tin cậy vừa', low: 'độ tin cậy thấp' }[r.confidence];

  const fav = pa >= pb ? nameA : nameB;
  const favP = Math.max(pa, pb);
  const margin = favP >= 0.65 ? 'chênh lệch rõ rệt'
               : favP >= 0.56 ? 'nhỉnh hơn'
               : 'gần như cân bằng';
  $('verdict').innerHTML =
    `<b>${escapeHtml(fav)}</b> được đánh giá cao hơn (${fmtPct(favP)}) — ${margin}. ` +
    `Sức mạnh đội đóng góp ${signed(r.factors.team_strength.logit)} log-odds, ` +
    `đội hình đóng góp ${signed(r.factors.draft_total_logit)}, ` +
    `tuyển thủ với hero ${signed(r.factors.player_heroes.logit)}.`;

  /* --- over / under --- */
  const d = r.duration;
  $('ou-line').textContent = `O/U ${d.line_minutes}′`;
  $('ou-expected').textContent = d.expected_minutes.toFixed(1);
  $('ou-pick').textContent = d.pick;
  $('ou-pick').className = `ou-pick ${d.pick}`;
  $('ou-fill-under').style.width = `${d.p_under * 100}%`;
  $('ou-under').textContent = fmtPct(d.p_under);
  $('ou-over').textContent = fmtPct(d.p_over);
  $('ou-marker').style.left = `${(d.p_under * 100).toFixed(1)}%`;
  $('ou-marker-label').textContent = `${d.line_minutes}′`;
  const win = d.baseline_days ? `${d.baseline_days} ngày gần nhất` : 'toàn bộ lịch sử';
  const t = r.factors.duration_terms;
  const ctx = r.factors.ti_context || {};
  $('ou-note').textContent =
    `Nền pro ${d.baseline_minutes}′ (${win}, ${d.sample.toLocaleString('vi-VN')} trận) ` +
    `· nhịp độ 2 đội ${pctShift(t.team_pace_log)} · đội hình ${pctShift(t.hero_draft_log)} ` +
    (ctx.active ? `· TI 2026 (${ctx.games} ván) ${pctShift(t.ti_context_log)} ` : '') +
    `· trung bình kỳ vọng ${d.mean_minutes}′`;

  /* --- factors --- */
  const f = r.factors;
  const rows = [
    { label: 'Sức mạnh đội (Elo)', value: f.team_strength.logit,
      hint: `${nameA} ${f.team_strength.a_rating} vs ${nameB} ${f.team_strength.b_rating}` },
    { label: 'Chất lượng hero', value: f.hero_winrate.logit,
      hint: ctx.active
        ? `tổng tỉ lệ thắng nền của 5 hero mỗi bên, đã nhân ×${ctx.hero_mult.toFixed(2)} `
          + `theo ${ctx.games} ván TI đã đấu`
        : 'tổng tỉ lệ thắng nền của 5 hero mỗi bên' },
    { label: 'Khắc chế đội hình', value: f.hero_matchups.logit,
      hint: 'đối đầu hero với hero, đã trừ đi sức mạnh nền của từng hero' },
    { label: 'Tuyển thủ với hero', value: f.player_heroes.logit,
      hint: f.player_heroes.assigned
        ? `${f.player_heroes.assigned} tuyển thủ được gán hero, so với tỉ lệ thắng chung của chính họ`
        : 'chưa gán tuyển thủ nào cho hero' },
  ];
  const scale = Math.max(0.35, ...rows.map((x) => Math.abs(x.value)));
  $('factors').innerHTML = rows.map((row) => {
    const w = Math.min(50, (Math.abs(row.value) / scale) * 50);
    const cls = row.value >= 0 ? 'pos' : 'neg';
    const color = row.value >= 0 ? 'var(--radiant-soft)' : 'var(--dire-soft)';
    return `
      <div class="factor">
        <div class="factor-top">
          <span class="lbl">${escapeHtml(row.label)}</span>
          <span class="val" style="color:${color}">${signed(row.value)}</span>
        </div>
        <div class="factor-track"><div class="factor-bar ${cls}" style="width:${w}%"></div></div>
        <div class="factor-hint">${escapeHtml(row.hint)}</div>
      </div>`;
  }).join('') +
  `<div class="factor-hint" style="margin-top:12px">Giá trị dương ⇒ lợi thế cho ${escapeHtml(nameA)}; âm ⇒ lợi thế cho ${escapeHtml(nameB)}.</div>`;

  /* --- head to head + form --- */
  const h = r.head_to_head;
  const formA = r.teams.a.form, formB = r.teams.b.form;
  const runHtml = (form) => `<span class="form-run">${form.results.slice().reverse().map((x) => `<i class="${x}">${x}</i>`).join('')}</span>`;
  $('h2h').innerHTML = `
    <div class="h2h-score">
      <span class="n a">${h.a_wins}</span><span class="sep">—</span><span class="n b">${h.b_wins}</span>
    </div>
    <div class="stat-row"><span class="k">Phong độ ${escapeHtml(nameA)}</span><span class="v">${runHtml(formA)}</span></div>
    <div class="stat-row"><span class="k">Phong độ ${escapeHtml(nameB)}</span><span class="v">${runHtml(formB)}</span></div>
    <div class="stat-row"><span class="k">Thời lượng TB gần đây</span><span class="v">${formA.avg_duration_min ?? '—'}′ / ${formB.avg_duration_min ?? '—'}′</span></div>
    ${h.matches.length ? `<div class="h2h-list" style="margin-top:10px">${h.matches.map((m) => `
      <div class="h2h-row">
        <span class="w ${m.winner === 'A' ? 'a' : 'b'}">${m.winner === 'A' ? escapeHtml(nameA).slice(0, 9) : escapeHtml(nameB).slice(0, 9)}</span>
        <span class="lg">${escapeHtml(m.league || '')}</span>
        <span class="dur">${m.duration_min}′</span>
      </div>`).join('')}</div>`
      : '<p class="muted small" style="margin:10px 0 0">Chưa có lịch sử đối đầu trực tiếp trong dữ liệu.</p>'}`;

  /* --- player / hero lineup --- */
  renderLineup(r, nameA, nameB);

  /* --- notes --- */
  $('notes').innerHTML = (r.notes || []).map((n) => `<div class="note">${escapeHtml(n)}</div>`).join('');

  $('result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* Per-slot table: who is on which hero and what that is worth. */
function renderLineup(r, nameA, nameB) {
  const p = r.factors.player_heroes;
  $('lineup-total').textContent = `${signed(p.logit)} log-odds`;

  const sum = (rows) => rows.reduce((acc, x) => acc + x.edge, 0);

  const col = (rows, name, cls) => {
    if (!rows.length) {
      return `<div class="lu-col"><h3 class="th-head ${cls}">${escapeHtml(name)}</h3>
              <p class="muted small">Chưa chọn hero.</p></div>`;
    }
    return `
      <div class="lu-col">
        <h3 class="th-head ${cls}">${escapeHtml(name)} <span class="lu-sum">${signed(sum(rows))}</span></h3>
        ${rows.map((x) => {
          const hero = state.heroById.get(x.hero_id);
          const wr = x.winrate === null ? '—' : `${(x.winrate * 100).toFixed(0)}%`;
          const base = x.base_winrate === null ? '—' : `${(x.base_winrate * 100).toFixed(0)}%`;
          const note = !x.account_id ? 'chưa gán tuyển thủ'
                     : !x.known ? 'chưa có dữ liệu tuyển thủ'
                     : x.games < 3 ? `chỉ ${x.games} trận — bỏ qua`
                     : `${x.games} trận · ${wr} (nền ${base})`;
          return `
            <div class="lu-row">
              ${hero ? `<img src="${hero.img}" alt="">` : '<span class="lu-noimg"></span>'}
              <span class="lu-txt">
                <b>${escapeHtml(x.player || (x.account_id ? `#${x.account_id}` : 'không gán'))}</b>
                <em>${escapeHtml(x.hero || '')} · ${escapeHtml(note)}</em>
              </span>
              <span class="lu-edge ${x.edge > 0 ? 'pos' : x.edge < 0 ? 'neg' : ''}">${signed(x.edge)}</span>
            </div>`;
        }).join('')}
      </div>`;
  };

  $('lineup').innerHTML = `
    <div class="lineup-grid">${col(p.a, nameA, 'a')}${col(p.b, nameB, 'b')}</div>
    <p class="muted small" style="margin-top:10px">
      Mỗi số là lợi thế của chính tuyển thủ đó trên hero được gán — tỉ lệ thắng của họ trên hero
      này so với tỉ lệ thắng chung của họ (nguồn OpenDota, gồm cả trận rank).
      Tổng ${escapeHtml(nameA)} (${signed(sum(p.a))}) trừ tổng ${escapeHtml(nameB)}
      (${signed(sum(p.b))}) rồi nhân trọng số ⇒ ${signed(p.logit)} log-odds cho ${escapeHtml(nameA)}.
    </p>`;
}

const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(3);
/* a log-space shift shown as the percentage change it implies */
const pctShift = (x) => `${x >= 0 ? '+' : ''}${((Math.exp(x) - 1) * 100).toFixed(1)}%`;

/* =========================================================================
   Data refresh
   ========================================================================= */
/* The button runs several phases back to back: teams/schedule first so the UI
   is usable, then the finished-results archive. */
let refreshQueue = [];

async function startRefresh() {
  // `history` is what recomputes the Elo ratings from the latest results, so
  // it has to be in the button's sequence -- without it the ratings never move.
  refreshQueue = state.teams.length ? ['core', 'history', 'players', 'results'] : ['all'];
  runNextPhase();
}

async function runNextPhase() {
  const phase = refreshQueue.shift();
  if (!phase) {
    setTimeout(() => $('refresh-bar').classList.add('hidden'), 2500);
    await Promise.allSettled([loadStatus(), loadTeams(), loadHeroes(), loadSchedule(),
                              loadHistory(state.historyScope)]);
    renderSide('a'); renderSide('b');
    return;
  }
  try {
    await api('/api/refresh', {
      method: 'POST',
      body: JSON.stringify({ phase, draft_limit: 400, result_days: 14 }),
    });
    $('refresh-bar').classList.remove('hidden');
    pollRefresh();
  } catch (err) {
    refreshQueue = [];
    toast(err.message);
  }
}

let pollTimer = null;
function pollRefresh() {
  $('refresh-bar').classList.remove('hidden');
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const job = await api('/api/refresh/status');
      $('refresh-phase').textContent = job.phase === 'idle' ? 'hoàn tất' : job.phase;
      $('refresh-msg').textContent = job.message || '';
      const pct = job.total ? Math.min(100, (job.done / job.total) * 100) : 0;
      $('refresh-fill').style.width = `${pct}%`;
      if (!job.running) {
        clearInterval(pollTimer);
        if (job.errors?.length) toast(`Hoàn tất kèm ${job.errors.length} cảnh báo.`, 5000);
        runNextPhase();
      }
    } catch (err) { clearInterval(pollTimer); refreshQueue = []; }
  }, 1200);
}

/* =========================================================================
   Events
   ========================================================================= */
function wireEvents() {
  for (const side of ['a', 'b']) {
    $(`team-btn-${side}`).addEventListener('click', (e) => {
      e.stopPropagation();
      const menu = $(`team-menu-${side}`);
      const wasHidden = menu.hidden;
      closeMenus();
      menu.hidden = !wasHidden;
      if (!menu.hidden) {
        const search = $(`team-search-${side}`);
        if (search) {
          search.value = '';
          renderTeamOptions(side);
          search.focus();
        }
      }
    });
  }
  document.addEventListener('click', closeMenus);

  $('btn-predict').addEventListener('click', predict);
  $('btn-refresh').addEventListener('click', startRefresh);
  $('btn-cancel').addEventListener('click', () => api('/api/refresh/cancel', { method: 'POST' }));
  $('btn-clear').addEventListener('click', () => {
    state.pick = { a: emptySide(), b: emptySide() };
    renderSide('a'); renderSide('b'); syncMenuDisabled(); updatePredictButton();
    $('result').classList.add('hidden');
  });

  for (const tab of $('history-tabs').children) {
    tab.addEventListener('click', () => loadHistory(tab.dataset.scope));
  }

  $('hero-search').addEventListener('input', (e) => { state.modal.q = e.target.value; renderHeroGrid(); });
  for (const b of $('attr-tabs').children) {
    b.addEventListener('click', () => {
      for (const x of $('attr-tabs').children) x.classList.remove('on');
      b.classList.add('on');
      state.modal.attr = b.dataset.attr;
      renderHeroGrid();
    });
  }
  for (const el of document.querySelectorAll('[data-close]')) {
    el.addEventListener('click', closeHeroModal);
  }
  for (const el of document.querySelectorAll('[data-close-player]')) {
    el.addEventListener('click', closePlayerModal);
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeHeroModal(); closePlayerModal(); closeMenus(); }
    if (e.key === 'Enter' && e.ctrlKey) predict();
  });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

boot();
