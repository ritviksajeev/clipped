import React, { useEffect, useState } from 'react'
import { marked } from 'marked'
import { api } from '../api.js'
import { useApp } from '../App.jsx'

marked.setOptions({ gfm: true, breaks: false })

export default function Guides() {
  const { route } = useApp()
  const [guides, setGuides] = useState(null)
  useEffect(() => { api.get('/api/guides').then(setGuides).catch(() => setGuides([])) }, [])
  if (!guides) return <div className="muted">Loading…</div>
  const current = guides.find((g) => g.slug === route.sub) || guides[0]
  return (
    <div className="page">
      <header className="page-head"><h1>Setup guides</h1></header>
      <div className="settings-layout">
        <nav className="subnav">
          {guides.map((g) => <a key={g.slug} href={`#/guides/${g.slug}`} className={current?.slug === g.slug ? 'active' : ''}>{g.title}</a>)}
        </nav>
        <article className="card prose" onClick={(e) => {
          const a = e.target.closest('a')
          if (a && /^https?:/.test(a.getAttribute('href') || '')) { a.target = '_blank'; a.rel = 'noreferrer' }
        }} dangerouslySetInnerHTML={{ __html: current ? marked.parse(current.markdown) : '' }} />
      </div>
    </div>
  )
}
