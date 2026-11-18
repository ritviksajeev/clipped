import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useApp } from '../App.jsx'
import { AutoWarning, Field, NumberInput, Select, TagInput, Toggle } from '../components/ui.jsx'

const SECTIONS = [
  ['connections', 'Connections'], ['mode', 'Mode & schedule'], ['safety', 'Safety'], ['captions', 'Captions'],
  ['layout', 'Layout & hooks'], ['titles', 'Titles & AI'], ['youtube', 'YouTube uploads'], ['advanced', 'Advanced'],
  ['about', 'About'],
]
const INTERVALS = [[30, '30 minutes'], [120, '2 hours'], [360, '6 hours'], [1440, '24 hours']]

function SecretField({ name, info, onSaved, placeholder, storage }) {
  const { notify } = useApp()
  const [value, setValue] = useState('')
  if (!info) return null
  return (
    <Field label={info.label} hint={info.set ? `Saved (${info.hint}). ${storage || ''}` : 'Not set'}>
      <div className="row gap">
        <input type="password" autoComplete="off" spellCheck={false} placeholder={info.set ? 'Enter a new value to replace' : placeholder}
          value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn small" disabled={!value} onClick={async () => {
          try { await api.put(`/api/secrets/${name}`, { value }); setValue(''); onSaved(); notify(`${info.label} saved`) } catch (e) { notify(e.message, 'error') }
        }}>Save</button>
        {info.set && <button className="btn ghost small" onClick={async () => { await api.del(`/api/secrets/${name}`); onSaved() }}>Clear</button>}
      </div>
    </Field>
  )
}

function Connections() {
  const { notify, route, refreshStatus } = useApp()
  const [secrets, setSecrets] = useState(null)
  const [yt, setYt] = useState(null)
  const [json, setJson] = useState('')
  const load = async () => {
    setSecrets(await api.get('/api/secrets'))
    setYt(await api.get('/api/youtube/status'))
  }
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (route.params.get('youtube') === 'connected') notify('YouTube connected')
    if (route.params.get('youtube_error')) notify(`YouTube connection failed: ${route.params.get('youtube_error')}`, 'error')
  }, [])
  if (!secrets) return <div className="muted">Loading…</div>
  const s = secrets.secrets
  const storage = secrets.os_keyring ? 'Stored in your OS keychain.' : 'Stored in an owner-only file.'
  return (
    <>
      <section className="card">
        <h2>Twitch</h2>
        <p className="muted small">Your own free Twitch developer app. <a href="#/guides/twitch">How to get these →</a></p>
        <SecretField name="twitch_client_id" info={s.twitch_client_id} onSaved={load} storage={storage} placeholder="Client ID" />
        <SecretField name="twitch_client_secret" info={s.twitch_client_secret} onSaved={load} storage={storage} placeholder="Client Secret" />
        <button className="btn" disabled={!s.twitch_client_id.set || !s.twitch_client_secret.set} onClick={async () => {
          try { await api.post('/api/twitch/test'); notify('Twitch connected ✓'); refreshStatus() } catch (e) { notify(e.message, 'error') }
        }}>Test Twitch</button>
      </section>

      <section className="card">
        <h2>YouTube</h2>
        <p className="muted small">Uses an OAuth client in your own Google Cloud project. <a href="#/guides/youtube">Step-by-step guide →</a></p>
        <Field label="Paste client JSON" hint="Paste the client_secret_….json you downloaded from Google Cloud (Desktop app client)." wide>
          <textarea rows={3} value={json} onChange={(e) => setJson(e.target.value)} placeholder='{"installed":{"client_id":"…","client_secret":"…"}}' />
        </Field>
        <button className="btn small" disabled={!json.trim()} onClick={async () => {
          try { const r = await api.post('/api/secrets/google-client-json', { json_text: json }); setJson(''); load(); notify(`Google ${r.client_type} client saved`) } catch (e) { notify(e.message, 'error') }
        }}>Save client JSON</button>
        <details className="small"><summary>…or enter the Client ID and Secret separately</summary>
          <SecretField name="google_client_id" info={s.google_client_id} onSaved={load} storage={storage} placeholder="….apps.googleusercontent.com" />
          <SecretField name="google_client_secret" info={s.google_client_secret} onSaved={load} storage={storage} placeholder="GOCSPX-…" />
        </details>
        <div className="yt-connect">
          {yt?.connected ? (
            <>
              <div>Connected to <strong>{yt.channel?.title || 'your channel'}</strong></div>
              {yt.auth_problem && <div className="banner error small">{yt.auth_problem}</div>}
              <button className="btn" onClick={async () => { const r = await api.get('/api/youtube/connect'); window.location.href = r.url }}>Reconnect</button>
              <button className="btn ghost" onClick={async () => { await api.post('/api/youtube/disconnect'); load(); refreshStatus() }}>Disconnect</button>
            </>
          ) : (
            <button className="btn primary" disabled={!yt?.client_configured} onClick={async () => {
              try { const r = await api.get('/api/youtube/connect'); window.location.href = r.url } catch (e) { notify(e.message, 'error') }
            }}>Connect YouTube</button>
          )}
        </div>
        <p className="muted small">Google will warn that the app is unverified. It's your own app: click <em>Advanced → Go to ClipPilot</em>.
          Uploads may be locked to private until your project passes YouTube's free API audit (<a href="#/guides/youtube">details</a>).</p>
      </section>

      <section className="card">
        <h2>AI title generation (optional)</h2>
        <p className="muted small">Leave empty to use the free templates. <a href="#/guides/ai-titles">Guide →</a></p>
        <SecretField name="anthropic_api_key" info={s.anthropic_api_key} onSaved={load} storage={storage} placeholder="sk-ant-…" />
        <SecretField name="openai_api_key" info={s.openai_api_key} onSaved={load} storage={storage} placeholder="sk-…" />
      </section>
      <p className="muted small">Secret storage: {secrets.backend}{!secrets.os_keyring && ' (no OS keychain detected, using an owner-only file)'}</p>
    </>
  )
}

