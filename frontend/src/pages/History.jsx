import React, { useEffect, useState } from 'react'
import { api, fmtDuration, fmtNum, fmtTime } from '../api.js'
import { useApp } from '../App.jsx'
import { Empty, Loading, PageHead } from '../components/ui.jsx'

export default function History() {
  const { notify, status } = useApp()
  const [rows, setRows] = useState(null)
  const load = () => api.get('/api/history?limit=300').then(setRows).catch((e) => notify(e.message, 'error'))
  useEffect(() => { load() }, [status?.items?.uploaded])

  return (
    <div className="page">
      <PageHead idx={4} crumb="history" title="Upload" accent="log."
        lead="Every Short that went up, with views and retention from YouTube, refreshed every six hours.">
        <button className="btn small" onClick={async () => {
          try { await api.post('/api/youtube/refresh-stats'); notify('Refreshing stats…'); setTimeout(load, 5000) } catch (e) { notify(e.message, 'error') }
        }}>Refresh stats <span className="arrow">↻</span></button>
      </PageHead>
      {rows === null ? <Loading /> : rows.length === 0 ? (
        <Empty title="Nothing uploaded yet" sticker="history">Approved clips appear here once they're live on YouTube.</Empty>
      ) : (
        <div className="table-wrap card glow">
          <table className="table">
            <thead>
              <tr><th></th><th>Title</th><th>Streamer</th><th>Uploaded</th><th>Privacy</th><th className="num">Views</th><th className="num">Retention</th><th className="num">Likes</th><th>Style</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const locked = r.privacy_requested && r.privacy_actual && r.privacy_requested !== r.privacy_actual
                const privacy = r.privacy_actual || r.privacy_requested
                return (
                  <tr key={r.id}>
                    <td>{r.thumbnail_url ? <img className="mini-thumb" src={r.thumbnail_url} alt="" /> : null}</td>
                    <td className="title-cell">
                      <a href={r.youtube_url} target="_blank" rel="noreferrer">{r.title}</a>
                      <div className="q-meta" style={{ marginTop: 4 }}>{r.category_name} · {fmtDuration(r.duration)} · {r.mode}</div>
                    </td>
                    <td>{r.streamer}</td>
                    <td className="faint mono small">{fmtTime(r.uploaded_at)}</td>
                    <td>
                      <span className={`chip ${locked ? 'wip' : privacy === 'public' ? 'live' : ''}`}
                        title={locked ? 'YouTube locked this upload to private: see the API audit step in the YouTube guide' : ''}>
                        {privacy}
                      </span>
                      {locked && <div style={{ marginTop: 4 }}><a className="link small" href="#/guides/youtube">why?</a></div>}
                    </td>
                    <td className="num">{fmtNum(r.stats?.views)}</td>
                    <td className="num">{r.stats?.avg_view_pct != null ? `${Math.round(r.stats.avg_view_pct)}%` : '-'}</td>
                    <td className="num">{fmtNum(r.stats?.likes)}</td>
                    <td><span className="chip">{r.title_style || '-'}</span></td>
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
