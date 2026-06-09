/**
 * player-panel.js
 * Shared slide-in player profile panel for HoopIQ.
 * Include on any page after player-panel.css.
 *
 * Usage:
 *   PlayerPanel.open('LeBron James', 'nba')
 *   PlayerPanel.open('JAMES, MIKE', 'el')
 *
 * Add class "pp-trigger" to any element + data-player and data-league attributes:
 *   <span class="pp-trigger" data-player="Nikola Jokic" data-league="nba">Nikola Jokic</span>
 */

const PlayerPanel = (() => {
  const API = 'https://hoopiq-api-production-d3a4.up.railway.app';
  const NBA_HEADSHOT = id => `https://cdn.nba.com/headshots/nba/latest/260x190/${id}.png`;

  // Mock news per player (replace with real API later)
  const NEWS_MOCK = {
    default: [
      { type:'perf', title:'Check latest stats on NBA.com', meta:'HoopIQ · Today',
        body:'Real-time injury reports and news will be available in the next version of HoopIQ. For now, check official sources for the latest updates on this player.', source:'https://nba.com' },
    ]
  };

  const TAG_LABELS = { perf:'Performance', inj:'Injury', trade:'Trade', rest:'Rest' };

  let panelEl, overlayEl, newsPopupBg, currentSource = '#';

  function init() {
    if (document.getElementById('pp-panel')) return;

    // Inject panel HTML
    document.body.insertAdjacentHTML('beforeend', `
      <div class="pp-overlay" id="pp-overlay"></div>
      <div class="pp-panel" id="pp-panel">
        <div class="pp-header">
          <img class="pp-photo" id="pp-photo" src="" alt=""
               onerror="this.style.display='none';document.getElementById('pp-photo-fb').style.display='flex'">
          <div class="pp-photo-fb" id="pp-photo-fb"></div>
          <div class="pp-info">
            <div class="pp-name" id="pp-name">—</div>
            <div class="pp-sub"  id="pp-sub">—</div>
            <div class="pp-badges" id="pp-badges"></div>
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
          <div class="pp-popup-meta" id="pp-popup-meta"></div>
          <div class="pp-popup-body" id="pp-popup-body">—</div>
          <div class="pp-popup-source" id="pp-popup-source" onclick="PlayerPanel.openSource()">View full article →</div>
        </div>
      </div>
    `);

    panelEl      = document.getElementById('pp-panel');
    overlayEl    = document.getElementById('pp-overlay');
    newsPopupBg  = document.getElementById('pp-news-popup-bg');

    overlayEl.addEventListener('click', close);
    newsPopupBg.addEventListener('click', e => {
      if (e.target === newsPopupBg) closeNews();
    });

    // Delegate click handler for pp-trigger elements
    document.addEventListener('click', e => {
      const trigger = e.target.closest('.pp-trigger');
      if (trigger) {
        e.stopPropagation();
        const name   = trigger.dataset.player;
        const league = trigger.dataset.league || 'nba';
        if (name) open(name, league);
      }
    });
  }

  async function open(name, league = 'nba') {
    init();
    panelEl.classList.add('open');
    overlayEl.classList.add('open');
    document.getElementById('pp-body').innerHTML =
      '<div class="pp-loading"><div class="pp-spinner"></div>Loading...</div>';
    document.getElementById('pp-name').textContent = name;
    document.getElementById('pp-sub').textContent  = '';
    document.getElementById('pp-badges').innerHTML = '';
    document.getElementById('pp-photo').style.display = 'block';
    document.getElementById('pp-photo-fb').style.display = 'none';
    document.getElementById('pp-photo').src = '';
    document.getElementById('pp-photo-fb').textContent =
      name.split(/[\s,]+/).filter(Boolean).map(w => w[0]).join('').toUpperCase().slice(0,2);

    try {
      const endpoint = league === 'el'
        ? `${API}/euroleague/player/${encodeURIComponent(name)}`
        : `${API}/player/${encodeURIComponent(name)}`;
      const res  = await fetch(endpoint);
      if (!res.ok) throw new Error('Not found');
      const data = await res.json();
      render(data, league);
    } catch(e) {
      document.getElementById('pp-body').innerHTML =
        `<div class="pp-loading" style="color:#D85A30">Could not load player data</div>`;
    }
  }

  function render(data, league) {
    const s   = data.season || {};
    const isEl = league === 'el';

    // Photo
    const photoEl = document.getElementById('pp-photo');
    const fbEl    = document.getElementById('pp-photo-fb');
    if (!isEl && data.nba_id) {
      photoEl.src = NBA_HEADSHOT(data.nba_id);
      photoEl.style.display = 'block';
    } else {
      photoEl.style.display = 'none';
      fbEl.style.display = 'flex';
    }

    // Header
    document.getElementById('pp-name').textContent = data.name;
    document.getElementById('pp-sub').textContent  =
      `${s.team || data.team || '—'} · vs ${s.opp || '—'}`;

    // Trend badge
    const dk5 = (data.last10 || []).slice(-5).map(g => g.DK_PTS || 0);
    const dk10 = (data.last10 || []).map(g => g.DK_PTS || 0);
    const avg5  = dk5.length  ? dk5.reduce((a,b)=>a+b,0)/dk5.length  : 0;
    const avg10 = dk10.length ? dk10.reduce((a,b)=>a+b,0)/dk10.length : 0;
    const trend = avg5 > avg10 * 1.1 ? 'hot' : avg5 < avg10 * 0.9 ? 'cold' : 'flat';

    document.getElementById('pp-badges').innerHTML = [
      `<span class="pp-badge proj">Proj ${(data.proj_dk || 0).toFixed(1)} DK</span>`,
      trend === 'hot'  ? '<span class="pp-badge hot">Hot streak ↑</span>'  : '',
      trend === 'cold' ? '<span class="pp-badge cold">Cold stretch ↓</span>' : '',
      trend === 'flat' ? '<span class="pp-badge">On track →</span>' : '',
      `<span class="pp-badge ${isEl ? 'el' : ''}">${isEl ? 'Euroleague' : 'NBA'}</span>`,
    ].join('');

    // Stat categories
    const CATS = [
      {k:'pts',l:'PTS'},{k:'reb',l:'REB'},{k:'ast',l:'AST'},
      {k:'stl',l:'STL'},{k:'blk',l:'BLK'},{k:'fg3m',l:'3PM'},
      {k:'fg_pct',l:'FG%'},{k:'ft_pct',l:'FT%'},{k:'tov',l:'TO'},
    ];
    const fmtStat = (k,v) => {
      if (v === undefined || v === null) return '—';
      return k.includes('pct') ? (parseFloat(v)*100).toFixed(1)+'%' : parseFloat(v).toFixed(1);
    };

    const projStats = data.proj_stats || {};

    const statGrid = CATS.map(c => `
      <div class="pp-stat-card">
        <div class="pp-stat-val">${fmtStat(c.k, s[c.k])}</div>
        <div class="pp-stat-label">${c.l}</div>
        <div class="pp-stat-proj">${projStats[`proj_${c.k}`] !== undefined ? fmtStat(c.k, projStats[`proj_${c.k}`]) : '—'}</div>
      </div>`).join('');

    // Trend bars from last10
    const dkVals = dk10.length ? dk10 : Array(10).fill(0);
    const maxDk  = Math.max(...dkVals, 1);
    const trendBars = dkVals.map(v => {
      const h   = Math.round((v / maxDk) * 100);
      const cls = v >= maxDk * .8 ? 'hi' : v >= maxDk * .5 ? 'md' : 'lo';
      return `<div class="pp-tbar ${cls}" style="height:${h}%" title="${v.toFixed(1)} DK"></div>`;
    }).join('');

    // Game log (last 10, all 9 cats)
    const games    = (data.last10 || []).slice().reverse();
    const logRows  = games.map(g => `
      <tr>
        <td>${g.GAME_DATE || '—'}</td>
        <td>${g.OPP || '—'}</td>
        <td>${g.PTS ?? '—'}</td>
        <td>${g.REB ?? '—'}</td>
        <td>${g.AST ?? '—'}</td>
        <td>${g.STL ?? '—'}</td>
        <td>${g.BLK ?? '—'}</td>
        <td>${g.FG3M ?? '—'}</td>
        <td>${g.FG_PCT !== undefined ? (g.FG_PCT*100).toFixed(1)+'%' : '—'}</td>
        <td>${g.FT_PCT !== undefined ? (g.FT_PCT*100).toFixed(1)+'%' : '—'}</td>
        <td>${g.TOV ?? '—'}</td>
        <td class="pp-td-g">${g.DK_PTS !== undefined ? parseFloat(g.DK_PTS).toFixed(1) : '—'}</td>
      </tr>`).join('') || '<tr><td colspan="12" style="text-align:center;padding:12px;color:#9ca3af">No game data</td></tr>';

    // Projection bars
    const projKeys = ['pts','reb','ast','stl','blk','fg3m','tov'];
    const projVals = projKeys.map(k => parseFloat(projStats[`proj_${k}`] || s[k] || 0));
    const maxProj  = Math.max(...projVals, 1);
    const projBars = projKeys.map((k,i) => `
      <div class="pp-proj-row">
        <div class="pp-proj-lbl">${CATS.find(c=>c.k===k)?.l||k}</div>
        <div class="pp-proj-track">
          <div class="pp-proj-fill" style="width:${Math.round((projVals[i]/maxProj)*100)}%"></div>
        </div>
        <div class="pp-proj-val">${fmtStat(k, projVals[i])}</div>
      </div>`).join('');

    // News (mock for now)
    const newsItems = NEWS_MOCK[data.name] || NEWS_MOCK.default;
    const newsHtml  = newsItems.map(n => `
      <div class="pp-news-item" onclick="PlayerPanel.openNews(${JSON.stringify(n).replace(/'/g,'&#39;')})">
        <div class="pp-news-dot ${n.type}"></div>
        <div class="pp-news-content">
          <div class="pp-news-title">${n.title}<span class="pp-news-tag ${n.type}">${TAG_LABELS[n.type]}</span></div>
          <div class="pp-news-meta">${n.meta}</div>
        </div>
      </div>`).join('');

    document.getElementById('pp-body').innerHTML = `
      <div class="pp-sec-title">Season averages · projected below</div>
      <div class="pp-stat-grid">${statGrid}</div>

      <div class="pp-sec-title">Last 10 games — DK trend</div>
      <div class="pp-trend-wrap">
        <div class="pp-trend-bars">${trendBars}</div>
        <div class="pp-trend-foot">
          <span class="pp-trend-date">10 games ago</span>
          <span class="pp-trend-date">most recent</span>
        </div>
      </div>

      <div class="pp-sec-title">Last 10 games log</div>
      <div class="pp-log-wrap">
        <table class="pp-log-tbl">
          <thead><tr>
            <th>Date</th><th>Opp</th>
            <th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th>
            <th>3PM</th><th>FG%</th><th>FT%</th><th>TO</th><th>DK</th>
          </tr></thead>
          <tbody>${logRows}</tbody>
        </table>
      </div>

      <div class="pp-sec-title">Projection breakdown</div>
      <div class="pp-proj-wrap">${projBars}</div>

      <div class="pp-sec-title">News & updates</div>
      <div class="pp-news-wrap">${newsHtml}</div>
    `;
  }

  function close() {
    if (!panelEl) return;
    panelEl.classList.remove('open');
    overlayEl.classList.remove('open');
  }

  function openNews(n) {
    document.getElementById('pp-popup-title').textContent = n.title;
    document.getElementById('pp-popup-meta').innerHTML =
      `<span style="font-size:9px;padding:1px 5px;border-radius:4px;background:#f4f4f6;color:#6b7280">${TAG_LABELS[n.type]||n.type}</span> ${n.meta}`;
    document.getElementById('pp-popup-body').textContent  = n.body;
    document.getElementById('pp-popup-source').style.display = n.source && n.source !== '#' ? 'block' : 'none';
    currentSource = n.source;
    newsPopupBg.classList.add('open');
  }

  function closeNews() {
    newsPopupBg.classList.remove('open');
  }

  function openSource() {
    if (currentSource && currentSource !== '#') window.open(currentSource, '_blank');
  }

  return { open, close, openNews, closeNews, openSource, init };
})();
