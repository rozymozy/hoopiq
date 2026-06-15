/**
 * player-panel.js — HoopIQ shared player profile panel
 * Slide-in panel wired to live API.
 * Include after player-panel.css on any page.
 */

const PlayerPanel = (() => {
  const API = 'https://hoopiq-api-production-d3a4.up.railway.app';

  // Mock news — replace with real API later
  const NEWS_MOCK = {
    default: [
      { type:'perf',
        title:'Check latest stats on NBA.com',
        meta:'HoopIQ · Today',
        body:'Real-time injury reports and news will be available in a future version of HoopIQ. Check official sources for the latest updates on this player.',
        source:'https://nba.com' },
    ]
  };
  const TAG_LABELS = { perf:'Performance', inj:'Injury', trade:'Trade', rest:'Rest' };

  let panelEl, overlayEl, newsPopupBg, currentSource = '#';

  // ── INIT — inject DOM once ─────────────────────────────────────────────────
  function init() {
    if (document.getElementById('pp-panel')) return;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="pp-overlay" id="pp-overlay"></div>
      <div class="pp-panel" id="pp-panel">
        <div class="pp-header">
          <img class="pp-photo" id="pp-photo" src="" alt=""
               onerror="this.style.display='none';document.getElementById('pp-photo-fb').style.display='flex'">
          <div class="pp-photo-fb" id="pp-photo-fb"></div>
          <div class="pp-info">
            <div class="pp-name"    id="pp-name">—</div>
            <div class="pp-sub"     id="pp-sub">—</div>
            <div class="pp-badges"  id="pp-badges"></div>
          </div>
          <button class="pp-close" onclick="PlayerPanel.close()">✕</button>
        </div>
        <div class="pp-body" id="pp-body">
          <div class="pp-loading"><div class="pp-spinner"></div>Loading...</div>
        </div>
      </div>
      <div class="pp-news-popup-bg" id="pp-news-popup-bg">
        <div class="pp-news-popup">
          <div class="pp-popup-header">
            <div class="pp-popup-title" id="pp-popup-title">—</div>
            <button class="pp-popup-close" onclick="PlayerPanel.closeNews()">✕</button>
          </div>
          <div class="pp-popup-meta"  id="pp-popup-meta"></div>
          <div class="pp-popup-body"  id="pp-popup-body">—</div>
          <div class="pp-popup-source" id="pp-popup-source"
               onclick="PlayerPanel.openSource()">View full article →</div>
        </div>
      </div>
    `);

    panelEl     = document.getElementById('pp-panel');
    overlayEl   = document.getElementById('pp-overlay');
    newsPopupBg = document.getElementById('pp-news-popup-bg');

    overlayEl.addEventListener('click', close);
    newsPopupBg.addEventListener('click', e => {
      if (e.target === newsPopupBg) closeNews();
    });

    // Delegated listener (fallback for elements without inline onclick)
    document.addEventListener('click', e => {
      const trigger = e.target.closest('.pp-trigger');
      if (trigger) {
        e.stopPropagation();
        const name   = (trigger.dataset.player || '').trim();
        const league = (trigger.dataset.league || 'nba').trim().toLowerCase();
        if (name && name !== '[object Object]') open(name, league);
      }
    });
  }

  // ── OPEN ───────────────────────────────────────────────────────────────────
  async function open(name, league = 'nba') {
    // Guard: ensure name is a plain string, not an object
    name   = (typeof name   === 'string' ? name   : String(name   || '')).trim();
    league = (typeof league === 'string' ? league : String(league || 'nba')).trim().toLowerCase();
    if (!name || name === '[object Object]') return;

    init();

    // Show panel immediately with loading state
    panelEl.classList.add('open');
    overlayEl.classList.add('open');

    // Reset header
    document.getElementById('pp-name').textContent    = name;
    document.getElementById('pp-sub').textContent     = '';
    document.getElementById('pp-badges').innerHTML    = '';
    document.getElementById('pp-body').innerHTML      =
      '<div class="pp-loading"><div class="pp-spinner"></div>Loading...</div>';

    // Photo — show initials immediately, try NBA CDN headshot
    const photoEl = document.getElementById('pp-photo');
    const fbEl    = document.getElementById('pp-photo-fb');
    fbEl.textContent = name.split(/[\s,]+/).filter(Boolean)
                           .map(w => w[0]).join('').toUpperCase().slice(0, 2);
    photoEl.style.display = 'none';
    fbEl.style.display    = 'flex';

    try {
      const endpoint = league === 'el'
        ? `${API}/euroleague/player/${encodeURIComponent(name)}`
        : `${API}/player/${encodeURIComponent(name)}`;
      const res  = await fetch(endpoint);
      if (!res.ok) throw new Error('Player not found');
      const data = await res.json();
      render(data, league);
    } catch(err) {
      document.getElementById('pp-body').innerHTML =
        `<div class="pp-loading" style="color:#D85A30">
           Could not load player data.<br>
           <span style="font-size:11px;color:#9ca3af">${err.message}</span>
         </div>`;
    }
  }

  // ── RENDER ─────────────────────────────────────────────────────────────────
  function render(data, league) {
    const s    = data.season || {};
    const isEl = league === 'el';

    // ── Header sub-line
    document.getElementById('pp-name').textContent = data.name;
    document.getElementById('pp-sub').textContent  =
      `${data.team || s.team || '—'} · ${isEl ? 'Euroleague' : 'NBA'}`;

    // ── Trend: compare last 5 DK avg vs full 10-game DK avg
    const last10 = data.last10 || [];
    const dk10   = last10.map(g => parseFloat(g.DK_PTS) || 0);
    const dk5    = dk10.slice(-5);
    const avg10  = dk10.length ? dk10.reduce((a,b)=>a+b,0) / dk10.length : 0;
    const avg5   = dk5.length  ? dk5.reduce((a,b)=>a+b,0)  / dk5.length  : 0;
    const trend  = avg5 > avg10 * 1.1 ? 'hot' : avg5 < avg10 * 0.9 ? 'cold' : 'flat';

    const teamsThisSeason = data.teams_this_season || [];
    const wasTraded = teamsThisSeason.length > 1;

    document.getElementById('pp-badges').innerHTML = [
      `<span class="pp-badge proj">Proj ${parseFloat(data.proj_dk || 0).toFixed(1)} DK</span>`,
      trend === 'hot'  ? '<span class="pp-badge hot">Hot streak ↑</span>'   : '',
      trend === 'cold' ? '<span class="pp-badge cold">Cold stretch ↓</span>': '',
      trend === 'flat' ? '<span class="pp-badge">On track →</span>'         : '',
      `<span class="pp-badge ${isEl?'el':''}">${isEl ? 'Euroleague' : 'NBA'}</span>`,
      wasTraded ? `<span class="pp-badge trade" title="Played for: ${teamsThisSeason.join(', ')}">🔁 Traded (${teamsThisSeason.join(' → ')})</span>` : '',
    ].join('');

    // ── Stat helpers
    const CATS = [
      {k:'pts',l:'PTS'},{k:'reb',l:'REB'},{k:'ast',l:'AST'},
      {k:'stl',l:'STL'},{k:'blk',l:'BLK'},{k:'fg3m',l:'3PM'},
      {k:'fg_pct',l:'FG%'},{k:'ft_pct',l:'FT%'},{k:'tov',l:'TO'},
    ];
    const fmt = (k, v) => {
      if (v === undefined || v === null || isNaN(parseFloat(v))) return '—';
      return k.includes('pct')
        ? (parseFloat(v) * 100).toFixed(1) + '%'
        : parseFloat(v).toFixed(1);
    };

    // ── Season averages grid (9 cats, proj = same value since no proj_stats yet)
    const statGrid = CATS.map(c => `
      <div class="pp-stat-card">
        <div class="pp-stat-val">${fmt(c.k, s[c.k])}</div>
        <div class="pp-stat-label">${c.l}</div>
        <div class="pp-stat-proj">${fmt(c.k, s[c.k])}</div>
      </div>`).join('');

    // ── Trend bars (DK_PTS per game)
    const maxDk    = Math.max(...dk10, 1);
    const trendBars = dk10.map(v => {
      const h   = Math.round((v / maxDk) * 100);
      const cls = v >= maxDk * .8 ? 'hi' : v >= maxDk * .5 ? 'md' : 'lo';
      return `<div class="pp-tbar ${cls}" style="height:${Math.max(h,3)}%"
                   title="${v.toFixed(1)} DK"></div>`;
    }).join('');

    // ── Game log — only columns the API actually returns
    // API last10 keys: GAME_DATE, OPP, PTS, REB, AST, STL, BLK, TOV, DK_PTS, MIN
    const games   = last10.slice().reverse();  // most recent first
    const logRows = games.map(g => `
      <tr>
        <td>${(g.GAME_DATE || '—').slice(0,10)}</td>
        <td>${g.TEAM  ?? '—'}</td>
        <td>${g.OPP   ?? '—'}</td>
        <td>${g.PTS   ?? '—'}</td>
        <td>${g.REB   ?? '—'}</td>
        <td>${g.AST   ?? '—'}</td>
        <td>${g.STL   ?? '—'}</td>
        <td>${g.BLK   ?? '—'}</td>
        <td>${g.TOV   ?? '—'}</td>
        <td class="pp-td-g">${g.DK_PTS !== undefined
              ? parseFloat(g.DK_PTS).toFixed(1) : '—'}</td>
      </tr>`).join('')
      || '<tr><td colspan="10" style="text-align:center;padding:12px;color:#9ca3af">No game data</td></tr>';

    // ── Season history — current + previous 3 seasons, split by team if traded
    const seasonHistory = data.season_history || [];
    const SH_CATS = ['pts','reb','ast','stl','blk','tov','fg3m','fg_pct','ft_pct'];
    const seasonHistoryHtml = seasonHistory.map(sh => {
      if (!sh.available) {
        return `
          <div class="pp-sh-row pp-sh-unavailable">
            <div class="pp-sh-season">${sh.season}</div>
            <div class="pp-sh-team">—</div>
            <div class="pp-sh-na">Data not available</div>
          </div>`;
      }
      const statCells = SH_CATS.map(k => `
        <div class="pp-sh-stat">
          <div class="pp-sh-stat-val">${fmt(k, sh[k] ?? 0)}</div>
          <div class="pp-sh-stat-lbl">${CATS.find(c=>c.k===k)?.l || k.toUpperCase()}</div>
        </div>`).join('');
      const rowClass = sh.is_total ? 'pp-sh-row pp-sh-total'
                     : sh.traded_entry ? 'pp-sh-row pp-sh-traded' : 'pp-sh-row';
      return `
        <div class="${rowClass}">
          <div class="pp-sh-header">
            <div class="pp-sh-season">${sh.season}</div>
            <div class="pp-sh-team">${sh.is_total ? 'Total' : (sh.team || '—')}</div>
            <div class="pp-sh-games">${sh.games} GP</div>
          </div>
          <div class="pp-sh-stats">${statCells}</div>
        </div>`;
    }).join('');

    // ── News (mock)
    const newsItems = NEWS_MOCK[data.name] || NEWS_MOCK.default;
    const newsHtml  = newsItems.map(n => `
      <div class="pp-news-item"
           onclick="PlayerPanel.openNews(${JSON.stringify(n).replace(/'/g,'&#39;')})">
        <div class="pp-news-dot ${n.type}"></div>
        <div class="pp-news-content">
          <div class="pp-news-title">
            ${n.title}
            <span class="pp-news-tag ${n.type}">${TAG_LABELS[n.type]}</span>
          </div>
          <div class="pp-news-meta">${n.meta}</div>
        </div>
      </div>`).join('');

    // ── Inject everything
    document.getElementById('pp-body').innerHTML = `
      <div class="pp-sec-title">Season averages</div>
      <div class="pp-stat-grid">${statGrid}</div>

      <div class="pp-sec-title">Last 10 games — DK trend</div>
      <div class="pp-trend-wrap">
        <div class="pp-trend-bars">${trendBars.length ? trendBars : '<div style="color:#9ca3af;font-size:11px;padding:8px">No trend data</div>'}</div>
        <div class="pp-trend-foot">
          <span class="pp-trend-date">10 games ago</span>
          <span class="pp-trend-date">most recent</span>
        </div>
      </div>

      <div class="pp-sec-title">Last 10 games</div>
      <div class="pp-log-wrap">
        <table class="pp-log-tbl">
          <thead><tr>
            <th>Date</th><th>Team</th><th>Opp</th>
            <th>PTS</th><th>REB</th><th>AST</th>
            <th>STL</th><th>BLK</th><th>TO</th><th>DK</th>
          </tr></thead>
          <tbody>${logRows}</tbody>
        </table>
      </div>

      <div class="pp-sec-title">Season History</div>
      <div class="pp-sh-wrap">${seasonHistoryHtml || '<div style="color:#9ca3af;font-size:11px;padding:8px">No season history</div>'}</div>

      <div class="pp-sec-title">News & updates</div>
      <div class="pp-news-wrap">${newsHtml}</div>
    `;
  }

  // ── CLOSE ──────────────────────────────────────────────────────────────────
  function close() {
    if (!panelEl) return;
    panelEl.classList.remove('open');
    overlayEl.classList.remove('open');
  }

  // ── NEWS POPUP ─────────────────────────────────────────────────────────────
  function openNews(n) {
    document.getElementById('pp-popup-title').textContent = n.title;
    document.getElementById('pp-popup-meta').innerHTML =
      `<span style="font-size:9px;padding:1px 5px;border-radius:4px;
         background:#f4f4f6;color:#6b7280">${TAG_LABELS[n.type]||n.type}</span>
       &nbsp;${n.meta}`;
    document.getElementById('pp-popup-body').textContent = n.body;
    currentSource = n.source;
    document.getElementById('pp-popup-source').style.display =
      n.source && n.source !== '#' ? 'block' : 'none';
    newsPopupBg.classList.add('open');
  }

  function closeNews() { newsPopupBg.classList.remove('open'); }
  function openSource() {
    if (currentSource && currentSource !== '#') window.open(currentSource, '_blank');
  }

  return { open, close, openNews, closeNews, openSource, init };
})();
