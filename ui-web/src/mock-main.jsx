import React from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './mockapp/mock.css'
import MockApp from './mockapp/MockApp.jsx'

document.documentElement.dataset.theme = 'light'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <MockApp />
  </React.StrictMode>,
)
