/* Future Create Your Look boundary. No UI is mounted or advertised as live. */
export class BundleServiceError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}

export function createBundleService({ csrfToken, fetcher = globalThis.fetch } = {}) {
  async function post(path, body, signal) {
    const response = await fetcher(path, {
      method: 'POST', credentials: 'same-origin', signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new BundleServiceError(data.error || 'The set could not be prepared.', data.code, response.status);
    return data;
  }
  return {
    generate: (request, { signal } = {}) => post('/api/bundles/generate', request, signal),
    save: (references, { signal } = {}) => post('/api/bundles', references, signal),
  };
}

/** Strip derived catalogue values before confirming/saving a proposal. */
export function bundleReferences(proposal) {
  const fields = ['id', 'name', 'description', 'origin', 'occasion', 'colour_palette', 'budget_gbp', 'created_at', 'modified_at', 'status', 'schema_version'];
  const itemFields = ['product_id', 'variant_id', 'colour_id', 'selected_size', 'quantity', 'position', 'styling_explanation'];
  const pick = (record, keys) => Object.fromEntries(keys.filter((key) => Object.hasOwn(record, key)).map((key) => [key, record[key]]));
  return { ...pick(proposal, fields), items: proposal.items.map((item) => pick(item, itemFields)) };
}
