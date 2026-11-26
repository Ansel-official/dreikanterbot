import axios from 'axios'

const TOKEN_KEY = 'deepseek_chat_token'
const API_BASE_KEY = 'dreikanterbot_api_base'

export function getApiBase() {
  try {
    const saved = localStorage.getItem(API_BASE_KEY)
    if (saved) return saved.replace(/\/$/, '')
  } catch {
    /* ignore */
  }
  return (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')
}

export function setApiBase(value) {
  const base = String(value || '').trim().replace(/\/$/, '')
  try {
    if (base) localStorage.setItem(API_BASE_KEY, base)
    else localStorage.removeItem(API_BASE_KEY)
  } catch {
    /* ignore */
  }
  api.defaults.baseURL = getApiBase()
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 隐私模式下 localStorage 可能不可用 */
  }
}

export function clearToken() {
  setToken(null)
}

let unauthorizedHandler = null
export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

const api = axios.create({
  baseURL: getApiBase(),
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const url = error?.config?.url || ''
    if (status === 401 && !url.includes('/auth/login') && !url.includes('/auth/bootstrap')) {
      clearToken()
      if (unauthorizedHandler) unauthorizedHandler()
    }
    return Promise.reject(error)
  }
)

export function errorMessage(error, fallback = '操作失败，请稍后重试') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const text = detail
      .map((item) => item?.msg || item?.message || '')
      .filter(Boolean)
      .join('；')
    if (text) return text
  }
  if (detail && typeof detail.message === 'string') return detail.message
  if (error?.code === 'ECONNABORTED') return '请求超时，请检查网络后重试'
  if (!error?.response && error?.message) return '无法连接服务器，请检查网络或稍后重试'
  return fallback
}

export function filenameFromDisposition(disposition, fallback) {
  if (!disposition) return fallback
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].replace(/["']/g, ''))
    } catch {
      /* ignore */
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(disposition)
  return ascii ? ascii[1] : fallback
}

export async function downloadFromApi(url, fallbackName) {
  const response = await api.get(url, { responseType: 'blob', timeout: 120000 })
  const name = filenameFromDisposition(response.headers['content-disposition'], fallbackName)
  const blobUrl = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(blobUrl), 4000)
}

export default api
