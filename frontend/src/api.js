// API wrapper: attach Bearer token, parse error jadi message.
const TOKEN_KEY = 'ccpanel_token'
const ROLE_KEY = 'ccpanel_role'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t, role) {
  localStorage.setItem(TOKEN_KEY, t)
  if (role) localStorage.setItem(ROLE_KEY, role)
}
export function getRole() {
  return localStorage.getItem(ROLE_KEY) || 'client'
}
export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
}

async function request(method, url, body, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const init = { method, headers }
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  } else if (body instanceof FormData) {
    init.body = body
  }
  if (opts.params) {
    const q = new URLSearchParams(opts.params).toString()
    if (q) url += `?${q}`
  }
  const res = await fetch(url, init)
  if (res.status === 401 && getToken()) {
    logout()
    location.reload()
    throw new Error('Sesi habis, login ulang')
  }
  if (!res.ok) {
    let msg = `Error ${res.status}`
    try {
      const j = await res.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* non-JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

async function requestBlob(method, url, body, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const init = { method, headers }
  if (opts.params) {
    const q = new URLSearchParams(opts.params).toString()
    if (q) url += `?${q}`
  }
  const res = await fetch(url, init)
  if (res.status === 401 && getToken()) {
    logout()
    location.reload()
    throw new Error('Sesi habis, login ulang')
  }
  if (!res.ok) {
    let msg = `Error ${res.status}`
    try {
      const j = await res.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* non-JSON */ }
    throw new Error(msg)
  }
  return res.blob()
}

export const api = {
  get: (url, opts) => request('GET', url, undefined, opts),
  post: (url, body, opts) => request('POST', url, body, opts),
  put: (url, body, opts) => request('PUT', url, body, opts),
  delete: (url, opts) => request('DELETE', url, undefined, opts),
  blob: (url, opts) => requestBlob('GET', url, undefined, opts),
}