function CaptionPreview({ c }) {
  const words = ['THIS', 'IS', 'INSANE']
  const scale = 0.25
  const top = c.position === 'top' ? `${((c.margin_top + 300 + c.vertical_offset) / 1920) * 100}%`
    : c.position === 'bottom' ? `${((1920 - c.margin_bottom + c.vertical_offset) / 1920) * 100}%` : `${((1920 * 0.6 + c.vertical_offset) / 1920) * 100}%`
  const transform = c.position === 'bottom' ? 'translate(-50%, -100%)' : c.position === 'top' ? 'translate(-50%, 0)' : 'translate(-50%, -50%)'
  const stroke = `${Math.max(1, c.outline * scale)}px`
  return (
    <div className="phone caption-preview" aria-label="Caption preview">
      <div className="fake-game" />
      <div className="cap" style={{ top, transform, fontSize: `${c.font_size * scale}px`, WebkitTextStroke: `${stroke} ${c.outline_color}`,
        color: c.primary_color, textShadow: `0 ${c.shadow * scale}px ${c.shadow * scale}px #0008` }}>
        {words.map((w, i) => {
          const t = c.uppercase ? w : w.toLowerCase()
          return (
            <React.Fragment key={w}>
              {i > 0 && ' '}
              <span style={i === 1 ? { color: c.highlight_color, display: 'inline-block', transform: `scale(${c.highlight_scale / 100})` } : {}}>{t}</span>
            </React.Fragment>
          )
        })}
      </div>
      <div className="safe-zone" title="YouTube Shorts UI covers this area" />
    </div>
  )
}

