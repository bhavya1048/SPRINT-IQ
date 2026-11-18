/* ============================================================
   SprintIQ — main.js
   Handles sidebar toggle (collapse / mobile open), active nav
   ============================================================ */

(function () {
  'use strict';

  // ── Sidebar toggle ──────────────────────────────────────────
  const wrapper     = document.getElementById('wrapper');
  const toggleBtn   = document.getElementById('sidebar-toggle-btn');

  if (toggleBtn && wrapper) {
    toggleBtn.addEventListener('click', function () {
      const isMobile = window.innerWidth <= 768;
      if (isMobile) {
        wrapper.classList.toggle('sidebar-open');
      } else {
        wrapper.classList.toggle('sidebar-collapsed');
        // Persist preference
        const collapsed = wrapper.classList.contains('sidebar-collapsed');
        localStorage.setItem('siq-sidebar-collapsed', collapsed ? '1' : '0');
      }
    });

    // Restore sidebar state on desktop
    if (window.innerWidth > 768) {
      const stored = localStorage.getItem('siq-sidebar-collapsed');
      if (stored === '1') wrapper.classList.add('sidebar-collapsed');
    }
  }

  // ── Mobile overlay close ────────────────────────────────────
  document.addEventListener('click', function (e) {
    if (window.innerWidth > 768) return;
    const sidebar  = document.getElementById('sidebar-wrapper');
    if (sidebar && !sidebar.contains(e.target) && !toggleBtn.contains(e.target)) {
      wrapper.classList.remove('sidebar-open');
    }
  });

  // ── Mark active nav link ────────────────────────────────────
  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar-nav-link').forEach(function (link) {
    const href = link.getAttribute('href');
    if (href && (currentPath === href || (href !== '/' && currentPath.startsWith(href)))) {
      link.classList.add('active');
    }
  });

})();
