import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { registerServiceWorker } from './registerSW'
import './styles.css'
import './v3.css'

// 在首屏渲染前应用主题，避免闪白/闪黑
try {
  const saved = localStorage.getItem('deepseek_chat_theme')
  const theme =
    saved === 'light' || saved === 'dark'
      ? saved
      : window.matchMedia?.('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
  document.documentElement.dataset.theme = theme
} catch {
  document.documentElement.dataset.theme = 'light'
}

registerServiceWorker()

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
