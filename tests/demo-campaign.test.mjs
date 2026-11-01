import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

async function fixture({ success = true, handled = true } = {}) {
  let submit;
  let reloaded = false;
  let change;
  const requests = [];
  const attributes = new Map([['aria-checked', 'false']]);
  const button = { disabled: false, getAttribute: name => attributes.get(name),
    setAttribute: (name, value) => attributes.set(name, value) };
  const state = { textContent: 'Off' }, feedback = { textContent: '' };
  const form = { action: '/demo/black-friday',
    elements: { csrf_token: { value: 'session-token' }, enabled: { value: 'true' } },
    querySelector: selector => ({ '[data-demo-campaign-switch]': button,
      '[data-demo-campaign-state]': state, '[data-demo-campaign-feedback]': feedback })[selector],
    addEventListener: (name, listener) => { if (name === 'submit') submit = listener; } };
  const document = { querySelector: () => form, dispatchEvent(event) { change = event; return !handled; } };
  class CustomEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
  runInNewContext(readFileSync(new URL('../static/demo-campaign.js', import.meta.url), 'utf8'), {
    document, CustomEvent, location: { reload: () => { reloaded = true; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: success, json: async () => success ? { enabled: true, active: true } : { error: 'Please reload your session.' } };
    },
  });
  await submit({ preventDefault() {} });
  return { requests, attributes, button, state, feedback, form, change, reloaded };
}

test('website switch updates the server session and lets Studio refresh without reloading the unsaved look', async () => {
  const result = await fixture();
  assert.equal(result.requests[0].url, '/demo/black-friday');
  assert.deepEqual(JSON.parse(result.requests[0].options.body), { enabled: true });
  assert.equal(result.requests[0].options.headers['X-CSRF-Token'], 'session-token');
  assert.equal(result.attributes.get('aria-checked'), 'true');
  assert.equal(result.state.textContent, 'On');
  assert.equal(result.form.elements.enabled.value, 'false');
  assert.equal(result.change.type, 'velmora:campaign-change');
  assert.equal(result.change.cancelable, true);
  assert.equal(result.reloaded, false);
  assert.equal(result.button.disabled, false);
});

test('ordinary pages reload their current URL after a successful demo switch', async () => {
  assert.equal((await fixture({ handled: false })).reloaded, true);
});

test('failed demo mutations preserve the visible setting and show a retryable error', async () => {
  const result = await fixture({ success: false });
  assert.equal(result.attributes.get('aria-checked'), 'false');
  assert.equal(result.feedback.textContent, 'Please reload your session.');
  assert.equal(result.reloaded, false);
  assert.equal(result.change, undefined);
  assert.equal(result.button.disabled, false);
});
