/**
 * nav.js — shared navigation for Courtside
 * Injects a consistent top nav with smart back button on every page.
 * Include via <script src="nav.js" defer></script> in <head>.
 */

(function() {
  const PAGES = {
    'home.html':      { label: 'Home',         icon: '🏠' },
    'index.html':     { label: 'Projections',  icon: '📊' },
    'lobby.html':     { label: 'New League',   icon: '🏀' },
    'draft.html':     { label: 'Draft',        icon: '🏀' },
    'auction.html':   { label: 'Auction',      icon: '🔨' },
    'waivers.html':   { label: 'Waivers',      icon: '📋' },
    'matchup.html':   { label: 'Matchup',      icon: '⚔️'  },
    'league.html':    { label: 'My League',    icon: '🏆' },
    'dashboard.html': { label: 'Dashboard',    icon: '🏠' },
    'auth.html':      { label: 'Sign In',      icon: '👤' },
  };

  // Determine current page
  const path    = window.location.pathname;
  const current = Object.keys(PAGES).find(p => path.endsWith(p)) || 'index.html';

  // Nav order for breadcrumb logic
  const NAV_ORDER = ['index.html','lobby.html','league.html','draft.html','auction.html','waivers.html','matchup.html'];

  function canGoBack() {
    return window.history.length > 1;
  }

  function getBackLabel() {
    // Try to infer a sensible back label from referrer
    const ref = document.referrer;
    if (ref) {
      const match = Object.keys(PAGES).find(p => ref.includes(p));
      if (match) return PAGES[match].label;
    }
    // Fallback: go one step up in nav order
    const idx = NAV_ORDER.indexOf(current);
    if (idx > 0) return PAGES[NAV_ORDER[idx - 1]].label;
    return 'Home';
  }

  function goBack() {
    if (canGoBack()) {
      window.history.back();
    } else {
      window.location.href = 'index.html';
    }
  }

  // Preserve URL params for waiver/matchup links
  function linkWithParams(page) {
    // Try URL params first, then localStorage
    const p       = new URLSearchParams(window.location.search);
    let code      = p.get('code');
    let team      = p.get('team');
    let manager   = p.get('manager');
    if (!code || !team) {
      try {
        const saved = JSON.parse(localStorage.getItem('courtside_league') || '{}');
        if (!code)    code    = saved.code;
        if (!team)    team    = saved.team;
        if (!manager) manager = saved.manager;
      } catch(e) {}
    }
    const leaguePages = ['waivers.html','matchup.html','league.html','draft.html','auction.html'];
    if (code && team && leaguePages.includes(page)) {
      const params = new URLSearchParams({code, team});
      if (manager) params.set('manager', manager);
      return `${page}?${params}`;
    }
    return page;
  }

  // Bottom nav items (mobile only) — 5 fixed destinations
  const BOTTOM_NAV = [
    { page: 'home.html',    label: 'Home',     icon: '🏠', match: ['home.html'] },
    { page: 'index.html',   label: 'Players',  icon: '📊', match: ['index.html','waivers.html'] },
    { page: 'league.html',  label: 'League',   icon: '🏆', match: ['league.html','draft.html','auction.html'] },
    { page: 'matchup.html', label: 'Matchup',  icon: '⚔️', match: ['matchup.html'] },
    { page: 'account.html', label: 'Account',  icon: '👤', match: ['dashboard.html','auth.html'] },
  ];

  function getSavedLeague() {
    const p = new URLSearchParams(window.location.search);
    let code = p.get('code'), team = p.get('team'), manager = p.get('manager');
    if (!code || !team) {
      try {
        const saved = JSON.parse(localStorage.getItem('courtside_league') || '{}');
        if (!code)    code    = saved.code;
        if (!team)    team    = saved.team;
        if (!manager) manager = saved.manager;
      } catch(e) {}
    }
    return { code, team, manager };
  }

  function bottomNavHref(item) {
    const leaguePages = ['league.html','draft.html','auction.html','matchup.html'];
    if (item.page === 'account.html') {
      try {
        const sess = JSON.parse(localStorage.getItem('courtside_session') || 'null');
        return sess?.access_token ? 'dashboard.html' : 'auth.html';
      } catch(e) { return 'auth.html'; }
    }
    if (leaguePages.includes(item.page)) {
      const { code, team, manager } = getSavedLeague();
      if (!code || !team) return 'lobby.html';
      const params = new URLSearchParams({ code, team });
      if (manager) params.set('manager', manager);
      return `${item.page}?${params}`;
    }
    return item.page;
  }

  function injectNav() {
    // Remove any existing nav the page already has
    const existing = document.querySelector('.courtside-nav');
    if (existing) return; // already injected

    const backLabel = getBackLabel();
    const isHome    = current === 'index.html' || current === 'home.html';

    const nav = document.createElement('div');
    nav.className = 'courtside-nav';
    nav.innerHTML = `
      <style>
        .courtside-nav {
          position: sticky;
          top: 0;
          z-index: 200;
          background: #fff;
          border-bottom: 1px solid #e8e8ec;
          padding: 0 16px;
        }
        .courtside-nav-inner {
          max-width: 1200px;
          margin: 0 auto;
          display: flex;
          align-items: center;
          height: 52px;
          gap: 8px;
        }
        .hn-back {
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 5px 10px;
          border-radius: 8px;
          border: 1px solid #e8e8ec;
          background: #fff;
          font-size: 12px;
          font-weight: 600;
          color: #6b7280;
          cursor: pointer;
          flex-shrink: 0;
          transition: background .15s, color .15s;
          text-decoration: none;
        }
        .hn-back:hover { background: #f4f4f6; color: #111827; }
        .hn-back-arrow { font-size: 14px; }
        .hn-logo {
          font-size: 17px;
          font-weight: 700;
          color: #111827;
          text-decoration: none;
          flex-shrink: 0;
        }
        .hn-logo span { color: #2C5F8A; }
        .hn-divider {
          width: 1px;
          height: 20px;
          background: #e8e8ec;
          flex-shrink: 0;
        }
        .hn-current {
          font-size: 13px;
          font-weight: 600;
          color: #111827;
          flex: 1;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .hn-links {
          display: flex;
          align-items: center;
          gap: 4px;
          flex-shrink: 0;
        }
        .hn-link {
          font-size: 12px;
          font-weight: 500;
          color: #6b7280;
          text-decoration: none;
          padding: 4px 8px;
          border-radius: 7px;
          transition: background .15s, color .15s;
          white-space: nowrap;
        }
        .hn-link:hover { background: #f4f4f6; color: #111827; }
        .hn-link.active {
          color: #2C5F8A;
          background: #E3EEF6;
        }
        @media (max-width: 480px) {
          .hn-links { display: none; }
          .hn-current { display: none; }
        }
        .cs-bottom-nav {
          display: none;
        }
        @media (max-width: 480px) {
          .cs-bottom-nav {
            display: flex;
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            z-index: 201;
            background: #fff;
            border-top: 1px solid #e8e8ec;
            padding: 4px 4px calc(4px + env(safe-area-inset-bottom));
            justify-content: space-between;
          }
          body { padding-bottom: calc(54px + env(safe-area-inset-bottom)); }
        }
        .cs-bn-item {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 2px;
          padding: 6px 2px;
          text-decoration: none;
          color: #9ca3af;
          font-size: 10px;
          font-weight: 600;
          border-radius: 10px;
          transition: color .15s, background .15s;
        }
        .cs-bn-item:active { background: #f4f4f6; }
        .cs-bn-item.active { color: #2C5F8A; }
        .cs-bn-icon { font-size: 19px; line-height: 1; }
      </style>
      <div class="courtside-nav-inner">
        ${!isHome ? `
          <button class="hn-back" onclick="window.PlayerPanelNav.goBack()">
            <span class="hn-back-arrow">←</span>
            <span>${backLabel}</span>
          </button>
          <div class="hn-divider"></div>
        ` : ''}
        <a class="hn-logo" href="home.html">Court<span>side</span></a>
        <div class="hn-current">${PAGES[current]?.label || ''}</div>
        <div class="hn-links">
          <a class="hn-link ${current==='index.html'?'active':''}"    href="${linkWithParams('index.html')}">Projections</a>
          <a class="hn-link ${current==='lobby.html'?'active':''}"    href="lobby.html">New League</a>
          <a class="hn-link ${current==='league.html'?'active':''}"   href="${linkWithParams('league.html')}">My League</a>
          <a class="hn-link ${current==='waivers.html'?'active':''}"  href="${linkWithParams('waivers.html')}">Waivers</a>
          <a class="hn-link ${current==='matchup.html'?'active':''}"  href="${linkWithParams('matchup.html')}">Matchup</a>
          ${(()=>{
            try {
              const sess = JSON.parse(localStorage.getItem('courtside_session')||'null');
              if (sess?.access_token) {
                return \`<a class="hn-link ${current==='dashboard.html'?'active':''}" href="dashboard.html">Dashboard</a>\`;
              }
              return \`<a class="hn-link ${current==='auth.html'?'active':''}" href="auth.html">Sign in</a>\`;
            } catch(e) { return ''; }
          })()}
        </div>
      </div>
    `;

    // Insert before first child of body
    document.body.insertBefore(nav, document.body.firstChild);

    // Remove any old nav the page may have had
    document.querySelectorAll('.nav').forEach(el => {
      // Don't remove if it's our injected nav
      if (!el.classList.contains('courtside-nav')) el.remove();
    });

    // ── Bottom tab bar (mobile only) ────────────────────────────────────
    if (!document.querySelector('.cs-bottom-nav')) {
      const bottomNav = document.createElement('div');
      bottomNav.className = 'cs-bottom-nav';
      bottomNav.innerHTML = BOTTOM_NAV.map(item => {
        const isActive = item.match.includes(current);
        return `
          <a class="cs-bn-item ${isActive ? 'active' : ''}" href="${bottomNavHref(item)}">
            <span class="cs-bn-icon">${item.icon}</span>
            <span>${item.label}</span>
          </a>`;
      }).join('');
      document.body.appendChild(bottomNav);
    }
  }

  // Expose goBack globally
  window.PlayerPanelNav = { goBack };

  // Inject on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectNav);
  } else {
    injectNav();
  }
})();
