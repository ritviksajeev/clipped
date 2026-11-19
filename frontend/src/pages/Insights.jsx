import React, { useEffect, useState } from 'react'
import { api, fmtNum } from '../api.js'
import { ActivityChart } from '../components/charts.jsx'
import { Bars, Count, Empty, Kicker, Loading, PageHead } from '../components/ui.jsx'

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
  const [act, setAct] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { api.get('/api/insights').then(setData).catch((e) => setError(e.message)) }, [])
  useEffect(() => { api.get('/api/activity?days=30').then(setAct).catch(() => {}) }, [])
  if (error) return <div className="banner error">{error}</div>
  if (!data) return <Loading />
  const s = data.summary
  const pct = (v) => (v == null ? '-' : `${Math.round(v)}%`)
  return (
    <div className="page">
      <PageHead idx={5} crumb="insights" title="What's" accent="working."
        lead="Learned from your own channel. Auto mode uses the same numbers to pick title styles and posting times.">
        <span className="chip">{s.matured} with 24h+ of data</span>
      </PageHead>

      <section className="tiles">
        <div className="tile"><span className="label">Uploads · 120 days</span><b><Count value={s.uploads} /></b></div>
        <div className="tile"><span className="label">Total views</span><b><Count value={s.total_views} format={fmtNum} /></b></div>
        <div className="tile"><span className="label">Avg views / Short</span><b><Count value={s.avg_views} format={fmtNum} /></b></div>
        <div className="tile"><span className="label">Avg % viewed</span><b>{s.avg_retention == null ? '-' : <><Count value={s.avg_retention} /><small>%</small></>}</b></div>
      </section>

      {act && <section className="card chart-card">
        <div className="card-head"><h2>Last 30 days</h2><span className="label">{act.totals.made} made · {act.totals.uploaded} uploaded · {fmtNum(act.totals.views)} views</span></div>
        <ActivityChart days={act.days} />
      </section>}

      <Kicker idx={1} name="Takeaways" meta="plain words" />
      <section className="card glow">
        {data.tips.length ? <ul className="tips">{data.tips.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="muted">Upload a few Shorts first.</p>}
        <div className="chips">
          <span className={`chip ${data.learning_active.styles ? 'live' : 'wip'}`}>Title-style learning {data.learning_active.styles ? 'on' : 'warming up'}</span>
          <span className={`chip ${data.learning_active.timing ? 'live' : 'wip'}`}>Posting-time learning {data.learning_active.timing ? 'on' : 'warming up'}</span>
        </div>
      </section>

      {s.matured === 0 ? (
        <Empty title="Not enough data yet" sticker="insights">Charts appear once uploads have been live for a day and stats have refreshed.</Empty>
      ) : (
        <>
          <Kicker idx={2} name="Breakdown" meta="avg views · uploads" />
          <div className="grid2 cards">
            <section className="card glow"><h2>Title style</h2><Bars rows={data.by_style} format={fmtNum} /></section>
            <section className="card glow"><h2>Length</h2><Bars rows={data.by_length} format={fmtNum} /></section>
            <section className="card glow"><h2>Hook</h2><Bars rows={data.by_hook} format={fmtNum} /></section>
            <section className="card glow"><h2>Category</h2><Bars rows={data.by_category} format={fmtNum} /></section>
            <section className="card glow"><h2>Streamer</h2><Bars rows={data.by_streamer} format={fmtNum} /></section>
            <section className="card glow"><h2>Retention by style</h2><Bars rows={data.by_style} valueKey="avg_retention" format={pct} /></section>
            <section className="card glow span2">
              <div className="card-head"><h2>Posting hour</h2><span className="label">your local time</span></div>
              <HourChart rows={data.by_hour} />
              <p className="field-hint">Bars: average views by upload hour. Green markers: the learned score auto mode leans toward.</p>
            </section>
          </div>
          <Kicker idx={3} name="Top shorts" meta="by blended score" />
          <section className="card glow">
            <ol className="top-list">
              {data.top.map((t) => (
                <li key={t.id}>
                  <a href={`https://youtube.com/shorts/${t.youtube_id}`} target="_blank" rel="noreferrer">{t.title}</a>
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
