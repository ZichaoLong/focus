// Read by the native startup cover after the online document begins painting.
(() => {
  if (!document.body || document.readyState === 'loading') return false;
  if (!document.querySelector('meta[name="focus-mobile-contract"]')) return true;
  const shell = document.querySelector('.focus-shell');
  const ready = shell?.dataset.firstScreen ? shell.dataset.firstScreen === 'ready' : !!shell && !shell.querySelector('.gload');
  if (ready && !window.__focusFirstScreenFrame)
    requestAnimationFrame(() => requestAnimationFrame(() => { window.__focusFirstScreenFrame = true; }));
  return ready && window.__focusFirstScreenFrame === true;
})()
