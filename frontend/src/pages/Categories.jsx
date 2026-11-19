import React, { useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api.js'
import { useApp } from '../App.jsx'
import { AutoWarning, Empty, Field, Loading, NumberInput, PageHead, Select, TagInput, Toggle } from '../components/ui.jsx'
import { Sticker } from '../stickers.jsx'

const DISCOVERY = { inherit: 'global discovery', trending: 'trending now', top24h: 'top 24h' }
const PRESETS = {
  'top-left': { x: 0, y: 0, w: 0.26, h: 0.32 },
  'top-right': { x: 0.74, y: 0, w: 0.26, h: 0.32 },
  'bottom-left': { x: 0, y: 0.68, w: 0.26, h: 0.32 },
  'bottom-right': { x: 0.74, y: 0.68, w: 0.26, h: 0.32 },
}
const TILTS = [-6, 4, -3, 5, -5, 3, -4, 6, -2, 4]

// Box art as a die-cut sticker: white border, a tilt, a drop shadow. If the
// image can't load, a controller sticker stands in.
export function BoxArt({ src, i = 0, size = 'md' }) {
  const [failed, setFailed] = useState(false)
  return (
    <span className={`boxart ${size} ${!src || failed ? 'fallback' : ''}`} style={{ '--r': `${TILTS[i % TILTS.length]}deg` }}>
      {src && !failed ? <img src={src} alt="" onError={() => setFailed(true)} /> : <Sticker name="categories" />}
    </span>
  )
}

function Discover({ q, enabled, existing, onAdd }) {
  const { notify } = useApp()
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
  if (!enabled) return <Empty title="Twitch keys needed" sticker="key">Add your Twitch keys in <a className="link" href="#/settings/connections">Settings → Connections</a> to search categories.</Empty>
  return (
    <div className="discover">
      <div className="pane-head"><h2>{q ? <>Results for “{q}”</> : <>Top on Twitch <span className="serif accent">right now</span></>}</h2>{loading && <span className="label">searching…</span>}</div>
      <div className="art-grid">
        {results.map((r, i) => {
          const added = existing.includes(r.id)
          return (
            <button key={r.id} className={`art-pick ${added ? 'added' : ''}`} disabled={added} onClick={() => onAdd(r)} style={{ '--i': i }}>
              <BoxArt src={r.box_art_url} i={i} size="lg" />
              <span className="art-name">{r.name}</span>
              <span className="label">{added ? 'watching' : '+ add'}</span>
            </button>
          )
        })}
        {!loading && !results.length && <p className="field-hint">{q ? 'No matches.' : 'Nothing loaded yet.'}</p>}
      </div>
    </div>
  )
}

function CategoryEditor({ cat, onSaved, onDeleted, autoAcked, requestAck, index }) {
  const { notify } = useApp()
  const [s, setS] = useState(cat.settings)
  const [fc, setFc] = useState({ login: '', preset: 'top-left' })
  useEffect(() => setS(cat.settings), [cat])
  const set = (k) => (v) => setS({ ...s, [k]: v })
  const dirty = JSON.stringify(s) !== JSON.stringify(cat.settings)

  const save = async (settings = s) => {
    try {
      onSaved(await api.put(`/api/categories/${cat.id}`, { settings }))
      notify(`Saved ${cat.name}`, 'ok')
    } catch (e) {
      if (e.status === 409) requestAck(() => save(settings))
      else notify(e.message, 'error')
    }
  }
  return (
    <div className="cat-editor">
      <div className="cat-hero">
        <BoxArt src={cat.box_art_url} i={index} size="xl" />
        <div className="cat-hero-text">
          <h2>{cat.name}</h2>
          <div className="chips">
            <span className={`chip ${cat.enabled ? 'live' : ''}`}>{cat.enabled ? 'on' : 'off'}</span>
            <span className="chip">{s.mode === 'inherit' ? 'global mode' : s.mode}</span>
            <span className="chip">{DISCOVERY[s.discovery || 'inherit']}</span>
            <span className="chip">{cat.uploads} uploaded</span>
            <span className="chip">fetched {fmtTime(cat.last_fetch_at)}</span>
          </div>
          <div className="row">
            <Toggle checked={cat.enabled} label={cat.enabled ? 'Watching' : 'Paused'} onChange={async (v) => onSaved(await api.put(`/api/categories/${cat.id}`, { enabled: v }))} />
            <button className="btn small" onClick={async () => {
              try { await api.post(`/api/categories/${cat.id}/fetch`); notify(`Fetching ${cat.name}…`) } catch (e) { notify(e.message, 'error') }
            }}>Fetch now</button>
          </div>
        </div>
      </div>

      <section className="card glow">
        <div className="card-head"><h2>Finding clips</h2></div>
        <div className="grid3">
          <Field label="Find clips" hint="Trending = rising fastest now. Top 24h = most viewed today.">
            <Select value={s.discovery || 'inherit'} onChange={set('discovery')}
              options={[['inherit', 'Same as global'], ['trending', 'Trending now'], ['top24h', 'Top of the last 24h']]} />
          </Field>
          <Field label="Minimum views"><NumberInput value={s.min_views} min={0} onChange={set('min_views')} /></Field>
          <Field label="Max clips per day"><NumberInput value={s.max_clips_per_day} min={0} max={50} onChange={set('max_clips_per_day')} /></Field>
          <Field label="Mode" hint="Overrides the global mode">
            <Select value={s.mode} onChange={(v) => {
              if (v === 'auto' && !autoAcked) requestAck(() => setS((cur) => ({ ...cur, mode: 'auto' })))
              else set('mode')(v)
            }} options={[['inherit', 'Same as global'], ['manual', 'Manual approval'], ['auto', 'Auto']]} />
          </Field>
          <Field label="Language" hint="ISO code like en, es, pt. Blank = any.">
            <input value={s.language} maxLength={5} onChange={(e) => set('language')(e.target.value.trim())} />
          </Field>
        </div>
      </section>

      <section className="card glow">
        <div className="card-head"><h2>Streamers & tags</h2></div>
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
      </section>

      <section className="card glow">
        <div className="card-head"><h2>Facecams</h2><span className="label">split layout per streamer</span></div>
        <p className="field-hint" style={{ marginBottom: 12 }}>Streamers listed here get facecam-on-top, gameplay-below. Everyone else uses the global layout.</p>
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
      </section>

      <div className="savebar inline">
        <button className="btn small ghost danger" onClick={async () => {
          if (!confirm(`Remove ${cat.name}? Shorts already on YouTube stay there.`)) return
          await api.del(`/api/categories/${cat.id}`)
          onDeleted(cat.id)
        }}>Remove category</button>
        <span className="savebar-space" />
        {dirty && <button className="btn small ghost" onClick={() => setS(cat.settings)}>Discard</button>}
        <button className="btn primary" disabled={!dirty} onClick={() => save()}>Save {cat.name} <span className="arrow">→</span></button>
      </div>
    </div>
  )
}

export default function Categories() {
  const { notify, status } = useApp()
  const [cats, setCats] = useState(null)
  const [ack, setAck] = useState(null)
  const [selected, setSelected] = useState(null)
  const [q, setQ] = useState('')
  const [discover, setDiscover] = useState(false)
  useEffect(() => {
    api.get('/api/categories').then((list) => {
      setCats(list)
      setSelected((cur) => cur ?? list[0]?.id ?? null)
      if (!list.length) setDiscover(true)
    }).catch((e) => notify(e.message, 'error'))
  }, [])
  const autoAcked = !!status?.auto_warning_acknowledged
  const add = async (r) => {
    try {
      const cat = await api.post('/api/categories', { twitch_id: r.id, name: r.name, box_art_url: r.box_art_url })
      setCats((list) => [...(list || []).filter((c) => c.id !== cat.id), { ...cat, uploads: 0 }])
      setSelected(cat.id)
      setDiscover(false)
      setQ('')
      notify(`Added ${r.name}`, 'ok')
    } catch (e) { notify(e.message, 'error') }
  }
  const showDiscover = discover || q.length > 0
  const current = (cats || []).find((c) => c.id === selected)
  const index = (cats || []).findIndex((c) => c.id === selected)

  return (
    <div className="page fill">
      <PageHead idx={3} crumb="categories" title="Pick your" accent="games."
        lead="Search any Twitch category. Each one gets its own filters, hashtags, streamer lists and mode.">
        <span className="chip">{(cats || []).filter((c) => c.enabled).length} watching</span>
      </PageHead>
      <div className="cat-layout">
        <div className="pane cat-list">
          <div className="search-wrap">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" /></svg>
            <input className="search" placeholder="Search Twitch…" value={q} onChange={(e) => setQ(e.target.value)}
              onFocus={() => setDiscover(true)} disabled={!status?.twitch_configured} />
          </div>
          <button className={`cat-row add ${showDiscover ? 'active' : ''}`} onClick={() => { setDiscover(true); setQ('') }}>
            <span className="plus">+</span><span className="cat-row-name">Add a game</span>
          </button>
          {cats === null ? <Loading /> : cats.map((c, i) => (
            <button key={c.id} className={`cat-row ${!showDiscover && selected === c.id ? 'active' : ''} ${c.enabled ? '' : 'off'}`}
              onClick={() => { setSelected(c.id); setDiscover(false); setQ('') }}>
              <BoxArt src={c.box_art_url} i={i} size="sm" />
              <span className="cat-row-text">
                <span className="cat-row-name">{c.name}</span>
                <span className="q-meta">{c.enabled ? DISCOVERY[c.settings.discovery || 'inherit'] : 'paused'} · {c.uploads} up</span>
              </span>
              <span className={`led ${c.enabled ? 'on' : ''}`} />
            </button>
          ))}
        </div>
        <div className="pane">
          {showDiscover || !current
            ? <Discover q={q} enabled={!!status?.twitch_configured} existing={(cats || []).map((c) => c.twitch_id)} onAdd={add} />
            : <CategoryEditor key={current.id} cat={current} index={index} autoAcked={autoAcked} requestAck={(then) => setAck(() => then)}
              onSaved={(u) => setCats((list) => list.map((x) => (x.id === u.id ? { ...x, ...u } : x)))}
              onDeleted={(id) => { setCats((list) => list.filter((x) => x.id !== id)); setSelected(null) }} />}
        </div>
      </div>
      {ack && <AutoWarning onCancel={() => setAck(null)} onAccept={async () => { const fn = ack; setAck(null); await fn() }} />}
    </div>
  )
}
