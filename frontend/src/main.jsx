import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/geist-sans/300.css'
import '@fontsource/geist-sans/400.css'
import '@fontsource/geist-sans/500.css'
import '@fontsource/geist-sans/600.css'
import '@fontsource/geist-mono/400.css'
import '@fontsource/geist-mono/500.css'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import '@fontsource/inter/900.css' // captions: the engine state and the caption preview use the burned-in font
import './styles.css'
import App from './App.jsx'
import { bootFx } from './fx.js'
import { startAppHeartbeat } from './api.js'

createRoot(document.getElementById('root')).render(<App />)
bootFx()
startAppHeartbeat()
