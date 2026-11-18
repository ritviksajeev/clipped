import React, { useEffect, useState } from 'react'
import { api, fmtNum } from '../api.js'
import { Bars, Empty } from '../components/ui.jsx'
import { Count, Kicker, PageHead } from '../fx/components.jsx'

function HourChart({ rows }) {
  const max = Math.max(...rows.map((r) => r.avg_views || 0), 1)
  return (
    <div className="hours">
      {rows.map((r, i) => (
        <div key={r.hour} className="hour" style={{ '--i': i }}
          title={`${String(r.hour).padStart(2, '0')}:00 · ${r.n || 0} uploads · avg ${fmtNum(r.avg_views)} views`}>
          <span className="hour-bar" style={{ height: `${Math.max(2, ((r.avg_views || 0) / max) * 100)}%` }} />
          {r.learned_score != null && <span className="hour-learned" style={{ bottom: `${r.learned_score * 100}%` }} />}
          <span className="hour-label">{r.hour % 3 === 0 ? String(r.hour).padStart(2, '0') : ''}</span>
        </div>
      ))}
    </div>
  )
}

export default function Insights() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { api.get('/api/insights').then(setData).catch((e) => setError(e.message)) }, [])
  if (error) return <div className="banner error">{error}</div>
  if (!data) return <div className="faint label">Loading…</div>
  const s = data.summary
  const pct = (v) => (v == null ? '-' : `${Math.round(v)}%`)
  return (
    <div className="page">
      <PageHead crumb="insights" meta={`${s.matured} uploads with 24h+ of data`} text="What's" accent="working."
        lead="Learned from your own channel's analytics. Auto mode uses the same numbers to pick title styles and posting times." />

      <section className="stat-grid">
        <div className="stat glow reveal"><span className="stat-top">Uploads · 120 days</span><span className="stat-num"><Count value={s.uploads} /></span></div>
        <div className="stat glow reveal d1"><span className="stat-top">Total views</span><span className="stat-num"><Count value={s.total_views} format={fmtNum} /></span></div>
        <div className="stat glow reveal d2"><span className="stat-top">Avg views / short</span><span className="stat-num"><Count value={s.avg_views} format={fmtNum} /></span></div>
        <div className="stat glow reveal d3"><span className="stat-top">Avg % viewed</span><span className="stat-num">{s.avg_retention == null ? '-' : <><Count value={s.avg_retention} /><small>%</small></>}</span></div>
      </section>

      <Kicker idx={1} name="Takeaways" meta="plain words" />
      <section className="card glow reveal">
        {data.tips.length ? <ul className="tips">{data.tips.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="muted">Upload a few Shorts first.</p>}
        <div className="chips">
          <span className={`chip ${data.learning_active.styles ? 'live' : 'wip'}`}>Title-style learning {data.learning_active.styles ? 'on' : 'warming up'}</span>
          <span className={`chip ${data.learning_active.timing ? 'live' : 'wip'}`}>Posting-time learning {data.learning_active.timing ? 'on' : 'warming up'}</span>
        </div>
      </section>

      {s.matured === 0 ? (
        <Empty title="Not enough data yet">Charts appear once uploads have been live for a day and stats have refreshed.</Empty>
      ) : (
        <>
          <Kicker idx={2} name="Breakdown" meta="avg views · uploads" />
          <div className="grid2 cards">
            <section className="card glow reveal"><h2>Title style</h2><Bars rows={data.by_style} format={fmtNum} /></section>
            <section className="card glow reveal d1"><h2>Length</h2><Bars rows={data.by_length} format={fmtNum} /></section>
            <section className="card glow reveal"><h2>Hook</h2><Bars rows={data.by_hook} format={fmtNum} /></section>
            <section className="card glow reveal d1"><h2>Category</h2><Bars rows={data.by_category} format={fmtNum} /></section>
            <section className="card glow reveal"><h2>Streamer</h2><Bars rows={data.by_streamer} format={fmtNum} /></section>
            <section className="card glow reveal d1"><h2>Retention by style</h2><Bars rows={data.by_style} valueKey="avg_retention" format={pct} /></section>
            <section className="card glow reveal span2">
              <div className="card-head"><h2>Posting hour</h2><span className="label">your local time</span></div>
              <HourChart rows={data.by_hour} />
              <p className="field-hint">Bars: average views by upload hour. Green markers: the learned score auto mode leans toward.</p>
            </section>
          </div>
          <Kicker idx={3} name="Top shorts" meta="by blended score" />
          <section className="card glow reveal">
            <ol className="top-list">
              {data.top.map((t) => (
                <li key={t.id}>
                  <a href={`https://youtube.com/shorts/${t.youtube_id}`} target="_blank" rel="noreferrer" data-cursor-label="Watch">{t.title}</a>
                  <span className="q-meta">{fmtNum(t.views)} views · {pct(t.avg_view_pct)} viewed · {t.style}</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </div>
  )
}
