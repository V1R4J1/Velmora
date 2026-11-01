/* Shared, reference-only state transformations used by manual and AI flows. */
export function itemReference(entry) {
  return { product_id: entry.product_id, variant_id: entry.variant_id, colour_id: entry.colour_id,
    selected_size: entry.selected_size || null, quantity: entry.quantity };
}

export function updateStartingItem(anchor, entry) {
  return anchor && entry?._anchor ? itemReference(entry) : anchor;
}

export function removeSelection(entries, index, anchor) {
  const [removed] = entries.splice(index, 1);
  return removed?._anchor ? null : anchor;
}

export function bundleFromSelection({ name, description, occasion, budget, origin, entries }) {
  return { schema_version: 1, name: name.trim(), description: description.trim() || null,
    occasion: occasion.trim() || null, origin, status: 'draft',
    colour_palette: [...new Set(entries.map((entry) => entry.colour_id))],
    budget_gbp: budget.trim() ? Number(budget) : null,
    items: entries.map((entry, position) => ({ ...itemReference(entry), position,
      styling_explanation: entry.styling_explanation || null })) };
}
