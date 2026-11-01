(() => {
  const drawer = document.querySelector('#mobile-navigation');
  const opener = document.querySelector('[data-menu-open]');
  if (!drawer || !opener) return;
  let scrollY = 0;
  let previousStyle = '';
  let destination = null;
  opener.addEventListener('click', () => {
    scrollY = window.scrollY;
    previousStyle = document.body.style.cssText;
    document.body.style.position = 'fixed';
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = '100%';
    drawer.showModal();
    opener.setAttribute('aria-expanded', 'true');
    drawer.querySelector('[data-menu-close]').focus();
  });
  const close = () => drawer.close();
  drawer.querySelector('[data-menu-close]').addEventListener('click', close);
  drawer.addEventListener('click', (event) => {
    if (event.target === drawer) {
      const rect = drawer.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
    }
    const link = event.target.closest('a');
    if (link) {
      const url = new URL(link.href);
      if (url.pathname === location.pathname && url.hash) {
        event.preventDefault();
        destination = url;
      }
      close();
    }
  });
  drawer.addEventListener('close', () => {
    document.body.style.cssText = previousStyle;
    window.scrollTo({ top: scrollY, behavior: 'instant' });
    opener.setAttribute('aria-expanded', 'false');
    opener.focus({ preventScroll: true });
    if (destination) {
      const target = document.getElementById(destination.hash.slice(1));
      history.pushState(null, '', destination);
      target?.scrollIntoView();
      destination = null;
    }
  });
  window.matchMedia('(min-width: 901px)').addEventListener('change', (event) => {
    if (event.matches && drawer.open) close();
  });
})();
