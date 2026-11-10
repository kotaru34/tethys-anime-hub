/* Client-only theme switcher; user preference is local until account settings ship. */
(function () {
  'use strict';
  const key = 'tethys-theme';
  const allowed = new Set(['system', 'dark', 'light', 'amoled']);
  const media = window.matchMedia('(prefers-color-scheme: light)');
  function saved() {
    try { const value = localStorage.getItem(key) || 'dark'; return allowed.has(value) ? value : 'dark'; }
    catch (_) { return 'dark'; }
  }
  function apply(value) {
    document.documentElement.dataset.theme = value === 'system' ? (media.matches ? 'light' : 'dark') : value;
  }
  document.addEventListener('DOMContentLoaded', () => {
    const picker = document.getElementById('theme-select');
    if (!picker) return;
    picker.value = saved();
    picker.addEventListener('change', () => {
      if (!allowed.has(picker.value)) return;
      try { localStorage.setItem(key, picker.value); } catch (_) { /* Private mode: still apply. */ }
      apply(picker.value);
    });
    media.addEventListener('change', () => { if (saved() === 'system') apply('system'); });
  });
})();
