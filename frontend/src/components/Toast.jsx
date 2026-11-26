import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import Icon from './Icons'

const ToastContext = createContext(null)

const ICON_BY_TYPE = {
  success: 'check',
  error: 'alert',
  info: 'info',
  warning: 'alert',
}

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const timersRef = useRef(new Map())
  const sequenceRef = useRef(0)

  const dismiss = useCallback((id) => {
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const push = useCallback(
    (message, type = 'info') => {
      if (!message) return
      const id = ++sequenceRef.current
      setItems((current) => [...current.slice(-3), { id, message, type }])
      const timer = setTimeout(() => {
        setItems((current) => current.filter((item) => item.id !== id))
        timersRef.current.delete(id)
      }, type === 'error' ? 6000 : 4000)
      timersRef.current.set(id, timer)
      return id
    },
    []
  )

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      timers.forEach((timer) => clearTimeout(timer))
      timers.clear()
    }
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast toast-${item.type}`}>
            <span className="toast-icon">
              <Icon name={ICON_BY_TYPE[item.type] || 'sparkles'} size={17} />
            </span>
            <span className="toast-text">{item.message}</span>
            <button className="toast-close" onClick={() => dismiss(item.id)} aria-label="关闭提示">
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast 必须在 ToastProvider 内使用')
  return context
}
