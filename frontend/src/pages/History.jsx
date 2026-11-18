import React, { useEffect, useState } from 'react'
import { api, fmtDuration, fmtNum, fmtTime } from '../api.js'
import { useApp } from '../App.jsx'
import { Empty } from '../components/ui.jsx'

export default function History() {
  const { notify, status } = useApp()
  const [rows, setRows] = useState(null)
  const load = () => api.get('/api/history?limit=300').then(setRows).catch((e) => notify(e.message, 'error'))
  useEffect(() => { load() }, [status?.items?.uploaded])

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Upload history</h1>
          <p className="muted">Views and retention refresh every 6 hours from the YouTube Data and Analytics APIs.</p>
        </div>
        <button className="btn" onClick={async () => {
          try { await api.post('/api/youtube/refresh-stats'); notify('Refreshing stats…'); setTimeout(load, 5000) } catch (e) { notify(e.message, 'error') }
        }}>Refresh stats now</button>
      </header>
      {rows === null ? <div className="muted">Loading…</div> : rows.length === 0 ? (
        <Empty title="No uploads yet">Approved clips appear here once they're on YouTube.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th></th><th>Title</th><th>Streamer</th><th>Uploaded</th><th>Privacy</th><th className="num">Views</th><th className="num">Retention</th><th className="num">Likes</th><th>Style</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const locked = r.privacy_requested && r.privacy_actual && r.privacy_requested !== r.privacy_actual
                return (
                  <tr key={r.id}>
                    <td>{r.thumbnail_url ? <img className="mini-thumb" src={r.thumbnail_url} alt="" /> : null}</td>
                    <td className="title-cell">
                      <a href={r.youtube_url} target="_blank" rel="noreferrer">{r.title}</a>
                      <div className="muted small">{r.category_name} · {fmtDuration(r.duration)} · {r.mode}</div>
                    </td>
                    <td>{r.streamer}</td>
                    <td>{fmtTime(r.uploaded_at)}</td>
                    <td>
                      <span className={`pill ${locked ? 'warn' : ''}`} title={locked ? 'YouTube locked this upload to private: see the API audit step in the YouTube guide' : ''}>
                        {r.privacy_actual || r.privacy_requested}
                      </span>
                      {locked && <div className="small"><a href="#/guides/youtube">why?</a></div>}
                    </td>
                    <td className="num">{fmtNum(r.stats?.views)}</td>
                    <td className="num">{r.stats?.avg_view_pct != null ? `${Math.round(r.stats.avg_view_pct)}%` : '-'}</td>
                    <td className="num">{fmtNum(r.stats?.likes)}</td>
                    <td><span className="pill">{r.title_style || '-'}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