export default function Settings() {
  const { notify, refreshStatus, route } = useApp()
  const [data, setData] = useState(null)
  const [saved, setSaved] = useState(null)
  const [ack, setAck] = useState(false)
  const [about, setAbout] = useState(null)
  const section = SECTIONS.some(([k]) => k === route.sub) ? route.sub : 'connections'

  useEffect(() => {
    api.get('/api/settings').then((r) => { setData(r.settings); setSaved(r.settings); setAck(r.auto_warning_acknowledged) })
    api.get('/api/about').then(setAbout).catch(() => {})
  }, [])
  const dirty = useMemo(() => JSON.stringify(data) !== JSON.stringify(saved), [data, saved])
  const [warn, setWarn] = useState(null)
  if (!data) return <div className="muted">Loading…</div>

  const upd = (path, value) => {
    setData((prev) => {
      const next = structuredClone(prev)
      let o = next
      const keys = path.split('.')
      keys.slice(0, -1).forEach((k) => { o = o[k] })
      o[keys[keys.length - 1]] = value
      return next
    })
  }
  const bind = (path) => (v) => upd(path, v)
  const get = (path) => path.split('.').reduce((o, k) => o?.[k], data)
  const save = async (payload = data) => {
    try {
      const r = await api.put('/api/settings', payload)
      setData(r.settings); setSaved(r.settings); setAck(r.auto_warning_acknowledged)
      notify('Settings saved'); refreshStatus()
    } catch (e) {
      if (e.status === 409) setWarn(() => () => save(payload))
      else notify(e.message, 'error')
    }
  }
  const sched = data.schedule
  const isCustom = !INTERVALS.some(([v]) => v === sched.upload_interval_minutes)

  return (
    <div className="page settings">
      <header className="page-head"><h1>Settings</h1></header>
      <div className="settings-layout">
        <nav className="subnav">
          {SECTIONS.map(([k, l]) => <a key={k} href={`#/settings/${k}`} className={section === k ? 'active' : ''}>{l}</a>)}
        </nav>
        <div className="settings-body">
          {section === 'connections' && <Connections />}

          {section === 'mode' && <>
            <section className="card">
              <h2>Mode</h2>
              <div className="mode-switch">
                {[['manual', 'Manual approval', 'Every rendered clip waits in the review queue. Nothing uploads until you approve it.'],
                  ['auto', 'Auto', 'ClipPilot selects, renders and uploads on its own, following your schedule and safety rules.']].map(([v, l, d]) => (
                  <button key={v} className={`mode-option ${data.mode === v ? 'active' : ''}`} onClick={() => {
                    if (v === 'auto' && !ack) setWarn(() => async () => { setAck(true); upd('mode', 'auto') })
                    else upd('mode', v)
                  }}>
                    <strong>{l}</strong><span className="muted small">{d}</span>
                  </button>
                ))}
              </div>
              <p className="muted small">Each category can override this in Categories.</p>
            </section>
            <section className="card">
              <h2>Upload schedule</h2>
              <div className="grid3">
                <Field label="Interval between auto uploads">
                  <Select value={isCustom ? 'custom' : String(sched.upload_interval_minutes)} onChange={(v) => upd('schedule.upload_interval_minutes', v === 'custom' ? 90 : Number(v))}
                    options={[...INTERVALS.map(([v, l]) => [String(v), l]), ['custom', 'Custom…']]} />
                </Field>
                {isCustom && <Field label="Custom interval (minutes)"><NumberInput value={sched.upload_interval_minutes} min={10} max={10080} onChange={bind('schedule.upload_interval_minutes')} /></Field>}
                <Field label="Max uploads per day"><NumberInput value={sched.max_uploads_per_day} min={1} max={50} onChange={bind('schedule.max_uploads_per_day')} /></Field>
                <Field label="Minimum gap between any uploads (min)" hint="Anti-spam floor, also applies to manual 'upload now'">
                  <NumberInput value={sched.min_gap_minutes} min={5} max={1440} onChange={bind('schedule.min_gap_minutes')} />
                </Field>
                <Field label="Check Twitch every (min)"><NumberInput value={sched.fetch_interval_minutes} min={5} max={1440} onChange={bind('schedule.fetch_interval_minutes')} /></Field>
                <Field label="Rendered clips to keep ready (auto)"><NumberInput value={sched.render_ahead} min={1} max={20} onChange={bind('schedule.render_ahead')} /></Field>
              </div>
              <Toggle checked={sched.quiet_hours.enabled} onChange={bind('schedule.quiet_hours.enabled')} label="Quiet hours" hint="No uploads during this window (your local time)" />
              {sched.quiet_hours.enabled && <div className="grid3">
                <Field label="From"><input type="time" value={sched.quiet_hours.start} onChange={(e) => upd('schedule.quiet_hours.start', e.target.value)} /></Field>
                <Field label="Until"><input type="time" value={sched.quiet_hours.end} onChange={(e) => upd('schedule.quiet_hours.end', e.target.value)} /></Field>
              </div>}
              <Field label="Pause uploads until" hint="Leave empty to run normally">
                <div className="row gap">
                  <input type="datetime-local" value={sched.pause_until ? new Date(new Date(sched.pause_until).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''}
                    onChange={(e) => upd('schedule.pause_until', e.target.value ? new Date(e.target.value).toISOString() : null)} />
                  {sched.pause_until && <button className="btn ghost small" onClick={() => upd('schedule.pause_until', null)}>Clear</button>}
                </div>
              </Field>
            </section>
          </>}

          {section === 'safety' && <section className="card">
            <h2>Safety</h2>
            <Toggle checked={data.approved_streamers_only} onChange={bind('approved_streamers_only')} label="Approved streamers only (Auto mode)"
              hint="Auto mode only uploads clips from streamers on this list or a category allowlist. Everything else goes to the review queue." />
            <Field label="Approved streamers" hint="Twitch logins of streamers who've allowed you to post their clips" wide>
              <TagInput value={data.approved_streamers} onChange={bind('approved_streamers')} placeholder="add a login, Enter" />
            </Field>
            <p className="muted small">Credit is always on: every upload names the streamer and links their channel and the original clip. See <a href="#/guides/safety">Auto mode & staying safe</a>.</p>
          </section>}

          {section === 'captions' && <section className="card">
            <h2>Captions <span className="pill ok">always on</span></h2>
            <div className="caption-layout">
              <div className="grid2">
                <Field label="Font"><Select value={data.captions.font} onChange={bind('captions.font')} options={['Inter Black', 'Inter ExtraBold', 'Inter Bold']} /></Field>
                <Field label="Size"><input type="range" min={50} max={140} value={data.captions.font_size} onChange={(e) => upd('captions.font_size', Number(e.target.value))} /></Field>
                <Field label="Text color"><input type="color" value={data.captions.primary_color} onChange={(e) => upd('captions.primary_color', e.target.value.toUpperCase())} /></Field>
                <Field label="Current-word highlight"><input type="color" value={data.captions.highlight_color} onChange={(e) => upd('captions.highlight_color', e.target.value.toUpperCase())} /></Field>
                <Field label="Outline color"><input type="color" value={data.captions.outline_color} onChange={(e) => upd('captions.outline_color', e.target.value.toUpperCase())} /></Field>
                <Field label="Outline thickness"><input type="range" min={0} max={14} value={data.captions.outline} onChange={(e) => upd('captions.outline', Number(e.target.value))} /></Field>
                <Field label="Position"><Select value={data.captions.position} onChange={bind('captions.position')} options={[['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']]} /></Field>
                <Field label="Nudge up/down (px)"><input type="range" min={-400} max={400} step={10} value={data.captions.vertical_offset} onChange={(e) => upd('captions.vertical_offset', Number(e.target.value))} /></Field>
                <Field label="Words per caption"><NumberInput value={data.captions.max_words} min={1} max={8} onChange={bind('captions.max_words')} /></Field>
                <Field label="Animation"><Select value={data.captions.animation} onChange={bind('captions.animation')} options={[['pop', 'Pop current word'], ['none', 'Color only']]} /></Field>
              </div>
              <div>
                <CaptionPreview c={data.captions} />
                <Toggle checked={data.captions.uppercase} onChange={bind('captions.uppercase')} label="UPPERCASE" />
              </div>
            </div>
            <p className="muted small">Captions stay inside the Shorts safe area (the player's buttons and title cover the right edge and bottom).</p>
          </section>}

          {section === 'layout' && <>
            <section className="card">
              <h2>9:16 layout</h2>
              <div className="grid3">
                <Field label="Default layout"><Select value={data.reframe.mode} onChange={bind('reframe.mode')}
                  options={[['blur', 'Blurred background fill'], ['split', 'Facecam + gameplay split'], ['crop', 'Center crop']]} /></Field>
                <Field label="Gameplay zoom (blur layout)"><input type="range" min={1} max={1.6} step={0.02} value={data.reframe.zoom} onChange={(e) => upd('reframe.zoom', Number(e.target.value))} /></Field>
                <Field label="Facecam height (split)"><input type="range" min={0.2} max={0.6} step={0.02} value={data.reframe.facecam_height} onChange={(e) => upd('reframe.facecam_height', Number(e.target.value))} /></Field>
              </div>
              <p className="muted small">The split layout needs to know where each streamer's facecam is. Set that per streamer in Categories → Settings. Others fall back to the blurred fill.</p>
            </section>
            <section className="card">
              <h2>Hook</h2>
              <div className="grid3">
                <Field label="Opening"><Select value={data.hook.mode} onChange={bind('hook.mode')}
                  options={[['teaser', 'Flash-forward to the best moment'], ['trim', 'Trim dead air only'], ['off', 'Leave the clip as is']]} /></Field>
                <Field label="Hook text seconds"><NumberInput value={data.hook.hook_seconds} min={0.5} max={5} step={0.5} onChange={bind('hook.hook_seconds')} /></Field>
                <Field label="Cut silences longer than (s)"><NumberInput value={data.hook.max_silence} min={0.3} max={5} step={0.1} onChange={bind('hook.max_silence')} /></Field>
              </div>
              <Toggle checked={data.hook.hook_text} onChange={bind('hook.hook_text')} label="Show hook text for the first seconds" />
              <Toggle checked={data.hook.trim_dead_air} onChange={bind('hook.trim_dead_air')} label="Trim dead air" />
            </section>
            <section className="card">
              <h2>Intro / outro / commentary</h2>
              <p className="muted small">Optional, to make each Short more than a repost. Use a short video or an image (shown for 2 seconds).</p>
              {['intro_path', 'outro_path'].map((k) => (
                <Field key={k} label={k === 'intro_path' ? 'Intro' : 'Outro'}>
                  <div className="row gap">
                    <span className="muted small ellipsis">{data.render[k] ? data.render[k].split(/[\\/]/).pop() : 'none'}</span>
                    <label className="btn small">Choose file<input type="file" hidden accept="video/*,image/*" onChange={async (e) => {
                      if (!e.target.files[0]) return
                      try { const r = await api.upload('/api/assets', e.target.files[0]); upd(`render.${k}`, r.path) } catch (err) { notify(err.message, 'error') }
                    }} /></label>
                    {data.render[k] && <button className="btn ghost small" onClick={() => upd(`render.${k}`, '')}>Remove</button>}
                  </div>
                </Field>
              ))}
              <Field label="Default commentary line" hint="Shown on screen after the hook and added to the description. Editable per clip." wide>
                <input value={data.commentary_default} maxLength={200} onChange={(e) => upd('commentary_default', e.target.value)} />
              </Field>
            </section>
          </>}

          {section === 'titles' && <section className="card">
            <h2>Titles, descriptions & hashtags</h2>
            <div className="grid3">
              <Field label="Title generator"><Select value={data.metadata.provider} onChange={bind('metadata.provider')}
                options={[['template', 'Free templates'], ['anthropic', 'Anthropic (your key)'], ['openai', 'OpenAI (your key)']]} /></Field>
              {data.metadata.provider === 'anthropic' && <Field label="Anthropic model"><input value={data.metadata.anthropic_model} onChange={(e) => upd('metadata.anthropic_model', e.target.value)} /></Field>}
              {data.metadata.provider === 'openai' && <Field label="OpenAI model"><input value={data.metadata.openai_model} onChange={(e) => upd('metadata.openai_model', e.target.value)} /></Field>}
              <Field label="Variants per clip"><Select value={String(data.metadata.variants)} onChange={(v) => upd('metadata.variants', Number(v))} options={['1', '2', '3']} /></Field>
            </div>
            <Toggle checked={data.metadata.credit_in_title} onChange={bind('metadata.credit_in_title')} label="Put the streamer's name in the title"
              hint="The description always credits the streamer and links the original clip." />
            <Field label="Default hashtags" wide><TagInput value={data.metadata.default_hashtags} onChange={bind('metadata.default_hashtags')} prefix="#" /></Field>
            <Field label="Description footer" hint="Added to every description (e.g. your socials)" wide>
              <textarea rows={2} value={data.metadata.description_footer} onChange={(e) => upd('metadata.description_footer', e.target.value)} />
            </Field>
          </section>}

          {section === 'youtube' && <section className="card">
            <h2>YouTube upload settings</h2>
            <div className="grid3">
              <Field label="Privacy"><Select value={data.youtube.privacy_status} onChange={bind('youtube.privacy_status')} options={['public', 'unlisted', 'private']} /></Field>
              <Field label="YouTube category"><Select value={data.youtube.category_id} onChange={bind('youtube.category_id')}
                options={[['20', 'Gaming'], ['24', 'Entertainment'], ['23', 'Comedy'], ['17', 'Sports'], ['22', 'People & Blogs']]} /></Field>
            </div>
            <Toggle checked={data.youtube.made_for_kids} onChange={bind('youtube.made_for_kids')} label="Made for kids" hint="Required declaration. Most gaming clips are not made for kids." />
            <Toggle checked={data.youtube.set_thumbnail} onChange={bind('youtube.set_thumbnail')} label="Upload custom thumbnail" hint="Needs a phone-verified channel" />
            <Toggle checked={data.youtube.contains_synthetic_media} onChange={bind('youtube.contains_synthetic_media')} label="Declare altered or synthetic content" />
          </section>}

          {section === 'advanced' && <>
            <section className="card">
              <h2>Clip selection</h2>
              <div className="grid3">
                <Field label="Ideal length from (s)"><NumberInput value={data.selection.ideal_min_seconds} onChange={bind('selection.ideal_min_seconds')} /></Field>
                <Field label="Ideal length to (s)"><NumberInput value={data.selection.ideal_max_seconds} onChange={bind('selection.ideal_max_seconds')} /></Field>
                <Field label="Skip clips longer than (s)"><NumberInput value={data.selection.max_seconds} onChange={bind('selection.max_seconds')} /></Field>
                <Field label="Skip clips quieter than (dBFS)"><NumberInput value={data.selection.min_mean_db} onChange={bind('selection.min_mean_db')} /></Field>
                <Field label="Too similar to a recent upload above"><NumberInput value={data.selection.similarity_threshold} step={0.05} min={0.1} max={1} onChange={bind('selection.similarity_threshold')} /></Field>
              </div>
              <Field label="Hype keywords" wide><TagInput value={data.selection.hype_keywords} onChange={bind('selection.hype_keywords')} /></Field>
            </section>
            <section className="card">
              <h2>Optimizer</h2>
              <Toggle checked={data.optimizer.enabled} onChange={bind('optimizer.enabled')} label="Learn from YouTube Analytics" hint="Favor the best title styles and posting hours, and spread uploads across streamers." />
              <div className="grid3">
                <Field label="Exploration rate"><NumberInput value={data.optimizer.explore_rate} step={0.05} min={0} max={1} onChange={bind('optimizer.explore_rate')} /></Field>
                <Field label="Uploads needed before learning titles"><NumberInput value={data.optimizer.min_samples_for_styles} onChange={bind('optimizer.min_samples_for_styles')} /></Field>
                <Field label="Uploads needed before learning times"><NumberInput value={data.optimizer.min_samples_for_timing} onChange={bind('optimizer.min_samples_for_timing')} /></Field>
              </div>
            </section>
            <section className="card">
              <h2>Transcription (runs on this computer)</h2>
              <div className="grid3">
                <Field label="Whisper model" hint="Bigger = more accurate, slower. Downloaded once."><Select value={data.whisper.model_size} onChange={bind('whisper.model_size')}
                  options={[['tiny', 'tiny (fastest)'], ['base', 'base (default)'], ['small', 'small'], ['medium', 'medium'], ['distil-large-v3', 'distil-large-v3'], ['large-v3', 'large-v3 (best)']]} /></Field>
                <Field label="Device"><Select value={data.whisper.device} onChange={bind('whisper.device')} options={[['auto', 'Auto'], ['cpu', 'CPU'], ['cuda', 'NVIDIA GPU']]} /></Field>
                <Field label="Language" hint="Blank = auto-detect"><input value={data.whisper.language} maxLength={5} onChange={(e) => upd('whisper.language', e.target.value.trim())} /></Field>
              </div>
            </section>
            <section className="card">
              <h2>Render quality</h2>
              <div className="grid3">
                <Field label="Quality (CRF, lower = better)"><NumberInput value={data.render.crf} min={14} max={32} onChange={bind('render.crf')} /></Field>
                <Field label="Speed preset"><Select value={data.render.preset} onChange={bind('render.preset')} options={['ultrafast', 'veryfast', 'faster', 'fast', 'medium', 'slow']} /></Field>
              </div>
              <Toggle checked={data.render.loudnorm} onChange={bind('render.loudnorm')} label="Normalize loudness (-14 LUFS)" />
            </section>
          </>}

          {section === 'about' && <section className="card">
            <h2>About</h2>
            {about ? <dl className="about">
              <dt>Version</dt><dd>{about.version}</dd>
              <dt>Data folder</dt><dd><code>{about.data_dir}</code></dd>
              <dt>ffmpeg</dt><dd>{about.ffmpeg || 'not found'} {about.libass ? '· libass ✓' : '· libass missing!'}</dd>
              <dt>Secret storage</dt><dd>{about.secret_storage}</dd>
              <dt>Server</dt><dd>bound to this computer only. No ClipPilot servers exist; nothing is sent anywhere except Twitch, Google, and your chosen AI provider.</dd>
            </dl> : <div className="muted">Loading…</div>}
          </section>}
        </div>
      </div>
      {dirty && section !== 'connections' && section !== 'about' && (
        <div className="savebar">
          <span>Unsaved changes</span>
          <button className="btn ghost" onClick={() => setData(saved)}>Discard</button>
          <button className="btn primary" onClick={() => save()}>Save settings</button>
        </div>
      )}
      {warn && <AutoWarning onCancel={() => setWarn(null)} onAccept={async () => { const fn = warn; setWarn(null); setAck(true); await fn() }} />}
    </div>
  )
}
