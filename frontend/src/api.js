async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let detail = await res.text()
    try {
      const j = JSON.parse(detail)
      detail = j.detail || detail
    } catch (_) {}
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  dashboard: () => request('/api/dashboard'),
  skus: () => request('/api/skus'),
  tickets: () => request('/api/tickets'),
  ticket: (id) => request(`/api/tickets/${id}`),
  createTicket: (body) => request('/api/tickets', { method: 'POST', body: JSON.stringify(body) }),
  clock: () => request('/api/apply/clock'),
  setClock: (business_clock) =>
    request('/api/apply/clock', { method: 'PUT', body: JSON.stringify({ business_clock }) }),
  applyDue: () => request('/api/apply/due', { method: 'POST' }),
  batches: () => request('/api/apply/batches'),
  applyRejections: () => request('/api/apply/rejections'),
  priceBook: () => request('/api/prices/book'),
  history: (sku) => request(sku ? `/api/prices/history?sku_code=${encodeURIComponent(sku)}` : '/api/prices/history'),
  reconConfig: () => request('/api/reconcile/config'),
  saveReconConfig: (body) =>
    request('/api/reconcile/config', { method: 'PUT', body: JSON.stringify(body) }),
  runReconcile: () => request('/api/reconcile/run', { method: 'POST' }),
  reconReports: () => request('/api/reconcile/reports'),
  reconReport: (id) => request(`/api/reconcile/reports/${id}`),
  reconFlags: (status) =>
    request(status ? `/api/reconcile/flags?status=${encodeURIComponent(status)}` : '/api/reconcile/flags'),
  resolveFlag: (id, note) =>
    request(`/api/reconcile/flags/${id}/resolve`, { method: 'POST', body: JSON.stringify({ note }) }),
}
