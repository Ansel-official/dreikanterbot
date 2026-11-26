import { useCallback, useEffect, useRef, useState } from 'react'
import { getApiBase } from '../api/client'

function websocketUrl(token) {
  const base = getApiBase()
  const parsed = new URL(base, window.location.href)
  const protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
  const path = `${parsed.pathname.replace(/\/api\/?$/, '').replace(/\/$/, '')}/ws/chat`
  return `${protocol}//${parsed.host}${path}?token=${encodeURIComponent(token)}`
}

/**
 * WebSocket 连接管理：自动重连、心跳应答、断线重连事件。
 * 发送失败返回 false，由界面提示用户；不会静默丢消息。
 */
export function useChatSocket({ token, onEvent }) {
  const [status, setStatus] = useState('connecting')
  const socketRef = useRef(null)
  const handlerRef = useRef(onEvent)

  useEffect(() => {
    handlerRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (!token) {
      setStatus('unauthorized')
      return undefined
    }

    let disposed = false
    let retry = 0
    let timer = null
    let everConnected = false
    let socket = null

    const url = websocketUrl(token)

    const scheduleReconnect = () => {
      if (disposed) return
      retry += 1
      const delay = Math.min(1000 * 2 ** Math.min(retry - 1, 4), 15000)
      const jitter = Math.floor(Math.random() * 400)
      timer = setTimeout(open, delay + jitter)
    }

    const open = () => {
      if (disposed) return
      setStatus((current) => (current === 'connected' ? current : 'connecting'))
      try {
        socket = new WebSocket(url)
      } catch {
        setStatus('disconnected')
        scheduleReconnect()
        return
      }
      socketRef.current = socket

      socket.onopen = () => {
        if (disposed) {
          socket.close()
          return
        }
        retry = 0
        setStatus('connected')
        if (everConnected) handlerRef.current?.({ type: 'socket_reconnected' })
        everConnected = true
      }

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data?.type === 'ping') {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'pong' }))
            }
            return
          }
          handlerRef.current?.(data)
        } catch (error) {
          console.warn('无法解析 WebSocket 消息', error)
        }
      }

      socket.onclose = (event) => {
        socketRef.current = null
        if (disposed) return
        if (event.code === 4401 || event.code === 4403) {
          setStatus('unauthorized')
          handlerRef.current?.({ type: 'socket_unauthorized' })
          return
        }
        setStatus('disconnected')
        scheduleReconnect()
      }

      socket.onerror = () => {
        // onclose 会统一处理重连
      }
    }

    const onOnline = () => {
      if (disposed) return
      if (!socket || socket.readyState === WebSocket.CLOSED) {
        clearTimeout(timer)
        retry = 0
        open()
      }
    }

    open()
    window.addEventListener('online', onOnline)

    return () => {
      disposed = true
      window.removeEventListener('online', onOnline)
      clearTimeout(timer)
      if (socket) {
        socket.onclose = null
        socket.close(1000, 'component unmounted')
      }
      socketRef.current = null
    }
  }, [token])

  const send = useCallback((payload) => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    try {
      socket.send(JSON.stringify(payload))
      return true
    } catch {
      return false
    }
  }, [])

  return { status, send }
}
