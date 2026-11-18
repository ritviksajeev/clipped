import React, { useEffect, useState } from 'react'
import { api, fmtNum } from '../api.js'
import { Bars, Empty } from '../components/ui.jsx'

function HourChart({ rows }) {
  const max = Math.max(...rows.map((r) => r.avg_views || 0), 1)
  return (
    <div className="hours">
      {rows.map((r) => (
        <div key={r.hour} className="hour" title={`${String(r.hour).padStart(2, '0')}:00 · ${r.n || 0} uploads · avg ${fmtNum(r.avg_views)} views`}>
          <span className="hour-bar" style={{ height: `${Math.max(2, ((r.avg_views || 0) / max) * 100)}%` }} />
          {r.learned_score != null && <span className="hour-learned" style={{ bottom: `${r.learned_score * 100}%` }} />}
          <span className="hour-label">{r.hour % 3 === 0 ? r.hour : ''}</span>
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
  if (!data) return <div className="muted">Loading…</div>
  const s = data.summary
  const pct = (v) => (v == null ? '-' : `${Math.round(v)}%`)
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>What's working</h1>
          <p className="muted">Learned from your own channel's YouTube Analytics. Only uploads live for 24h+ count.</p>
        </div>
      </header>
      <section className="stats-grid">
        <div className="stat card"><div className="stat-num">{s.uploads}</div><div className="muted">uploads (120 days)</div></div>
        <div className="stat card"><div className="stat-num">{fmtNum(s.total_views)}</div><div className="muted">total views</div></div>
        <div className="stat card"><div className="stat-num">{fmtNum(s.avg_views)}</div><div className="muted">avg views / Short</div></div>
        <div className="stat card"><div className="stat-num">{pct(s.avg_retention)}</div><div className="muted">avg % viewed</div></div>
      </section>

      <section className="card">
        <h2>Takeaways</h2>
        {data.tips.length ? <ul className="tips">{data.tips.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="muted">Upload a few Shorts first.</p>}
        <div className="row gap small">
          <span className={`pill ${data.learning_active.styles ? 'ok' : ''}`}>Title-style learning {data.learning_active.styles ? 'active' : 'warming up'}</span>
          <span className={`pill ${data.learning_active.timing ? 'ok' : ''}`}>Posting-time learning {data.learning_active.timing ? 'active' : 'warming up'}</span>
        </div>
      </section>

      {s.matured === 0 ? (
        <Empty title="Not enough data yet">Charts appear once uploads have been live for a day and stats have refreshed.</Empty>
      ) : (
        <div className="grid2 cards">
          <section className="card"><h2>Title style</h2><Bars rows={data.by_style} format={fmtNum} /></section>
          <section className="card"><h2>Length</h2><Bars rows={data.by_length} format={fmtNum} /></section>
          <section className="card"><h2>Hook</h2><Bars rows={data.by_hook} format={fmtNum} /></section>
          <section className="card"><h2>Category</h2><Bars rows={data.by_category} format={fmtNum} /></section>
          <section className="card"><h2>Streamer</h2><Bars rows={data.by_streamer} format={fmtNum} /></section>
          <section className="card"><h2>Retention by style</h2><Bars rows={data.by_style} valueKey="avg_retention" format={pct} /></section>
          <section className="card span2">
            <h2>Posting hour (your local time)</h2>
            <HourChart rows={data.by_hour} />
            <p className="muted small">Bars: average views by upload hour. Markers: the learned score auto mode uses to nudge the schedule.</p>
          </section>
          <section className="card span2">
            <h2>Top Shorts</h2>
            <ol className="top-list">
              {data.top.map((t) => (
                <li key={t.id}>
                  <a href={`https://youtube.com/shorts/${t.youtube_id}`} target="_blank" rel="noreferrer">{t.title}</a>
                  <span className="muted small"> · {fmtNum(t.views)} views · {pct(t.avg_view_pct)} viewed · {t.style}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </div>
  )
}
