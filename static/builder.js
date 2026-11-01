import { bundleFromSelection, itemReference, removeSelection, updateStartingItem } from './builder-state.js';

/* One catalogue-backed set model drives the prompt, lookboard, editor and bag. */
const app = document.querySelector('[data-studio-app]');
if (app) {
  const $ = (selector) => app.querySelector(selector);
  const $$ = (selector) => [...app.querySelectorAll(selector)];
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  const params = new URLSearchParams(location.search);
  const state = { catalogue: [], entries: [], csrf: '', id: null, url: null, origin: 'customer-created', mode: 'describe', hasProposal: false, anchor: null, enabled: false, phase: 'idle', editorIndex: null, pricedBundle: null, priceKey: '', priceRevision: 0, campaignRevision: 0 };
  const feedback = $('[data-selection-feedback]');
  const global = $('[data-global-status]');
  const getProduct = (id) => state.catalogue.find((product) => product.id === id);
  const getVariant = (product, id) => product?.variants.find((variant) => variant.id === id);
  const placeholder = '<span class="look-tile-placeholder" aria-hidden="true">V</span>';
  const available = (variant) => variant && variant.availability !== 'unavailable';
  const imageSources = (url, sizes = '(max-width: 700px) 50vw, 35vw') => url?.startsWith('/static/productImages/') ? `srcset="${[320,640,960].map(width => `${escape(url.replace('/static/', '/static/responsive/'))}.${width}.webp ${width}w`).join(', ')}" sizes="${sizes}" width="800" height="1000"` : '';
  const image = (variant, name, className = '') => variant?.image
    ? `<img class="${className}" src="${escape(variant.image)}" ${imageSources(variant.image)} alt="${escape(name)} in ${escape(variant.colour_label)}" loading="lazy">` : placeholder;

  async function request(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    let data;
    try { data = await response.json(); } catch { throw new Error('The studio could not complete your request. Please try again.'); }
    if (!response.ok) throw new Error(data.error || 'The studio could not complete your request. Please try again.');
    return data;
  }
  function post(url, body) {
    return request(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify(body) });
  }
  const gbp = (value) => `£${Number(value).toFixed(2)}`;
  const entryPrice = (entry) => getVariant(getProduct(entry.product_id), entry.variant_id) || {};
  const priceMarkup = (price, quantity = 1) => price.price_gbp == null ? '—' : price.promotion_active
    ? `<span class="promotion-price"><del>${gbp(price.original_price_gbp * quantity)}</del> ${gbp(price.price_gbp * quantity)} <small>${escape(price.discount_percentage)}% less · Demo preview</small></span>` : gbp(price.price_gbp * quantity);
  let priceTimer;
  async function resolvePrices() {
    if (!state.entries.length) return;
    const key = JSON.stringify(references()), revision = ++state.priceRevision;
    try {
      const body = references(); if (!body.name) body.name = 'My look';
      const priced = await post('/api/bundles/resolve', body);
      if (revision !== state.priceRevision || key !== JSON.stringify(references())) return;
      const previous = state.pricedBundle?.total_price_gbp;
      priced.price_change_notice ||= state.pricedBundle?.price_change_notice;
      if (previous != null && previous !== priced.total_price_gbp) priced.price_change_notice = `This look now totals ${gbp(priced.total_price_gbp)}; the previous preview was ${gbp(previous)}.`;
      acceptPrices(priced); state.priceKey = key; renderSelection(false);
    } catch (error) {
      if (revision === state.priceRevision) { state.pricedBundle = null; $('[data-total]').textContent = 'Price unavailable'; feedback.textContent = error.message; }
    }
  }
  function acceptPrices(bundle) {
    state.pricedBundle = bundle;
    for (const item of bundle.items || []) {
      const variant = getVariant(getProduct(item.product_id), item.variant_id);
      if (variant) Object.assign(variant, { price_gbp: item.unit_price_gbp, original_price_gbp: item.original_price_gbp, promotional_price_gbp: item.promotional_price_gbp, discount_percentage: item.discount_percentage, promotion_active: item.promotion_active, preview_only: item.preview_only });
    }
  }
  function dirty() {
    state.priceKey = '';
    state.url = null;
    $('[data-explore-set]').hidden = true;
    feedback.textContent = '';
  }
  function syncStage() {
    const reviewing = state.entries.length > 0;
    app.dataset.stage = reviewing ? 'review' : 'create';
    app.dataset.mode = state.mode;
    $('[data-styling-brief]').hidden = state.mode !== 'describe' || reviewing;
    $('[data-builder]').hidden = state.mode !== 'manual' || reviewing;
    $('[data-review]').hidden = !reviewing;
    $('[data-refinement-form]').hidden = !reviewing || !state.enabled || state.mode !== 'describe';
    app.querySelectorAll('[data-mode]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.mode === state.mode)));
  }
  function setMode(mode) {
    state.mode = mode;
    syncStage();
  }
  function renderProducts(query = '') {
    const term = query.trim().toLocaleLowerCase();
    const matches = state.catalogue.filter((product) => [product.id, product.name, product.category, product.fabric, ...product.variants.map((variant) => variant.colour_label)].join(' ').toLocaleLowerCase().includes(term));
    $$('[data-result-count]').forEach((node) => { node.textContent = `${matches.length} ${matches.length === 1 ? 'piece' : 'pieces'}`; });
    $$('[data-no-results]').forEach((node) => { node.hidden = matches.length > 0; });
    const html = matches.map((product) => {
      const selected = product.variants.find((variant) => variant.id === product.default_variant_id && available(variant)) || product.variants.find(available) || product.variants[0];
      const options = product.variants.map((variant) => `<option value="${escape(variant.id)}"${variant === selected ? ' selected' : ''}${available(variant) ? '' : ' disabled'}>${escape(variant.colour_label)}${available(variant) ? '' : ' — unavailable'}</option>`).join('');
      return `<article class="studio-product" data-discovery-id="${escape(product.id)}"><div class="studio-product-image" data-discovery-image>${image(selected, product.name)}</div><h3>${escape(product.name)}</h3><p class="price">${priceMarkup(selected)}</p><label for="pick-${escape(product.id)}">Colour</label><select id="pick-${escape(product.id)}" data-discovery-variant aria-label="Colour for ${escape(product.name)}">${options}</select><p class="photo-note" data-discovery-note${selected?.image ? ' hidden' : ''}>Photography in this colour is not available yet.</p><button type="button" data-add-product="${escape(product.id)}"${product.variants.some(available) ? '' : ' disabled'}>${product.variants.some(available) ? 'Add to my set <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg>' : 'Currently unavailable'}</button></article>`;
    }).join('');
    $$('[data-products]').forEach((node) => { node.innerHTML = html; });
  }
  function renderSelection(resolve = true) {
    syncStage();
    const count = state.entries.reduce((sum, entry) => sum + entry.quantity, 0);
    const board = $('[data-lookboard]');
    const visible = state.entries.slice(0, 4);
    if (visible.length > 1) {
      const primary = visible.findIndex((entry) => {
        const product = getProduct(entry.product_id), variant = getVariant(product, entry.variant_id);
        return variant?.image && ['dress', 'jumpsuit'].includes(product?.category);
      });
      if (primary > 0) visible.unshift(visible.splice(primary, 1)[0]);
    }
    board.dataset.count = String(visible.length);
    board.innerHTML = visible.map((entry, visualIndex) => {
      const product = getProduct(entry.product_id), variant = getVariant(product, entry.variant_id);
      const color = variant?.colour_label || entry.colour_id;
      return `<button type="button" class="look-tile${visualIndex === 0 ? ' look-tile--primary' : ''}" data-edit-piece="${state.entries.indexOf(entry)}" aria-label="Edit ${escape(product?.name || 'unavailable piece')} in ${escape(color)}"><span class="tile-art">${image(variant, product?.name || 'Unavailable piece')}</span><span class="look-tile-caption"><strong>${escape(product?.name || 'Unavailable piece')}</strong><span>${escape(color)} · ${priceMarkup(entryPrice(entry))}</span></span><span class="look-tile-edit" aria-hidden="true">Edit piece</span></button>`;
    }).join('');
    $('[data-view-all]').hidden = state.entries.length <= 4;
    $('[data-view-all]').textContent = `View all ${state.entries.length} pieces`;
    $('[data-piece-count]').textContent = `${count} ${count === 1 ? 'piece' : 'pieces'}`;
    const current = state.priceKey === JSON.stringify(references()) ? state.pricedBundle : null;
    $('[data-total]').textContent = !state.entries.length ? '£0.00' : current ? gbp(current.total_price_gbp) : 'Updating…';
    const priceSummary = $('[data-price-summary]');
    priceSummary.hidden = !current?.total_savings_gbp;
    priceSummary.textContent = current?.total_savings_gbp ? `Original total ${gbp(current.original_total_price_gbp)} · Demo preview savings ${gbp(current.total_savings_gbp)}` : '';
    $('[data-pricing-notice]').textContent = current ? [current.price_change_notice, current.pricing_notice].filter(Boolean).join(' ') : '';
    if (resolve && state.entries.length && !current) { clearTimeout(priceTimer); priceTimer = setTimeout(resolvePrices, 180); }
    $('[data-selection-empty]').hidden = state.entries.length > 0;
    const summary = $('[data-selection-items]');
    summary.innerHTML = state.entries.slice(0, 4).map((entry, index) => {
      const product = getProduct(entry.product_id), variant = getVariant(product, entry.variant_id);
      const warning = !product || !available(variant) || (!product.one_size && !entry.selected_size);
      return `<button type="button" class="summary-item" data-edit-piece="${index}" aria-label="Edit ${escape(product?.name || 'unavailable piece')}"><span class="summary-thumb">${variant?.image ? `<img src="${escape(variant.image)}" ${imageSources(variant.image)} alt="" loading="lazy">` : '<span aria-hidden="true">V</span>'}</span><span class="summary-item-copy"><strong>${escape(product?.name || 'Unavailable piece')}${warning ? ' · check selection' : ''}</strong><span>${escape(variant?.colour_label || entry.colour_id)}${entry.quantity > 1 ? ` · Qty ${entry.quantity}` : ''}</span></span><span class="summary-item-price">${priceMarkup(entryPrice(entry), entry.quantity)}</span></button>`;
    }).join('');
    if (state.entries.length > 4) summary.insertAdjacentHTML('beforeend', `<button type="button" class="summary-more" data-open-all>+ ${state.entries.length - 4} more pieces</button>`);
    const needsSize = state.entries.filter((entry) => { const product = getProduct(entry.product_id); return product && !product.one_size && !entry.selected_size; });
    const unavailable = state.entries.filter((entry) => !available(getVariant(getProduct(entry.product_id), entry.variant_id)));
    const guidance = $('.purchase-guidance');
    guidance.textContent = unavailable.length ? 'Choose an available colour for each piece before adding this look to your bag.' : needsSize.length ? `Choose a size for ${needsSize.map((entry) => getProduct(entry.product_id)?.name).filter(Boolean).join(', ')} before adding this look to your bag.` : 'Current catalogue prices. Sizes and availability are checked when you add this look to your bag.';
    $('[data-description-preview]').textContent = $('[data-set-description]').value.trim();
    if (state.editorIndex !== null && $('[data-item-dialog]').open) renderEditor(state.editorIndex);
  }
  function showAnchor() {
    if (!state.anchor) { $('[data-anchor-summary]').replaceChildren(); return; }
    const product = getProduct(state.anchor.product_id), variant = getVariant(product, state.anchor.variant_id);
    if (!product || !variant) return;
    $('[data-anchor-summary]').innerHTML = `<div class="anchor-card">${image(variant, product.name)}<div><strong>Starting with ${escape(product.name)}</strong><span>${escape(variant.colour_label)}${state.anchor.selected_size ? ` · ${escape(state.anchor.selected_size)}` : ''}</span></div></div>`;
  }
  function addEntry(product, variant, size = null) {
    if (!product || !available(variant)) return;
    if (state.entries.length >= 50) { feedback.textContent = 'A look can contain up to 50 selections.'; return; }
    const selectedSize = size || (product.one_size ? 'one size' : null);
    const existing = state.entries.find((item) => item.product_id === product.id && item.variant_id === variant.id && item.selected_size === selectedSize);
    if (existing) {
      if (existing.quantity >= 20) { feedback.textContent = 'A maximum of 20 of each selection can be added.'; return; }
      existing.quantity++;
    } else state.entries.push({ product_id: product.id, variant_id: variant.id, colour_id: variant.colour_id, selected_size: selectedSize, quantity: 1, styling_explanation: null });
    dirty(); renderSelection();
    feedback.textContent = `${product.name} in ${variant.colour_label} added to your look.`;
    if ($('[data-catalogue-dialog]').open) $('[data-catalogue-dialog]').close();
  }
  function references() {
    return bundleFromSelection({ name: $('[data-set-name]').value, description: $('[data-set-description]').value,
      occasion: $('[data-set-occasion]').value, budget: $('[data-set-budget]').value,
      origin: state.origin, entries: state.entries });
  }
  function checkSelection(purchase = false) {
    if (!$('[data-set-name]').value.trim()) return 'Please name your look.';
    if (!state.entries.length) return 'Choose at least one piece for your look.';
    const rawBudget = $('[data-set-budget]').value.trim();
    if (rawBudget && (!Number.isFinite(Number(rawBudget)) || Number(rawBudget) < 0 || Number(rawBudget) > 1000000 || !/^\d+(?:\.\d{1,2})?$/.test(rawBudget))) return 'Enter a valid budget in pounds and pence.';
    if (!state.pricedBundle || state.priceKey !== JSON.stringify(references())) return 'Current prices are updating. Please try again shortly.';
    if (rawBudget && !state.pricedBundle.within_budget) return 'This look is above the budget. Adjust the pieces or budget before continuing.';
    for (const entry of state.entries) {
      const product = getProduct(entry.product_id), variant = getVariant(product, entry.variant_id);
      if (!product || !variant) return 'A piece is no longer in the catalogue. Remove it or choose another piece.';
      if (purchase && !available(variant)) return `${product.name} in ${variant.colour_label} is unavailable. Choose another colour or remove this piece.`;
      if (purchase && !product.one_size && !entry.selected_size) return `Choose a size for ${product.name} before adding this look to your bag.`;
    }
    return null;
  }
  async function refreshSaved() {
    const response = await request('/api/bundles/mine');
    const saved = response.bundles || [];
    $('[data-saved-section]').hidden = !saved.length;
    $('[data-saved-sets]').innerHTML = saved.map((bundle) => `<a href="/sets/create?edit=${encodeURIComponent(bundle.id)}">${escape(bundle.name)} <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></a>`).join('');
  }
  function applyBundle(bundle) {
    state.entries = (bundle.items || []).map((entry) => ({ product_id: entry.product_id, variant_id: entry.variant_id, colour_id: entry.colour_id, selected_size: entry.selected_size, quantity: entry.quantity, styling_explanation: entry.styling_explanation }));
    if (state.anchor) {
      const anchored = state.entries.find((entry) => entry.product_id === state.anchor.product_id && entry.variant_id === state.anchor.variant_id);
      if (anchored) anchored._anchor = true;
    }
    state.origin = bundle.origin === 'AI-generated' ? 'AI-generated' : 'customer-created';
    $('[data-set-name]').value = bundle.name || 'My look';
    $('[data-set-description]').value = bundle.description || '';
    $('[data-set-occasion]').value = bundle.occasion || '';
    $('[data-set-budget]').value = bundle.budget_gbp ?? '';
    acceptPrices(bundle); state.priceKey = JSON.stringify(references());
    renderSelection(false);
  }
  function renderReplaceOptions(index, query = '') {
    const entry = state.entries[index];
    if (!entry) return;
    const term = query.trim().toLocaleLowerCase();
    const matches = state.catalogue.filter((product) => product.id !== entry.product_id && [product.id, product.name, product.category, product.fabric, ...product.variants.map((variant) => variant.colour_label)].join(' ').toLocaleLowerCase().includes(term)).slice(0, 7);
    const target = $('[data-replace-results]');
    if (!target) return;
    target.innerHTML = matches.map((product) => {
      const variant = product.variants.find((option) => option.id === product.default_variant_id && available(option)) || product.variants.find(available);
      return variant ? `<button type="button" class="replace-option" data-replace-product="${escape(product.id)}" data-index="${index}">${variant.image ? `<img src="${escape(variant.image)}" ${imageSources(variant.image)} alt="" loading="lazy">` : '<span class="summary-thumb" aria-hidden="true">V</span>'}<span>${escape(product.name)}<br><small>${escape(variant.colour_label)}</small></span><small>${priceMarkup(variant)}</small></button>` : '';
    }).join('') || '<p class="photo-note">No available pieces match your search.</p>';
  }
  function renderEditor(index) {
    const entry = state.entries[index];
    const product = entry && getProduct(entry.product_id);
    const variant = entry && getVariant(product, entry.variant_id);
    if (!entry || !product) return;
    state.editorIndex = index;
    const colours = product.variants.map((option) => `<button type="button" class="editor-swatch" data-editor-colour="${escape(option.id)}" data-index="${index}" aria-pressed="${option.id === variant?.id}"${!available(option) && option.id !== variant?.id ? ' disabled' : ''}><span class="editor-swatch-mark colour-${escape(option.colour_id)}"></span><span>${escape(option.colour_label)}${available(option) ? '' : ' · unavailable'}</span></button>`).join('');
    const sizes = product.one_size ? '<span>One size</span>' : `<select data-editor-field="size" data-index="${index}" aria-label="Size"><option value="">Choose size</option>${product.sizes.map((size) => `<option value="${escape(size)}"${size === entry.selected_size ? ' selected' : ''}>${escape(size)}</option>`).join('')}</select>`;
    $('[data-item-editor]').innerHTML = `<div class="item-editor"><div class="item-editor-preview"><span class="editor-image">${image(variant, product.name)}</span><div><h3>${escape(product.name)}</h3><p>${priceMarkup(variant || {})} · ${escape(variant?.colour_label || entry.colour_id)}</p></div></div><label>Colour<span class="editor-swatches">${colours}</span></label><div class="item-editor-row"><label>Size${sizes}</label><label>Quantity<input type="number" min="1" max="20" value="${entry.quantity}" data-editor-field="quantity" data-index="${index}"></label></div><details class="item-editor-details"><summary>Piece details</summary><p>${escape(product.description)} ${escape(product.fabric)}${product.fit ? ` · ${escape(product.fit)} fit` : ''}.</p></details>${entry.styling_explanation ? `<details class="item-editor-details"><summary>Stylist’s notes</summary><p>${escape(entry.styling_explanation)}</p></details>` : ''}<label>Replace with<input type="search" placeholder="Search the collection" data-replace-search="${index}"></label><div class="replace-results" data-replace-results></div><div class="editor-actions"><div><button type="button" data-move="up" data-index="${index}"${index === 0 ? ' disabled' : ''}>Move earlier</button> <button type="button" data-move="down" data-index="${index}"${index === state.entries.length - 1 ? ' disabled' : ''}>Move later</button></div><button type="button" data-remove-current="${index}">Remove piece</button></div></div>`;
    renderReplaceOptions(index);
  }
  function openEditor(index) {
    if (!state.entries[index]) return;
    renderEditor(index);
    const dialog = $('[data-item-dialog]');
    if (!dialog.open) dialog.showModal();
  }
  function renderAllPieces() {
    $('[data-all-pieces]').innerHTML = state.entries.map((entry, index) => {
      const product = getProduct(entry.product_id), variant = getVariant(product, entry.variant_id);
      return `<button type="button" class="all-piece" data-edit-piece="${index}"><span class="summary-thumb">${variant?.image ? `<img src="${escape(variant.image)}" ${imageSources(variant.image)} alt="" loading="lazy">` : 'V'}</span><strong>${escape(product?.name || 'Unavailable piece')}</strong><span>${escape(variant?.colour_label || entry.colour_id)} · ${priceMarkup(entryPrice(entry))}</span></button>`;
    }).join('');
  }

  app.querySelectorAll('[data-mode]').forEach((button) => button.addEventListener('click', () => setMode(button.dataset.mode)));
  app.querySelectorAll('[data-studio-search]').forEach((input) => input.addEventListener('input', (event) => renderProducts(event.target.value)));
  app.querySelectorAll('[data-styling-form], [data-refinement-form]').forEach((form) => form.addEventListener('input', (event) => {
    if (event.target.matches('[name="prompt"]')) $('[data-refine-submit]').disabled = !state.enabled || !event.target.value.trim();
  }));
  app.addEventListener('input', (event) => {
    const target = event.target;
    if (target.matches('[data-set-name]')) { dirty(); renderSelection(); }
    if (target.matches('[data-set-description]')) { dirty(); renderSelection(); }
    if (target.matches('[data-set-occasion], [data-set-budget]')) { dirty(); renderSelection(); }
    if (target.matches('[data-replace-search]')) renderReplaceOptions(Number(target.dataset.replaceSearch), target.value);
    if (target.matches('[data-styling-form] [name="prompt"]')) $('[data-ai-generate]').disabled = !state.enabled || !target.value.trim();
  });
  app.addEventListener('change', (event) => {
    const target = event.target;
    if (target.matches('[data-discovery-variant]')) {
      const card = target.closest('[data-discovery-id]'), product = getProduct(card.dataset.discoveryId), variant = getVariant(product, target.value);
      card.querySelector('[data-discovery-image]').innerHTML = image(variant, product.name);
      card.querySelector('.price').innerHTML = priceMarkup(variant || {});
      card.querySelector('[data-discovery-note]').hidden = Boolean(variant?.image);
      return;
    }
    if (target.matches('[data-editor-field]')) {
      const index = Number(target.dataset.index), entry = state.entries[index], product = getProduct(entry?.product_id);
      if (!entry || !product) return;
      if (target.dataset.editorField === 'size') entry.selected_size = target.value || null;
      if (target.dataset.editorField === 'quantity') {
        const quantity = Number(target.value);
        if (!Number.isInteger(quantity) || quantity < 1 || quantity > 20) { target.value = entry.quantity; return; }
        entry.quantity = quantity;
      }
      if (entry._anchor && state.anchor) state.anchor = updateStartingItem(state.anchor, entry);
      dirty(); renderSelection(); renderEditor(index);
    }
  });
  app.addEventListener('click', (event) => {
    const target = event.target;
    const suggestion = target.closest('[data-prompt]');
    if (suggestion) { $('#styling-prompt').value = suggestion.dataset.prompt; $('[data-ai-generate]').disabled = !state.enabled; $('#styling-prompt').focus(); }
    const edit = target.closest('[data-edit-piece]');
    if (edit) {
      const index = Number(edit.dataset.editPiece);
      if ($('[data-all-dialog]').open) $('[data-all-dialog]').close();
      openEditor(index);
    }
    const rename = target.closest('[data-rename]');
    if (rename) { const input = $('[data-set-name]'); input.readOnly = false; input.focus(); input.select(); }
    if (target.closest('[data-close-item]')) { $('[data-item-dialog]').close(); state.editorIndex = null; }
    if (target.closest('[data-close-catalogue]')) $('[data-catalogue-dialog]').close();
    if (target.closest('[data-close-all]')) $('[data-all-dialog]').close();
    if (target.closest('[data-open-catalogue]')) { $('[data-catalogue-dialog]').showModal(); $('#studio-dialog-search').focus(); }
    if (target.closest('[data-view-all]') || target.closest('[data-open-all]')) { renderAllPieces(); $('[data-all-dialog]').showModal(); }
    const swatch = target.closest('[data-editor-colour]');
    if (swatch) {
      const index = Number(swatch.dataset.index), entry = state.entries[index], product = getProduct(entry?.product_id), variant = getVariant(product, swatch.dataset.editorColour);
      if (entry && available(variant)) { entry.variant_id = variant.id; entry.colour_id = variant.colour_id; if (entry._anchor && state.anchor) state.anchor = updateStartingItem(state.anchor, entry); dirty(); renderSelection(); renderEditor(index); }
    }
    const replace = target.closest('[data-replace-product]');
    if (replace) {
      const index = Number(replace.dataset.index), product = getProduct(replace.dataset.replaceProduct), variant = product?.variants.find((option) => option.id === product.default_variant_id && available(option)) || product?.variants.find(available);
      if (product && variant) {
        const entry = state.entries[index];
        Object.assign(entry, { product_id: product.id, variant_id: variant.id, colour_id: variant.colour_id, selected_size: product.one_size ? 'one size' : null, quantity: 1, styling_explanation: null });
        if (entry._anchor) { state.anchor = null; delete entry._anchor; }
        dirty(); renderSelection(); renderEditor(index);
      }
    }
    const add = target.closest('[data-add-product]');
    if (add) {
      const product = getProduct(add.dataset.addProduct), variant = getVariant(product, add.closest('[data-discovery-id]').querySelector('[data-discovery-variant]').value);
      addEntry(product, variant);
    }
    const remove = target.closest('[data-remove-current]');
    if (remove) {
      state.anchor = removeSelection(state.entries, Number(remove.dataset.removeCurrent), state.anchor);
      dirty(); renderSelection();
      $('[data-item-dialog]').close(); state.editorIndex = null;
    }
    const move = target.closest('[data-move]');
    if (move && !move.disabled) {
      const index = Number(move.dataset.index), next = index + (move.dataset.move === 'up' ? -1 : 1);
      if (next < 0 || next >= state.entries.length) return;
      [state.entries[index], state.entries[next]] = [state.entries[next], state.entries[index]];
      dirty(); renderSelection(); renderEditor(next);
    }
  });

  $('[data-item-dialog]').addEventListener('close', () => { state.editorIndex = null; });
  $('[data-catalogue-dialog]').addEventListener('click', (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });
  $('[data-all-dialog]').addEventListener('click', (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });
  $('[data-rename]').addEventListener('blur', () => {});
  $('[data-set-name]').addEventListener('blur', (event) => { event.target.readOnly = true; });
  app.addEventListener('keydown', (event) => { if (event.key === 'Escape') { state.editorIndex = null; } });

  $('[data-save-set]').addEventListener('click', async (event) => {
    const error = checkSelection(); if (error) { feedback.textContent = error; return; }
    const button = event.currentTarget; button.disabled = true; feedback.textContent = 'Saving your look…';
    try {
      const response = await post(state.id ? `/api/bundles/${encodeURIComponent(state.id)}/edit` : '/api/bundles', references());
      acceptPrices(response.bundle); state.priceKey = JSON.stringify(references()); renderSelection(false);
      state.id = response.bundle.id; state.url = response.url;
      const url = new URL(location.href); url.searchParams.set('edit', state.id); url.searchParams.delete('product'); url.searchParams.delete('variant'); url.searchParams.delete('size'); history.replaceState(null, '', url);
      const link = $('[data-explore-set]'); link.href = response.url; link.hidden = false;
      feedback.textContent = 'Your look is saved privately in this session.';
      await refreshSaved();
    } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
  });
  $('[data-add-set]').addEventListener('click', async (event) => {
    const error = checkSelection(true); if (error) { feedback.textContent = error; return; }
    const button = event.currentTarget; button.disabled = true; feedback.textContent = 'Adding your look…';
    try {
      const response = await post('/api/bag/bundle', references());
      document.querySelectorAll('[data-bag-count]').forEach((node) => { node.textContent = response.count; });
      feedback.replaceChildren(document.createTextNode(`Your look is in your bag at ${gbp(response.total_price_gbp)}. ${response.pricing_notice || ''} `));
      const link = document.createElement('a'); link.href = '/bag'; link.textContent = 'View bag'; feedback.append(link);
    } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
  });
  app.querySelectorAll('[data-styling-form], [data-refinement-form]').forEach((form) => form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.enabled || state.phase === 'loading') return;
    const values = new FormData(form), prompt = String(values.get('prompt') || '').trim();
    if (!prompt) return;
    const body = { prompt };
    const preferenceForm = $('[data-styling-form]');
    for (const key of ['occasion', 'size', 'aesthetic']) { const value = String(new FormData(preferenceForm).get(key) || '').trim(); if (value) body[key] = value; }
    for (const key of ['preferred_colours', 'categories']) { const value = String(new FormData(preferenceForm).get(key) || '').trim(); if (value) body[key] = value.split(',').map((part) => part.trim()).filter(Boolean); }
    const budget = String(new FormData(preferenceForm).get('budget_gbp') || '').trim();
    if (budget) body.budget_gbp = Number(budget);
    if (state.anchor) body.starting_item = { ...state.anchor };
    if (state.hasProposal) body.current_items = state.entries.map(itemReference);
    const campaignRevision = state.campaignRevision;
    state.phase = 'loading'; app.dataset.phase = state.phase;
    const firstButton = $('[data-ai-generate]'), refineButton = $('[data-refine-submit]');
    firstButton.disabled = true; refineButton.disabled = true;
    const status = state.entries.length ? $('[data-review-status]') : $('[data-ai-status]');
    status.textContent = state.hasProposal ? 'Reworking your look…' : 'Creating your look…';
    try {
      const data = await post('/api/bundles/generate', body);
      if (campaignRevision !== state.campaignRevision) {
        state.phase = 'idle'; status.textContent = 'Demo mode changed. Create your look again using current prices.'; return;
      }
      if (!data.proposal) { state.phase = 'empty'; status.textContent = (data.constraints || []).join(' ') || 'No available pieces matched your request.'; return; }
      applyBundle(data.proposal); state.id = null; state.url = null; state.hasProposal = true; state.phase = 'success';
      setMode('describe');
      const note = (data.constraints || []).join(' ');
      $('[data-review-status]').textContent = note;
      status.textContent = '';
      renderSelection();
    } catch (error) {
      state.phase = 'error';
      status.textContent = state.entries.length ? 'I couldn’t update this look. Your current pieces are unchanged; please try again.' : 'I couldn’t create that look. Please try another request.';
    } finally {
      app.dataset.phase = state.phase;
      firstButton.disabled = !state.enabled || !$('#styling-prompt').value.trim();
      refineButton.disabled = !state.enabled || !$('#refinement-prompt').value.trim();
    }
  }));

  async function init() {
    try {
      const session = await request('/api/session');
      state.csrf = session.csrf_token; state.enabled = Boolean(session.styling_enabled);
      const catalogue = await request('/api/styling/catalogue'); state.catalogue = catalogue.products;
      renderProducts(); renderSelection();
      const button = $('[data-ai-generate]'); button.disabled = !state.enabled;
      $('[data-ai-privacy]').hidden = !state.enabled;
      if (!state.enabled) { button.textContent = 'AI styling — coming soon'; $('[data-ai-status]').textContent = ''; }
      if (params.get('edit')) {
        const bundle = await request(`/api/bundles/${encodeURIComponent(params.get('edit'))}`);
        if (bundle.status !== 'draft') throw new Error('This look is not an editable private draft.');
        applyBundle(bundle); state.id = bundle.id; state.hasProposal = bundle.origin === 'AI-generated'; state.url = `/bundles/saved/${encodeURIComponent(bundle.id)}`;
        const link = $('[data-explore-set]'); link.href = state.url; link.hidden = false;
        setMode('manual');
      } else if (params.get('product')) {
        const product = getProduct(params.get('product'));
        const variant = getVariant(product, params.get('variant'));
        const size = params.get('size') || null;
        if (!product || !variant || !available(variant) || (size && !product.sizes.includes(size))) throw new Error('The starting piece or colour is unavailable. Please choose a piece from the collection.');
        state.anchor = { product_id: product.id, variant_id: variant.id, colour_id: variant.colour_id, selected_size: size || (product.one_size ? 'one size' : null), quantity: 1 };
        addEntry(product, variant, size); state.entries[0]._anchor = true; showAnchor(); setMode(params.get('mode') === 'manual' ? 'manual' : 'describe');
      } else if (params.get('mode') === 'manual' || params.get('mode') === 'describe') setMode(params.get('mode'));
      await refreshSaved();
    } catch (error) { global.textContent = error.message; }
  }
  let refreshingPrices = false;
  let priceRefreshPending = false;
  async function refreshCurrentPrices() {
    if (!state.csrf) return;
    if (refreshingPrices) { priceRefreshPending = true; return; }
    refreshingPrices = true;
    try {
      const data = await request('/api/styling/catalogue');
      state.catalogue = data.products;
      $$('[data-discovery-id]').forEach((card) => {
        const product = getProduct(card.dataset.discoveryId);
        const variant = getVariant(product, card.querySelector('[data-discovery-variant]').value);
        card.querySelector('.price').innerHTML = priceMarkup(variant || {});
      });
      await resolvePrices();
    } catch { /* Mutations still resolve current prices authoritatively. */ }
    finally {
      refreshingPrices = false;
      if (priceRefreshPending) { priceRefreshPending = false; refreshCurrentPrices(); }
    }
  }
  document.addEventListener('velmora:campaign-change', (event) => {
    event.preventDefault(); state.campaignRevision++; state.priceRevision++; state.priceKey = '';
    renderSelection(false); refreshCurrentPrices();
  });
  window.addEventListener('focus', refreshCurrentPrices);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshCurrentPrices(); });
  setInterval(() => { if (!document.hidden) refreshCurrentPrices(); }, 30000);
  init();
}
