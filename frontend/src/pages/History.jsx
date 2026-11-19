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
              <tr><th></th><th>Title</th><th>Posted to</th><th>When</th><th className="num">Views</th><th className="num">Retention</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const locked = r.privacy_requested && r.privacy_actual && r.privacy_requested !== r.privacy_actual
                const privacy = r.privacy_actual || r.privacy_requested
                return (
                  <tr key={r.id}>
                    <td>{r.thumbnail_url ? <img className="mini-thumb" src={r.thumbnail_url} alt="" /> : null}</td>
                    <td className="title-cell">
                      <a href={r.youtube_url || r.instagram_url || undefined} target="_blank" rel="noreferrer">{r.title}</a>
                      <div className="q-meta" style={{ marginTop: 4 }}>{r.streamer} · {r.category_name} · {fmtDuration(r.duration)}</div>
                    </td>
                    <td>
                      <div className="chips">
                        {r.youtube_url && <a className={`chip ${locked ? 'wip' : privacy === 'public' ? 'live' : ''}`} href={r.youtube_url} target="_blank" rel="noreferrer"
                          title={locked ? 'YouTube locked this upload to private: see the API audit step in the YouTube guide' : privacy}>YouTube{privacy && privacy !== 'public' ? ` · ${privacy}` : ''}</a>}
                        {r.instagram_url && <a className="chip live" href={r.instagram_url} target="_blank" rel="noreferrer">Instagram</a>}
                        {r.posted_manually && <span className="chip">by hand</span>}
                      </div>
                      {locked && <div style={{ marginTop: 4 }}><a className="link small" href="#/guides/youtube">why private?</a></div>}
                    </td>
                    <td className="faint mono small">{fmtTime(r.uploaded_at)}</td>
                    <td className="num">{fmtNum(r.stats?.views)}</td>
                    <td className="num">{r.stats?.avg_view_pct != null ? `${Math.round(r.stats.avg_view_pct)}%` : '-'}</td>
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
