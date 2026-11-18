import React, { useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api.js'
import { useApp } from '../App.jsx'
import { AutoWarning, Empty, Field, NumberInput, Select, TagInput, Toggle } from '../components/ui.jsx'
import { Kicker, PageHead } from '../fx/components.jsx'

const PRESETS = {
  'top-left': { x: 0, y: 0, w: 0.26, h: 0.32 },
  'top-right': { x: 0.74, y: 0, w: 0.26, h: 0.32 },
  'bottom-left': { x: 0, y: 0.68, w: 0.26, h: 0.32 },
  'bottom-right': { x: 0.74, y: 0.68, w: 0.26, h: 0.32 },
}

function Picker({ onAdd, existing, enabled }) {
  const { notify } = useApp()
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const timer = useRef(null)
  useEffect(() => {
    if (!enabled) return
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setLoading(true)
      try { setResults(await api.get(`/api/twitch/search?q=${encodeURIComponent(q)}`)) } catch (e) {
        setResults([])
        if (q) notify(e.message, 'error')
      } finally { setLoading(false) }
    }, 300)
    return () => clearTimeout(timer.current)
  }, [q, enabled])
  return (
    <section className="card glow reveal">
      <div className="search-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" /></svg>
        <input className="search" placeholder="Search Twitch: Valorant, Counter-Strike, GTA, Fortnite…" value={q}
          onChange={(e) => setQ(e.target.value)} disabled={!enabled} />
      </div>
      <div className="cat-results">
        {loading && <div className="label full-row">Searching…</div>}
        {results.map((r, i) => {
          const added = existing.includes(r.id)
          return (
            <button key={r.id} className="cat-result glow" style={{ '--i': i }} disabled={added} onClick={() => onAdd(r)}>
              {r.box_art_url ? <img src={r.box_art_url} alt="" onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} /> : <span className="noimg" />}
              <span>{r.name}</span>
              <span className="label">{added ? 'added' : '+ add'}</span>
            </button>
          )
        })}
        {!loading && !results.length && <div className="field-hint full-row">{!enabled ? 'Add your Twitch keys in Settings to search.' : q ? 'No matches.' : 'Type to search, or pick from the top categories once they load.'}</div>}
      </div>
    </section>
  )
}

