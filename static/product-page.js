/* One atomic product view for curated, customised and generated bundles. */
(() => {
  const view = document.querySelector('[data-product-view]');
  if (!view) return;
  const status = document.querySelector('[data-product-status]');
  const errorNote = document.querySelector('[data-view-error]');
  let activeRequest;
  let requestNumber = 0;
  history.replaceState({ velmora: true }, '', location.href);

  function revealCurrentPiece() {
    const strip = view.querySelector('.bundle-items');
    const current = strip?.querySelector('[aria-current="true"]');
    if (!current) return;
    const start = current.getBoundingClientRect().left - strip.getBoundingClientRect().left + strip.scrollLeft;
    const end = start + current.offsetWidth;
    if (start < strip.scrollLeft) strip.scrollLeft = start;
    else if (end > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = end - strip.clientWidth;
  }
  revealCurrentPiece();

  async function navigate(url, { pop = false } = {}) {
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    const number = ++requestNumber;
    view.setAttribute('aria-busy', 'true');
    view.inert = true;
    errorNote.hidden = true;
    try {
      const response = await fetch(url, {
        headers: { 'X-Velmora-View': 'product', Accept: 'application/json' },
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok || typeof data.html !== 'string') throw new Error(data.error || 'This selection could not be loaded.');
      if (number !== requestNumber) return;
      // Markup comes from the same escaped Jinja component as the initial page.
      view.innerHTML = data.html;
      document.title = data.title;
      document.querySelector('meta[name="description"]')?.setAttribute('content', view.querySelector('.product-description')?.textContent || '');
      if (!pop) history.pushState({ velmora: true }, '', url);
      document.dispatchEvent(new Event('velmora:product-ready'));
      revealCurrentPiece();
      status.textContent = `${view.querySelector('#product-title').textContent}, ${view.querySelector('[data-selected-colour]').textContent}`;
      const title = view.querySelector('#product-title');
      title.tabIndex = -1;
      view.inert = false;
      title.focus({ preventScroll: true });
    } catch (error) {
      if (error.name === 'AbortError' || number !== requestNumber) return;
      errorNote.replaceChildren(document.createTextNode('This selection could not be loaded. '));
      const retry = document.createElement('a');
      retry.href = url;
      retry.textContent = 'Reload this selection';
      errorNote.append(retry);
      errorNote.hidden = false;
      // A failed browser-history request must not display a different product at its URL.
      if (pop) view.hidden = true;
    } finally {
      if (number === requestNumber) {
        view.removeAttribute('aria-busy');
        view.inert = false;
        if (errorNote.hidden) view.hidden = false;
      }
    }
  }

  view.addEventListener('click', (event) => {
    const link = event.target.closest('a[data-product-link]');
    if (!link || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    navigate(link.href);
  });

  view.addEventListener('change', (event) => {
    if (!event.target.matches('[data-product-size]')) return;
    const state = view.querySelector('[data-product-state]');
    const url = new URL(location.href);
    if (state.dataset.bundleSizes !== undefined) {
      const sizes = state.dataset.bundleSizes.split('/');
      sizes[Number(state.dataset.itemIndex)] = event.target.value || '-';
      state.dataset.bundleSizes = sizes.join('/');
      url.searchParams.set('sizes', sizes.join('/'));
      url.searchParams.set('colours', state.dataset.bundleColours);
    } else {
      if (event.target.value) url.searchParams.set('size', event.target.value);
      else url.searchParams.delete('size');
    }
    history.replaceState({ velmora: true }, '', url);
    const buildLook = view.querySelector('[data-build-look]');
    if (buildLook) {
      const target = new URL(buildLook.href);
      if (event.target.value) target.searchParams.set('size', event.target.value);
      else target.searchParams.delete('size');
      buildLook.href = target;
    }
    view.querySelectorAll('a[data-product-link]').forEach((link) => {
      const target = new URL(link.href);
      for (const key of ['size', 'sizes']) {
        if (url.searchParams.has(key)) target.searchParams.set(key, url.searchParams.get(key));
        else target.searchParams.delete(key);
      }
      link.href = target;
    });
    view.querySelector('[data-bag-feedback]').hidden = true;
  });

  view.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-bag-form]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const feedback = form.querySelector('[data-bag-feedback]');
    if (button.disabled) return;
    button.disabled = true;
    feedback.hidden = true;
    try {
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Your selection could not be added. Please try again.');
      document.querySelectorAll('[data-bag-count]').forEach((label) => { label.textContent = data.count; });
      feedback.replaceChildren(document.createTextNode('Added to your bag. '));
      const link = document.createElement('a');
      link.href = '/bag';
      link.textContent = 'View bag';
      feedback.append(link);
    } catch (error) {
      feedback.textContent = error.message || 'Your selection could not be added. Please try again.';
    } finally {
      feedback.hidden = false;
      button.disabled = false;
    }
  });
  window.addEventListener('popstate', () => navigate(location.href, { pop: true }));
})();
