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

// Launched as a desktop app (`clipped` / `clipped app`): the launcher passes a
// per-launch token so the window can tell the server it is still open.
function readAppToken() {
  let token = new URLSearchParams(window.location.search).get('app')
  try {
    if (token) sessionStorage.setItem('clipped-app', token)
    else token = sessionStorage.getItem('clipped-app') // back from a sign-in page without the query
  } catch { /* storage blocked: the query param is enough */ }
  return token
}
const APP_TOKEN = readAppToken()
let leavingForSignIn = false

export const isDesktop = () => Boolean(window.pywebview || APP_TOKEN)

function appPing(flag = '') {
  if (!APP_TOKEN) return
  const url = `/app/ping?token=${encodeURIComponent(APP_TOKEN)}${flag}`
  if (navigator.sendBeacon && navigator.sendBeacon(url)) return
  fetch(url, { method: 'POST', keepalive: true }).catch(() => {})
}

export function startAppHeartbeat() {
  if (!APP_TOKEN) return
  appPing()
  setInterval(() => appPing(), 15000)
  // Closing the window (or reloading) says goodbye; the server waits a few
  // seconds for a reload to check back in before it quits.
  window.addEventListener('pagehide', () => { if (!leavingForSignIn) appPing('&bye=1') })
}

// Sign-in pages (Google, OpenRouter) open outside the dashboard: in the system
// browser from a native window (Google refuses embedded windows), or in a popup
// from an app window. In a normal browser tab we just navigate there.
export async function openExternal(url) {
  if (window.pywebview?.api?.open_url) {
    await window.pywebview.api.open_url(url)
    return true
  }
  if (APP_TOKEN) {
    const w = window.open(url, 'clipped-signin', 'popup,width=560,height=760')
    if (w) return true
    // Popup blocked: sign in in this window. Tell the server we are only away.
    appPing('&away=1')
    leavingForSignIn = true
  }
  window.location.href = url
  return Boolean(APP_TOKEN)
}