function CategoryEditor({ cat, onSaved, onDeleted, autoAcked, requestAck, index }) {
  const { notify } = useApp()
  const [s, setS] = useState(cat.settings)
  const [open, setOpen] = useState(false)
  const [fc, setFc] = useState({ login: '', preset: 'top-left' })
  useEffect(() => setS(cat.settings), [cat])
  const set = (k) => (v) => setS({ ...s, [k]: v })
  const dirty = JSON.stringify(s) !== JSON.stringify(cat.settings)

  const save = async (settings = s) => {
    try {
      onSaved(await api.put(`/api/categories/${cat.id}`, { settings }))
      notify(`Saved ${cat.name}`)
    } catch (e) {
      if (e.status === 409) requestAck(() => save(settings))
      else notify(e.message, 'error')
    }
  }
  const modeChip = s.mode === 'auto' ? 'live' : s.mode === 'manual' ? 'accent' : ''
  return (
    <section className={`category glow reveal ${cat.enabled ? '' : 'disabled'}`} style={{ '--d': `${Math.min(index, 6) * 0.06}s` }}>
      <div className="cat-head">
        <div className="cat-title">
          {cat.box_art_url && <img className="boxart" src={cat.box_art_url} alt="" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
          <div>
            <h3>{cat.name}</h3>
            <div className="cat-meta">
              <span className={`chip ${modeChip}`}>{s.mode === 'inherit' ? 'global mode' : s.mode}</span>
              <span className="chip">max {s.max_clips_per_day}/day</span>
              <span className="chip">{s.min_views}+ views</span>
              <span className="chip">last {s.max_age_hours}h</span>
              <span className="chip">{cat.uploads} uploaded</span>
              <span className="chip">fetched {fmtTime(cat.last_fetch_at)}</span>
            </div>
          </div>
        </div>
        <div className="row">
          <Toggle checked={cat.enabled} label={cat.enabled ? 'On' : 'Off'} onChange={async (v) => onSaved(await api.put(`/api/categories/${cat.id}`, { enabled: v }))} />
          <button className="btn small ghost" onClick={async () => {
            try { await api.post(`/api/categories/${cat.id}/fetch`); notify(`Fetching ${cat.name}…`) } catch (e) { notify(e.message, 'error') }
          }}>Fetch now</button>
          <button className={`btn small ${open ? 'primary' : ''}`} onClick={() => setOpen(!open)}>{open ? 'Close' : 'Settings'}</button>
        </div>
      </div>
      <div className={`collapse ${open ? 'open' : ''}`}>
        <div>
          <div className="cat-form">
            <div className="grid3">
              <Field label="Mode" hint="Overrides the global mode">
                <Select value={s.mode} onChange={(v) => {
                  if (v === 'auto' && !autoAcked) requestAck(() => setS((cur) => ({ ...cur, mode: 'auto' })))
                  else set('mode')(v)
                }} options={[['inherit', 'Same as global'], ['manual', 'Manual approval'], ['auto', 'Auto']]} />
              </Field>
              <Field label="Minimum views"><NumberInput value={s.min_views} min={0} onChange={set('min_views')} /></Field>
              <Field label="Clip age window (hours)"><NumberInput value={s.max_age_hours} min={1} max={720} onChange={set('max_age_hours')} /></Field>
              <Field label="Language" hint="ISO code like en, es, pt. Blank = any.">
                <input value={s.language} maxLength={5} onChange={(e) => set('language')(e.target.value.trim())} />
              </Field>
              <Field label="Max clips per day"><NumberInput value={s.max_clips_per_day} min={0} max={50} onChange={set('max_clips_per_day')} /></Field>
            </div>
            <Field label="Streamer allowlist" hint="If set, only these streamers are used. They also count as approved for Auto mode.">
              <TagInput value={s.allowlist} onChange={set('allowlist')} placeholder="twitch login, enter to add" />
            </Field>
            <Field label="Streamer blocklist">
              <TagInput value={s.blocklist} onChange={set('blocklist')} placeholder="never use these streamers" />
            </Field>
            <Field label="Hashtags">
              <TagInput value={s.hashtags} onChange={set('hashtags')} prefix="#" placeholder="#valorant #fps" />
            </Field>
            <Field label="Extra hype keywords" hint="Words that signal a great moment in this game (e.g. ace, clutch)">
              <TagInput value={s.keywords} onChange={set('keywords')} placeholder="ace, 1v5, clutch" />
            </Field>
            <Field label="Facecam positions · split layout per streamer"
              hint="Streamers listed here get facecam-on-top / gameplay-below. Everyone else uses the global layout.">
              <div className="facecams">
                {Object.entries(s.facecams || {}).map(([login, rect]) => (
                  <span className="tag" key={login}>{login}: {Object.entries(PRESETS).find(([, p]) => JSON.stringify(p) === JSON.stringify(rect))?.[0] || 'custom'}
                    <button type="button" onClick={() => { const n = { ...s.facecams }; delete n[login]; set('facecams')(n) }}>×</button></span>
                ))}
                <input placeholder="streamer login" value={fc.login} onChange={(e) => setFc({ ...fc, login: e.target.value })} />
                <Select value={fc.preset} onChange={(v) => setFc({ ...fc, preset: v })} options={Object.keys(PRESETS)} />
                <button className="btn small" type="button" disabled={!fc.login.trim()} onClick={() => {
                  set('facecams')({ ...(s.facecams || {}), [fc.login.trim().toLowerCase()]: PRESETS[fc.preset] })
                  setFc({ ...fc, login: '' })
                }}>Add</button>
              </div>
            </Field>
            <div className="row between" style={{ marginTop: 6 }}>
              <button className="btn small ghost danger" onClick={async () => {
                if (!confirm(`Remove ${cat.name}? Shorts already on YouTube stay there.`)) return
                await api.del(`/api/categories/${cat.id}`)
                onDeleted(cat.id)
              }}>Remove category</button>
              <button className="btn shine" disabled={!dirty} onClick={() => save()}>Save {cat.name} <span className="arrow">→</span></button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default function Categories() {
  const { notify, status } = useApp()
  const [cats, setCats] = useState(null)
  const [ack, setAck] = useState(null)
  useEffect(() => { api.get('/api/categories').then(setCats).catch((e) => notify(e.message, 'error')) }, [])
  const autoAcked = !!status?.auto_warning_acknowledged
  const add = async (r) => {
    try {
      const cat = await api.post('/api/categories', { twitch_id: r.id, name: r.name, box_art_url: r.box_art_url })
      setCats((list) => [...(list || []).filter((c) => c.id !== cat.id), { ...cat, uploads: 0 }])
      notify(`Added ${r.name}`)
    } catch (e) { notify(e.message, 'error') }
  }
  return (
    <div className="page">
      <PageHead crumb="categories" meta={`${cats?.length ?? 0} watching`} text="Pick your" accent="games."
        lead="Search any Twitch category. Each one gets its own filters, hashtags, streamer lists and mode." />
      {!status?.twitch_configured && <div className="banner warn">Add your Twitch keys in <a href="#/settings/connections">Settings</a> to search categories.</div>}
      <Picker onAdd={add} existing={(cats || []).map((c) => c.twitch_id)} enabled={!!status?.twitch_configured} />
      <Kicker idx={1} name="Watching" meta={`${(cats || []).filter((c) => c.enabled).length} enabled`} />
      {cats && cats.length === 0 && <Empty title="No categories yet">Search above and add one or more.</Empty>}
      <div className="cards">
        {(cats || []).map((c, i) => (
          <CategoryEditor key={c.id} cat={c} index={i} autoAcked={autoAcked} requestAck={(then) => setAck(() => then)}
            onSaved={(u) => setCats((list) => list.map((x) => (x.id === u.id ? { ...x, ...u } : x)))}
            onDeleted={(id) => setCats((list) => list.filter((x) => x.id !== id))} />
        ))}
      </div>
      {ack && <AutoWarning onCancel={() => setAck(null)} onAccept={async () => { const fn = ack; setAck(null); await fn() }} />}
    </div>
  )
}
