import assert from 'node:assert/strict';
import test from 'node:test';
import { bundleFromSelection, itemReference, updateStartingItem, removeSelection } from '../static/builder-state.js';

const dress = () => ({ product_id: 'VLM-003', variant_id: 'VLM-003--champagne', colour_id: 'champagne', selected_size: 'UK 10', quantity: 1, styling_explanation: 'The foundation.', _anchor: true });
const scarf = () => ({ product_id: 'VLM-047', variant_id: 'VLM-047--pewter', colour_id: 'pewter', selected_size: 'one size', quantity: 2 });

test('manual and AI selections save reference-only data with current colours and retained budget and occasion', () => {
  const bundle = bundleFromSelection({ name: '  My evening  ', description: ' A note ', occasion: ' Winter ', budget: '600.00', origin: 'AI-generated', entries: [dress(), scarf()] });
  assert.equal(bundle.name, 'My evening');
  assert.equal(bundle.description, 'A note');
  assert.equal(bundle.occasion, 'Winter');
  assert.equal(bundle.budget_gbp, 600);
  assert.equal(bundle.origin, 'AI-generated');
  assert.deepEqual(bundle.colour_palette, ['champagne', 'pewter']);
  assert.deepEqual(bundle.items.map((item) => item.position), [0, 1]);
  assert.equal(bundle.items[0].styling_explanation, 'The foundation.');
  assert.equal('_anchor' in bundle.items[0], false);
});

test('an explicit starting-piece colour or size change updates its fixed selection', () => {
  const entry = dress();
  let anchor = itemReference(entry);
  entry.variant_id = 'VLM-003--emerald'; entry.colour_id = 'emerald'; entry.selected_size = 'UK 12';
  anchor = updateStartingItem(anchor, entry);
  assert.equal(anchor.variant_id, 'VLM-003--emerald');
  assert.equal(anchor.colour_id, 'emerald');
  assert.equal(anchor.selected_size, 'UK 12');
  assert.equal('_anchor' in anchor, false);
  assert.deepEqual(updateStartingItem(anchor, scarf()), anchor);
});

test('removing the starting piece releases it while refinement preserves only reference fields', () => {
  const entries = [dress(), scarf()];
  const anchor = itemReference(entries[0]);
  const current = entries.map(itemReference);
  assert.equal('styling_explanation' in current[0], false);
  assert.equal('_anchor' in current[0], false);
  assert.equal(removeSelection(entries, 0, anchor), null);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].colour_id, 'pewter');
});
