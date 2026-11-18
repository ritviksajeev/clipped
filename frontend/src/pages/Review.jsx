import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, fmtDuration, fmtNum, fmtTime } from '../api.js'
import { useApp } from '../App.jsx'
import { Empty, Field, Select } from '../components/ui.jsx'

const TABS = [
  ['review', 'Needs review'],
  ['approved,ready,uploading', 'Approved & scheduled'],
  ['failed', 'Failed'],
  ['rejected', 'Rejected'],
]
const STYLE_LABEL = { hype: 'Hype', question: 'Question', descriptive: 'Descriptive', streamer: 'Streamer first' }

function hashtagsFrom(description) {
  return (description.match(/#[\p{L}\p{N}_]+/gu) || []).filter((v, i, a) => a.indexOf(v) === i)
}

function Editor({ item, onChanged, onRemoved }) {
  const { notify, refreshStatus } = useApp()
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState('')
  const [frameKey, setFrameKey] = useState(0)

  useEffect(() => {
    setForm({
      title: item.title, description: item.description, hook_text: item.hook_text,
      thumbnail_text: item.thumbnail_text, commentary: item.commentary,
      hashtags: hashtagsFrom(item.description).join(' '),
    })
  }, [item.id, item.updated_at])

  if (!form) return null
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const dirty = ['title', 'description', 'hook_text', 'thumbnail_text', 'commentary'].some((k) => (form[k] ?? '') !== (item[k] ?? ''))
    || form.hashtags !== hashtagsFrom(item.description).join(' ')
  const renderDirty = ['hook_text', 'thumbnail_text', 'commentary'].some((k) => (form[k] ?? '') !== (item[k] ?? ''))
  const editable = !['uploading', 'uploaded'].includes(item.status)

  const run = async (label, fn) => {
    setBusy(label)
    try { await fn() } catch (e) { notify(e.message, 'error') } finally { setBusy('') }
  }
  const save = async () => {
    const body = {}
    for (const k of ['title', 'hook_text', 'thumbnail_text', 'commentary']) if ((form[k] ?? '') !== (item[k] ?? '')) body[k] = form[k]
    if (form.description !== item.description) body.description = form.description
    if (form.hashtags !== hashtagsFrom(item.description).join(' ')) body.hashtags = form.hashtags.split(/[\s,]+/).filter(Boolean)
    const updated = await api.patch(`/api/items/${item.id}`, body)
    onChanged(updated)
    return updated
  }
  const chooseVariant = (i) => run('variant', async () => onChanged(await api.patch(`/api/items/${item.id}`, { chosen: i })))
  const approve = (uploadNow) => run(uploadNow ? 'upload' : 'approve', async () => {
    if (dirty) await save()
    await api.post(`/api/items/${item.id}/approve`, { upload_now: uploadNow })
    notify(uploadNow ? 'Approved, uploading now' : 'Approved and queued for upload')
    onRemoved(item.id)
    refreshStatus()
  })
  const reject = () => run('reject', async () => {
    await api.post(`/api/items/${item.id}/reject`)
    notify('Rejected')
    onRemoved(item.id)
    refreshStatus()
  })
  const rerender = () => run('rerender', async () => {
    if (dirty) await save()
    await api.post(`/api/items/${item.id}/rerender`)
    notify('Re-rendering… the preview updates when it is done')
    const started = Date.now()
    const poll = setInterval(async () => {
      const fresh = await api.get(`/api/items/${item.id}`)
      if (!fresh.needs_rerender || Date.now() - started > 300000) {
        clearInterval(poll)
        onChanged(fresh)
        setFrameKey((k) => k + 1)
      }
    }, 2500)
  })
  const retry = () => run('retry', async () => {
    const r = await api.post(`/api/items/${item.id}/retry`)
    notify(r.requeued ? 'Re-processing this clip' : 'Moved back to the queue')
    onRemoved(item.id)
  })
  const uploadThumb = (file) => run('thumb', async () => {
    onChanged(await api.upload(`/api/items/${item.id}/thumbnail`, file))
    setFrameKey((k) => k + 1)
  })

  const a = item.analysis || {}
  return (
    <div className="editor">
      <div className="preview-col">
        {item.video_url
          ? <video key={item.video_url + frameKey} className="phone" src={item.video_url} controls playsInline preload="metadata" poster={item.thumbnail_url} />
          : <div className="phone placeholder">No video</div>}
        <div className="meta-list small">
          <div><span className="muted">Streamer</span> {item.clip?.channel_url ? <a href={item.clip.channel_url} target="_blank" rel="noreferrer">{item.streamer}</a> : item.streamer}</div>
          <div><span className="muted">Category</span> {item.category_name || '-'}</div>
          <div><span className="muted">Length</span> {fmtDuration(item.duration)}</div>
          <div><span className="muted">Hype</span> {Math.round((item.hype || 0) * 100)}%</div>
          {item.clip?.view_count != null && <div><span className="muted">Twitch views</span> {fmtNum(item.clip.view_count)}</div>}
          {item.clip?.url && <div><a href={item.clip.url} target="_blank" rel="noreferrer">Original clip ↗</a></div>}
        </div>
        {a.notes?.length > 0 && <ul className="notes small">{a.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      </div>

      <div className="form-col">
        {item.error && <div className={`banner ${item.status === 'failed' ? 'error' : 'warn'} small`}>{item.error}</div>}
        {item.variants?.length > 1 && (
          <div className="variants">
            <div className="field-label">Title variants</div>
            {item.variants.map((v, i) => (
              <button key={i} type="button" className={`variant ${item.chosen === i ? 'chosen' : ''}`}
                disabled={!editable || busy} onClick={() => chooseVariant(i)}>
                <span className="pill">{STYLE_LABEL[v.style] || v.style}{v.source !== 'template' ? ` · ${v.source}` : ''}</span>
                <span>{v.title}</span>
              </button>
            ))}
          </div>
        )}
        <Field label={<>Title <span className={`muted small ${form.title.length > 100 ? 'warn-text' : ''}`}>{form.title.length}/100</span></>}>
          <input value={form.title} onChange={set('title')} disabled={!editable} />
        </Field>
        <Field label="Description" hint="The streamer credit and both links are always kept, even if you delete them here.">
          <textarea rows={8} value={form.description} onChange={set('description')} disabled={!editable} />
        </Field>
        <Field label="Hashtags" hint="Space separated. #Shorts is always included.">
          <input value={form.hashtags} onChange={set('hashtags')} disabled={!editable} />
        </Field>
        <div className="grid2">
          <Field label="On-screen hook (first 2 s)">
            <input value={form.hook_text} onChange={set('hook_text')} disabled={!editable} maxLength={40} />
          </Field>
          <Field label="Thumbnail text">
            <input value={form.thumbnail_text} onChange={set('thumbnail_text')} disabled={!editable} maxLength={80} />
          </Field>
        </div>
        <Field label="Commentary (on screen + description)" hint="Your own take makes the Short more than a repost.">
          <input value={form.commentary} onChange={set('commentary')} disabled={!editable} maxLength={200} placeholder="e.g. Watch his crosshair before the swing" />
        </Field>
        <div className="thumb-row">
          {item.thumbnail_url && <img key={frameKey} src={item.thumbnail_url} alt="Thumbnail" className="thumb" />}
          {editable && <label className="btn ghost small">
            Upload custom thumbnail
            <input type="file" accept="image/*" hidden onChange={(e) => e.target.files[0] && uploadThumb(e.target.files[0])} />
          </label>}
        </div>
        {(renderDirty || item.needs_rerender) && editable && <div className="banner warn small">Hook, thumbnail or commentary changed. Re-render to update the video (approving re-renders automatically).</div>}
        <div className="actions">
          {item.status === 'review' && <>
            <button className="btn primary" disabled={!!busy} onClick={() => approve(false)}>{busy === 'approve' ? 'Approving…' : 'Approve'}</button>
            <button className="btn" disabled={!!busy} onClick={() => approve(true)}>Approve & upload now</button>
          </>}
          {['approved', 'ready'].includes(item.status) && <button className="btn" disabled={!!busy} onClick={() => run('upload', async () => {
            if (dirty) await save()
            await api.post(`/api/items/${item.id}/upload-now`)
            notify('Uploading now')
          })}>Upload now</button>}
          {editable && dirty && <button className="btn" disabled={!!busy} onClick={() => run('save', async () => { await save(); notify('Saved') })}>Save edits</button>}
          {editable && <button className="btn ghost" disabled={!!busy} onClick={rerender}>{busy === 'rerender' ? 'Re-rendering…' : 'Re-render'}</button>}
          {['failed', 'rejected'].includes(item.status) && <button className="btn" disabled={!!busy} onClick={retry}>Retry</button>}
          {['review', 'approved', 'ready', 'failed'].includes(item.status) && <button className="btn danger" disabled={!!busy} onClick={reject}>Reject</button>}
        </div>
      </div>
    </div>
  )
}

function AddClip({ onAdded }) {
  const { notify } = useApp()
  const [url, setUrl] = useState('')
  const [cats, setCats] = useState([])
  const [cat, setCat] = useState('')
  useEffect(() => { api.get('/api/categories').then(setCats).catch(() => {}) }, [])
  return (
    <form className="add-clip" onSubmit={async (e) => {
      e.preventDefault()
      try {
        await api.post('/api/clips', { url, category_id: cat ? Number(cat) : null })
        notify('Clip queued. It will appear here once rendered.')
        setUrl('')
        onAdded?.()
      } catch (err) { notify(err.message, 'error') }
    }}>
      <input placeholder="Paste a Twitch clip URL to process it manually" value={url} onChange={(e) => setUrl(e.target.value)} />
      <Select value={cat} onChange={setCat} options={[['', 'No category'], ...cats.map((c) => [String(c.id), c.name])]} />
      <button className="btn" disabled={!url}>Add clip</button>
    </form>
  )
}

export default function Review() {
  const { route, status } = useApp()
  const [tab, setTab] = useState(route.params.get('tab') === 'failed' ? 'failed' : 'review')
  const [items, setItems] = useState(null)
  const [selected, setSelected] = useState(null)

  const load = useCallback(async () => {
    const list = await api.get(`/api/items?status=${tab}`)
    setItems(list)
    setSelected((cur) => (cur && list.some((i) => i.id === cur) ? cur : list[0]?.id ?? null))
  }, [tab])

  useEffect(() => { load() }, [load, status?.items?.review, status?.items?.approved])

  const [detail, setDetail] = useState(null)
  useEffect(() => {
    if (!selected) { setDetail(null); return }
    api.get(`/api/items/${selected}`).then(setDetail).catch(() => setDetail(null))
  }, [selected])

  const counts = status?.items || {}
  const tabCount = useMemo(() => ({
    review: counts.review || 0,
    'approved,ready,uploading': (counts.approved || 0) + (counts.ready || 0) + (counts.uploading || 0),
    failed: counts.failed || 0,
    rejected: counts.rejected || 0,
  }), [counts])

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="muted">Nothing is uploaded until you approve it (unless a category is in Auto mode).</p>
        </div>
      </header>
      <AddClip onAdded={load} />
      <div className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={tab === key ? 'active' : ''} onClick={() => { setTab(key); setSelected(null) }}>
            {label} {tabCount[key] > 0 && <span className="badge">{tabCount[key]}</span>}
          </button>
        ))}
      </div>
      {items === null ? <div className="muted">Loading…</div> : items.length === 0 ? (
        <Empty title={tab === 'review' ? 'Nothing to review' : 'Nothing here'}>
          {tab === 'review' && (status?.running
            ? 'ClipPilot is looking for clips. New renders will show up here.'
            : <>Press <a href="#/dashboard">Start</a> to begin finding clips, or paste a clip URL above.</>)}
        </Empty>
      ) : (
        <div className="review-layout">
          <ul className="queue">
            {items.map((i) => (
              <li key={i.id}>
                <button className={selected === i.id ? 'active' : ''} onClick={() => setSelected(i.id)}>
                  {i.thumbnail_url ? <img src={i.thumbnail_url} alt="" /> : <span className="noimg" />}
                  <span className="q-text">
                    <span className="q-title">{i.title || i.clip_id}</span>
                    <span className="muted small">{i.streamer} · {i.category_name} · {fmtDuration(i.duration)}</span>
                    <span className="muted small">{i.status}{i.mode === 'auto' ? ' · auto' : ''}{i.needs_rerender ? ' · needs re-render' : ''} · {fmtTime(i.created_at)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {detail && <Editor item={detail}
            onChanged={(u) => { setDetail((d) => ({ ...d, ...u })); setItems((list) => list.map((x) => (x.id === u.id ? { ...x, ...u } : x))) }}
            onRemoved={(id) => { setItems((list) => list.filter((x) => x.id !== id)); setSelected(null) }} />}
        </div>
      )}
    </div>
  )
}
