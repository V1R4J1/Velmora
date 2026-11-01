import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

class Element extends EventTarget {
  constructor(dataset = {}) { super(); this.dataset = dataset; this.attributes = new Map(); this.children = new Map(); this.hidden = false; this.inert = false; this.textContent = ''; }
  querySelector(selector) { return this.children.get(selector)?.[0] || null; }
  querySelectorAll(selector) { return this.children.get(selector) || []; }
  setAttribute(key, value) { this.attributes.set(key, value); }
  removeAttribute(key) { this.attributes.delete(key); }
  getAttribute(key) { return this.attributes.get(key); }
  replaceChildren(...items) { this.content = items; }
  append(item) { (this.content ||= []).push(item); }
  focus(options) { this.focused = options; }
}
const tick = () => new Promise((resolve) => setImmediate(resolve));

function fixture() {
  const document = new Element();
  const window = new Element();
  const view = new Element();
  const status = new Element();
  const error = new Element();
  const count = new Element();
  const feedback = new Element();
  const metadata = new Element();
  const state = new Element({ bundleSizes: '-/one size/one size', bundleColours: 'champagne/champagne/emerald', itemIndex: '0' });
  const title = new Element(); title.textContent = 'Isola dress';
  const colour = new Element(); colour.textContent = 'Champagne';
  const description = new Element(); description.textContent = 'A column dress in jersey.';
  view.children = new Map([['#product-title', [title]], ['[data-selected-colour]', [colour]], ['.product-description', [description]], ['[data-product-state]', [state]], ['[data-bag-feedback]', [feedback]]]);
  const rendered = [];
  Object.defineProperty(view, 'innerHTML', { set(value) { rendered.push(value); title.textContent = value; } });
  document.children = new Map([['[data-product-view]', [view]], ['[data-product-status]', [status]], ['[data-view-error]', [error]], ['[data-bag-count]', [count]], ['meta[name="description"]', [metadata]]]);
  document.createElement = () => new Element();
  document.createTextNode = (value) => value;
  const location = { href: 'http://velmora.test/bundles/winter-soiree' };
  const changes = [];
  const history = {
    replaceState(state, unused, url) { location.href = new URL(url, location.href).href; changes.push(['replace', location.href]); },
    pushState(state, unused, url) { location.href = new URL(url, location.href).href; changes.push(['push', location.href]); },
  };
  const requests = [];
  function fetch(url, options) {
    return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  }
  runInNewContext(readFileSync(new URL('../static/product-page.js', import.meta.url), 'utf8'), {
    document, window, history, location, fetch, URL, Event, AbortController,
    FormData: class { constructor(form) { this.form = form; } },
  });
  function click(url) {
    const link = new Element(); link.href = new URL(url, location.href).href;
    const target = { closest: () => link };
    const event = new Event('click', { cancelable: true });
    Object.defineProperties(event, { target: { value: target }, button: { value: 0 } });
    view.dispatchEvent(event);
    return link;
  }
  function respond(index, data, ok = true) { requests[index].resolve({ ok, json: async () => data }); }
  return { document, window, view, status, error, state, title, count, feedback, requests, rendered, location, changes, click, respond };
}

test('product navigation fetches one complete view and synchronises history, title and status', async () => {
  const f = fixture();
  f.click('?item=2');
  assert.equal(f.view.inert, true);
  assert.equal(f.requests[0].options.headers['X-Velmora-View'], 'product');
  f.respond(0, { html: 'Bianca silk scarf', title: 'Bianca silk scarf | Velmora' });
  await tick();
  assert.equal(f.title.textContent, 'Bianca silk scarf');
  assert.equal(f.document.title, 'Bianca silk scarf | Velmora');
  assert.match(f.location.href, /item=2/);
  assert.equal(f.view.inert, false);
  assert.equal(f.status.textContent, 'Bianca silk scarf, Champagne');
  assert.equal(f.title.focused.preventScroll, true);
});

test('a late stale response cannot overwrite the newest selected product', async () => {
  const f = fixture();
  f.click('?item=2');
  f.click('?item=3');
  assert.equal(f.requests[0].options.signal.aborted, true);
  f.respond(1, { html: 'Celeste clutch', title: 'Celeste clutch | Velmora' });
  await tick();
  f.respond(0, { html: 'Bianca silk scarf', title: 'Bianca silk scarf | Velmora' });
  await tick();
  assert.deepEqual(f.rendered, ['Celeste clutch']);
  assert.match(f.location.href, /item=3/);
});

test('browser back reloads its selection without adding a history entry', async () => {
  const f = fixture();
  f.location.href = 'http://velmora.test/bundles/winter-soiree?item=2&colours=champagne/pewter/emerald';
  f.window.dispatchEvent(new Event('popstate'));
  f.respond(0, { html: 'Bianca silk scarf', title: 'Bianca silk scarf | Velmora' });
  await tick();
  assert.equal(f.rendered[0], 'Bianca silk scarf');
  assert.equal(f.changes.filter(([method]) => method === 'push').length, 0);
});

test('a failed history request hides the mismatched product and offers its direct link', async () => {
  const f = fixture();
  f.location.href += '?item=3';
  f.window.dispatchEvent(new Event('popstate'));
  f.requests[0].reject(new Error('network failed'));
  await tick();
  assert.equal(f.view.hidden, true);
  assert.equal(f.error.hidden, false);
  assert.match(f.error.content[1].href, /item=3/);
});

test('size changes preserve each bundle colour and update all piece and swatch links', () => {
  const f = fixture();
  const links = ['?item=2&colours=champagne/champagne/emerald', '?item=1&colours=emerald/champagne/emerald'].map((path) => ({ href: new URL(path, f.location.href).href }));
  f.view.children.set('a[data-product-link]', links);
  const event = new Event('change');
  Object.defineProperty(event, 'target', { value: { value: 'UK 10', matches: () => true } });
  f.view.dispatchEvent(event);
  assert.equal(new URL(f.location.href).searchParams.get('sizes'), 'UK 10/one size/one size');
  for (const link of links) assert.equal(new URL(link.href).searchParams.get('sizes'), 'UK 10/one size/one size');
  assert.equal(new URL(links[1].href).searchParams.get('colours'), 'emerald/champagne/emerald');
});

test('bag submission sends the current form and updates count only after server acceptance', async () => {
  const f = fixture();
  const form = new Element();
  form.action = 'http://velmora.test/bag/items';
  const button = new Element();
  form.children = new Map([['button[type="submit"]', [button]], ['[data-bag-feedback]', [f.feedback]]]);
  const event = new Event('submit', { cancelable: true });
  Object.defineProperty(event, 'target', { value: { closest: () => form } });
  f.view.dispatchEvent(event);
  assert.equal(button.disabled, true);
  assert.equal(f.requests[0].options.body.form, form);
  f.respond(0, { count: 2 });
  await tick();
  assert.equal(f.count.textContent, 2);
  assert.equal(button.disabled, false);
  assert.equal(f.feedback.content[1].href, '/bag');
});
