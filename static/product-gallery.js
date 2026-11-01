/* Genuine catalogue photographs only. Reinitialised after a product switch. */
(() => {
  const initialised = new WeakSet();
  function init() {
    document.querySelectorAll('[data-product-gallery]').forEach((gallery) => {
      if (initialised.has(gallery)) return;
      initialised.add(gallery);
      const stage = gallery.querySelector('[data-gallery-stage]');
      const images = [...gallery.querySelectorAll('[data-product-image]')];
      const triggers = [...gallery.querySelectorAll('[data-gallery-trigger]')];
      const dialog = gallery.querySelector('[data-gallery-dialog]');
      const zoomImage = gallery.querySelector('[data-zoom-image]');
      const zoomButton = gallery.querySelector('[data-gallery-zoom]');
      const closeButton = gallery.querySelector('[data-close-zoom]');
      if (!stage) return;
      const state = gallery.closest('[data-product-state]');
      triggers.forEach((trigger) => trigger.addEventListener('click', (event) => {
        if (trigger.dataset.colour !== state.dataset.colour) return;
        event.preventDefault();
        event.stopPropagation();
        const index = trigger.dataset.photoIndex;
        images.forEach((image) => { image.hidden = image.dataset.photoIndex !== index; });
        triggers.forEach((button) => {
          if (button === trigger) button.setAttribute('aria-current', 'true');
          else button.removeAttribute('aria-current');
        });
      }));
      function advance(direction) {
        const current = images.findIndex((image) => !image.hidden);
        if (triggers.length > 1) triggers[(current + direction + triggers.length) % triggers.length].click();
      }
      stage.addEventListener('keydown', (event) => {
        if (event.target !== stage) return;
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
          event.preventDefault();
          advance(event.key === 'ArrowRight' ? 1 : -1);
        }
      });
      let start;
      stage.addEventListener('touchstart', (event) => {
        start = event.touches.length === 1 ? event.touches[0] : null;
      }, { passive: true });
      stage.addEventListener('touchend', (event) => {
        if (!start || !event.changedTouches.length) return;
        const end = event.changedTouches[0];
        const dx = end.clientX - start.clientX;
        if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(end.clientY - start.clientY) * 1.5) advance(dx < 0 ? 1 : -1);
        start = null;
      }, { passive: true });
      if (dialog && zoomButton && zoomImage) {
        zoomButton.addEventListener('click', () => {
          const current = images.find((image) => !image.hidden);
          if (!current) return;
          zoomImage.src = current.src;
          zoomImage.alt = current.alt;
          dialog.showModal();
        });
        closeButton?.addEventListener('click', () => dialog.close());
        dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
      }
    });
  }
  init();
  document.addEventListener('velmora:product-ready', init);
})();
