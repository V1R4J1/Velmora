import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createBundleService, bundleReferences, BundleServiceError } from '../static/bundle-service.js';

test('the future frontend saves references rather than copied prices, stock and imagery', async () => {
  const source = JSON.parse(readFileSync(new URL('./fixtures/bundle-proposal.json', import.meta.url)));
  const resolved = { ...source, total_price_gbp: 540, currency: 'GBP', items: source.items.map((item) => ({ ...item, colour_label: 'Resolved label', price_gbp: 1, availability: 'in_stock', image: 'not-a-reference' })) };
  const references = bundleReferences(resolved);
  assert.deepEqual(references, source);
  let sent;
  const service = createBundleService({ csrfToken: 'test-only', fetcher: async (url, options) => {
    sent = { url, options };
    return { ok: true, json: async () => ({ url: '/bundles/saved/test' }) };
  } });
  const result = await service.save(references);
  assert.equal(sent.options.headers['X-CSRF-Token'], 'test-only');
  assert.deepEqual(JSON.parse(sent.options.body), source);
  assert.equal(result.url, '/bundles/saved/test');
});

test('disabled or failed providers return typed errors and preserve cancellation', async () => {
  const controller = new AbortController();
  let signal;
  const service = createBundleService({ fetcher: async (url, options) => {
    signal = options.signal;
    return { ok: false, status: 503, json: async () => ({ error: 'Personal styling is not connected yet.', code: 'provider_not_configured' }) };
  } });
  await assert.rejects(service.generate({ prompt: 'A winter look' }, { signal: controller.signal }), (error) => error instanceof BundleServiceError && error.code === 'provider_not_configured' && error.status === 503);
  assert.equal(signal, controller.signal);
});
