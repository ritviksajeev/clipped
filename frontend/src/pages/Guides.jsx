import React, { useEffect, useState } from 'react'
import { marked } from 'marked'
import { api } from '../api.js'
import { useApp } from '../App.jsx'
import { Loading, PageHead } from '../components/ui.jsx'
import { Sticker } from '../stickers.jsx'

marked.setOptions({ gfm: true, breaks: false })

const STK = { 'quick-start': 'dashboard', twitch: 'key', youtube: 'review', instagram: 'clipped', 'ai-titles': 'sparkle', ffmpeg: 'settings',
  safety: 'power', troubleshooting: 'empty' }

export default function Guides() {
  const { route } = useApp()
  const [guides, setGuides] = useState(null)
  useEffect(() => { api.get('/api/guides').then(setGuides).catch(() => setGuides([])) }, [])
  if (!guides) return <Loading />
  const current = guides.find((g) => g.slug === route.sub) || guides[0]
  return (
    <div className="page fill">
      <PageHead idx={7} crumb="guides" title="Set it" accent="up."
        lead="Everything you need to run clipped with your own free keys. Each guide takes a few minutes." />
      <div className="side-layout">
        <nav className="subnav pane">
          {guides.map((g, i) => (
            <a key={g.slug} href={`#/guides/${g.slug}`} className={current?.slug === g.slug ? 'active' : ''} style={{ '--r': `${i % 2 ? 5 : -5}deg` }}>
              <span className="subnav-stk"><Sticker name={STK[g.slug] || 'guides'} /></span>
              <span>{g.title.replace(/^Optional:\s*/i, '')}</span>
            </a>
          ))}
        </nav>
        <div className="pane">
          <article key={current?.slug} className="card glow prose" onClick={(e) => {
            const a = e.target.closest('a')
            if (a && /^https?:/.test(a.getAttribute('href') || '')) { a.target = '_blank'; a.rel = 'noreferrer' }
          }} dangerouslySetInnerHTML={{ __html: current ? marked.parse(current.markdown) : '' }} />
        </div>
      </div>
    </div>
  )
}
