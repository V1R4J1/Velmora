/* A signed-session preview switch; every price still comes from the server. */
(() => {
  const form = document.querySelector('[data-demo-campaign]');
  if (!form) return;
  const button = form.querySelector('[data-demo-campaign-switch]');
  const feedback = form.querySelector('[data-demo-campaign-feedback]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    feedback.textContent = '';
    try {
      const response = await fetch(form.action, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json',
          'X-CSRF-Token': form.elements.csrf_token.value },
        body: JSON.stringify({ enabled: button.getAttribute('aria-checked') !== 'true' }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'The demo could not update. Please try again.');
      button.setAttribute('aria-checked', String(result.enabled));
      form.querySelector('[data-demo-campaign-state]').textContent = result.enabled ? 'On' : 'Off';
      form.elements.enabled.value = result.enabled ? 'false' : 'true';
      // Studio/search update in place, preserving the customer's working look.
      const change = new CustomEvent('velmora:campaign-change', { detail: result, cancelable: true });
      if (document.dispatchEvent(change)) location.reload();
      else feedback.textContent = result.enabled ? 'Demo on' : 'Demo off';
    } catch (error) {
      feedback.textContent = error.message || 'The demo could not update. Please try again.';
    } finally {
      button.disabled = false;
    }
  });
})();
