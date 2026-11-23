export function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return
  if (import.meta.env.DEV) return

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { updateViaCache: 'none' })
      .then((registration) => {
        // 有新版本时提示刷新；不强制打断正在进行的对话
        registration.addEventListener('updatefound', () => {
          const worker = registration.installing
          if (!worker) return
          worker.addEventListener('statechange', () => {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) {
              window.dispatchEvent(new CustomEvent('dc:sw-updated'))
            }
          })
        })
      })
      .catch((error) => {
        console.warn('Service Worker 注册失败', error)
      })
  })
}
