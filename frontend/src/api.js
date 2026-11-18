// Tiny API client. Every state-changing request carries X-Clipped: 1,
// which the backend requires (blocks cross-site requests from other tabs).

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, body, isForm = false) {
  const opts = { method, headers: {} }
  if (method !== 'GET') opts.headers['X-Clipped'] = '1'
  if (body !== undefined) {
    if (isForm) opts.body = body
    else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  const res = await fetch(path, opts)
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    let detail = data && data.detail !== undefined ? data.detail : data
    if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
    throw new ApiError(res.status, detail || res.statusText)
  }
  return data
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b = {}) => request('POST', p, b),
  put: (p, b) => request('PUT', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: (p) => request('DELETE', p),
  upload: (p, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', p, fd, true)
  },
}

export function fmtDuration(seconds) {
  if (seconds == null) return '-'
  seconds = Math.max(0, Math.round(seconds))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`
  return `${s}s`
}

export function fmtTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function fmtNum(n) {
  if (n == null) return '-'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e4) return Math.round(n / 1e3) + 'K'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}
