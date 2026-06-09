/**
 * nav.js — shared navigation for HoopIQ
 * Injects a consistent top nav with smart back button on every page.
 * Include via <script src="nav.js" defer></script> in <head>.
 */

(function() {
  const PAGES = {
    'index.html':   { label: 'Projections',  icon: '📊' },
    'lobby.html':   { label: 'Draft Lobby',  icon: '🏀' },
    'draft.html':   { label: 'Draft',        icon: '🏀' },
    'waivers.html': { label: 'Waivers',      icon: '📋' },
    'matchup.html': { label: 'Matchup',      icon: '⚔️'  },
  };

  // Determine current page
  const path    = window.location.pathname;
  const current = Object.keys(PAGES).find(p => path.endsWith(p)) || 'index.html';

  // Nav order for breadcrumb logic
  const NAV_ORDER = ['index.html','lobby.html','draft.html','waivers.html','matchup.html'];

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
    const p = new URLSearchParams(window.location.search);
    const code = p.get('code');
    const team = p.get('team');
    if (code && team && (page === 'waivers.html' || page === 'matchup.html')) {
      return `${page}?code=${code}&team=${encodeURIComponent(team)}`;
    }
    return page;
  }

  function injectNav() {
    // Remove any existing nav the page already has
    const existing = document.querySelector('.hoopiq-nav');
    if (existing) return; // already injected

    const backLabel = getBackLabel();
    const isHome    = current === 'index.html';

    const nav = document.createElement('div');
    nav.className = 'hoopiq-nav';
    nav.innerHTML = `
      <style>
        .hoopiq-nav {
          position: sticky;
          top: 0;
          z-index: 200;
          background: #fff;
          border-bottom: 1px solid #e8e8ec;
          padding: 0 16px;
        }
        .hoopiq-nav-inner {
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
        .hn-logo span { color: #1D9E75; }
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
          color: #1D9E75;
          background: #E1F5EE;
        }
        @media (max-width: 480px) {
          .hn-links { display: none; }
          .hn-current { display: none; }
        }
      </style>
      <div class="hoopiq-nav-inner">
        ${!isHome ? `
          <button class="hn-back" onclick="window.PlayerPanelNav.goBack()">
            <span class="hn-back-arrow">←</span>
            <span>${backLabel}</span>
          </button>
          <div class="hn-divider"></div>
        ` : ''}
        <a class="hn-logo" href="index.html">Hoop<span>IQ</span></a>
        <div class="hn-current">${PAGES[current]?.label || ''}</div>
        <div class="hn-links">
          <a class="hn-link ${current==='index.html'?'active':''}"    href="${linkWithParams('index.html')}">Projections</a>
          <a class="hn-link ${current==='lobby.html'?'active':''}"    href="lobby.html">Draft</a>
          <a class="hn-link ${current==='waivers.html'?'active':''}"  href="${linkWithParams('waivers.html')}">Waivers</a>
          <a class="hn-link ${current==='matchup.html'?'active':''}"  href="${linkWithParams('matchup.html')}">Matchup</a>
        </div>
      </div>
    `;

    // Insert before first child of body
    document.body.insertBefore(nav, document.body.firstChild);

    // Remove any old nav the page may have had
    document.querySelectorAll('.nav').forEach(el => {
      // Don't remove if it's our injected nav
      if (!el.classList.contains('hoopiq-nav')) el.remove();
    });
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
