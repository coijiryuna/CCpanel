#!/usr/bin/env node
// CCPanel client CLI — Node.js (stdlib fetch, tanpa dependency).
//
// Env: CCPANEL_API (default http://127.0.0.1:8888), CCPANEL_TOKEN (opsional,
// kalau kosong baca ~/.ccpanel.json dari hasil `login`).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const API = (process.env.CCPANEL_API || 'http://127.0.0.1:8888').replace(/\/$/, '')
const CFG = process.env.CCPANEL_CONFIG || join(homedir(), '.ccpanel.json')

async function req(method, path, token, body) {
  const res = await fetch(API + path, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

function token() {
  if (process.env.CCPANEL_TOKEN) return process.env.CCPANEL_TOKEN
  try {
    return JSON.parse(readFileSync(CFG, 'utf8')).token
  } catch {
    throw new Error('belum login — jalankan: node ccpanel.mjs login <user> <pass>')
  }
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2)
  switch (cmd) {
    case 'login': {
      const [u, p] = args
      if (!u || !p) throw new Error('pemakaian: ccpanel.mjs login <username> <password>')
      const { token: t } = await req('POST', '/api/login', null, { username: u, password: p })
      writeFileSync(CFG, JSON.stringify({ api: API, token: t }, null, 2), { mode: 0o600 })
      console.log('Login OK. Token disimpan di', CFG)
      break
    }
    case 'sites': {
      const t = token()
      const [sub, ...rest] = args
      if (!sub) {
        const sites = await req('GET', '/api/sites', t)
        for (const s of sites) console.log(`${s.id}\t${s.domain}\t${s.enabled ? 'aktif' : 'nonaktif'}\t${s.webserver}\t${s.php_version}`)
      } else if (sub === 'create') {
        const s = await req('POST', '/api/sites', t, { domain: rest[0] })
        console.log(`Site dibuat: ${s.domain} (id ${s.id})`)
      } else if (sub === 'delete') {
        await req('DELETE', `/api/sites/${rest[0]}`, t)
        console.log('Site dihapus (trash)')
      } else if (sub === 'enable' || sub === 'disable') {
        await req('POST', `/api/sites/${rest[0]}/${sub}`, t)
        console.log(`Site ${sub}`)
      } else if (sub === 'php') {
        await req('PUT', `/api/sites/${rest[0]}/php`, t, { php_version: rest[1] })
        console.log(`PHP ${rest[1]}`)
      } else throw new Error(`sub tidak dikenal: ${sub}`)
      break
    }
    case 'dbs': {
      const t = token()
      const [sub, ...rest] = args
      if (!sub) {
        const dbs = await req('GET', '/api/dbs', t)
        for (const d of dbs) console.log(`${d.id}\t${d.db_name}\t${d.db_user}@${d.db_host}\t${d.db_type}`)
      } else if (sub === 'create') {
        const d = await req('POST', '/api/dbs', t, { db_name: rest[0], ...(rest[1] && { db_user: rest[1] }), ...(rest[2] && { password: rest[2] }) })
        console.log(`DB dibuat: ${d.db_name} (user ${d.db_user}@${d.db_host})`)
      } else if (sub === 'delete') {
        await req('DELETE', `/api/dbs/${rest[0]}`, t)
        console.log('DB dihapus')
      } else throw new Error(`sub tidak dikenal: ${sub}`)
      break
    }
    case 'dashboard': {
      const d = await req('GET', '/api/dashboard', token())
      console.log(`Sites: ${d.counts.sites}  DB: ${d.counts.dbs}  FTP: ${d.counts.ftp}  Users: ${d.counts.users}  Total: ${d.total_size} B`)
      break
    }
    case 'logs': {
      const limit = args[0] || '20'
      const logs = await req('GET', `/api/logs?limit=${limit}`, token())
      for (const l of logs) console.log(`${l.ts.slice(0, 19)}\t${l.user}\t${l.action}\t${l.detail}`)
      break
    }
    default:
      console.log(`CCPanel CLI (Node)

Pemakaian:
  node ccpanel.mjs login <user> <pass>
  node ccpanel.mjs sites [create <domain>|delete <id>|enable|disable <id>|php <id> <versi>]
  node ccpanel.mjs dbs [create <nama> [user] [pass]|delete <id>]
  node ccpanel.mjs dashboard
  node ccpanel.mjs logs [limit]
Env: CCPANEL_API, CCPANEL_TOKEN, CCPANEL_CONFIG`)
  }
}

main().catch((e) => {
  console.error('Error:', e.message)
  process.exit(1)
})
