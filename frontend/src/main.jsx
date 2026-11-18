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
import '@fontsource/inter/900.css' // caption preview only (matches the burned-in caption font)
import 'lenis/dist/lenis.css'
import './styles.css'
import App from './App.jsx'
import { bootMotion } from './fx/motion.js'

createRoot(document.getElementById('root')).render(<App />)
bootMotion()
