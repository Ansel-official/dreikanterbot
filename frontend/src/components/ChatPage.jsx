import { useCallback, useEffect, useRef, useState } from 'react'
import api, { downloadFromApi, errorMessage } from '../api/client'
import { useAuth } from '../hooks/useAuth'
import { useChatSocket } from '../hooks/useChatSocket'
import { useToast } from './Toast'
import { formatRelativeTime, makeClientId } from '../utils'
import Sidebar from './Sidebar'
import MessageList from './MessageList'
import Composer from './Composer'
import ConnectionBadge from './ConnectionBadge'
import SettingsPanel from './SettingsPanel'
import AdminPanel from './AdminPanel'
import ConfirmDialog from './ConfirmDialog'
import Icon from './Icons'

function mergeSessions(existing, incoming) {
  const map = new Map(existing.map((item) => [item.id, item]))
  incoming.forEach((item) => map.set(item.id, item))
  return [...map.values()].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  )
}

function QuotaChip({ quota }) {
  if (!quota) return null
  const unlimited = quota.limit == null
  const low = !unlimited && quota.remaining <= 10
  return (
    <div
      className={`quota-chip ${low ? 'low' : ''}`}
      title={
        unlimited
          ? '管理员账号不限制每日调用次数'
          : `今日已用 ${quota.used} 次，剩余 ${quota.remaining} 次`
      }
    >
      <Icon name="barChart" size={14} />
      <span>{unlimited ? '不限量' : `剩余 ${quota.remaining}`}</span>
    </div>
  )
}

export default function ChatPage({ theme, onToggleTheme }) {
  const { user, token, logout } = useAuth()
  const toast = useToast()

  const [sessions, setSessions] = useState([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [hasMoreSessions, setHasMoreSessions] = useState(false)
  const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false)
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [nextBefore, setNextBefore] = useState(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [quota, setQuota] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState('')

  const activeSessionRef = useRef(null)
  const messagesRef = useRef([])
  const streamingRef = useRef(false)
  const pendingRef = useRef(null)
  const aiWarnedRef = useRef(false)
  const manualNavRef = useRef(false)

  useEffect(() => {
    activeSessionRef.current = activeSessionId
  }, [activeSessionId])
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])
  useEffect(() => {
    streamingRef.current = streaming
  }, [streaming])

  const activeSession = sessions.find((item) => item.id === activeSessionId)
  const title = activeSession?.title || '新对话'

  const refreshSessions = useCallback(
    async (silent = true) => {
      try {
        const response = await api.get('/sessions', { params: { limit: 100 } })
        setSessions((current) => mergeSessions(current, response.data))
        if (response.data.length < 100) setHasMoreSessions(false)
        return response.data
      } catch (error) {
        if (!silent) toast(errorMessage(error, '加载会话列表失败'), 'error')
        return null
      }
    },
    [toast]
  )

  const loadMoreSessions = useCallback(async () => {
    if (sessionsLoadingMore || !hasMoreSessions) return
    setSessionsLoadingMore(true)
    try {
      const response = await api.get('/sessions', {
        params: { limit: 100, offset: sessions.length },
      })
      const items = response.data || []
      setSessions((current) => mergeSessions(current, items))
      setHasMoreSessions(items.length === 100)
    } catch (error) {
      toast(errorMessage(error, '加载更多会话失败'), 'error')
    } finally {
      setSessionsLoadingMore(false)
    }
  }, [hasMoreSessions, sessions.length, sessionsLoadingMore, toast])

  const resyncSession = useCallback(
    async (sessionId) => {
      try {
        const response = await api.get(`/sessions/${sessionId}/messages`, {
          params: { limit: 100 },
        })
        if (activeSessionRef.current !== sessionId) return
        const items = response.data.items || []
        const pending = pendingRef.current
        if (pending && !pending.acked) {
          const delivered = items.some(
            (item) => item.role === 'user' && item.content === pending.content
          )
          if (!delivered) {
            toast('连接曾中断，最近一条消息可能未发送成功，请检查后重试', 'warning')
          }
        }
        pendingRef.current = null
        setMessages(items)
        setHasMore(Boolean(response.data.has_more))
        setNextBefore(response.data.next_before_id || null)
        const stillStreaming = items.some(
          (item) => item.role === 'assistant' && item.status === 'streaming'
        )
        setStreaming(stillStreaming)
        streamingRef.current = stillStreaming
        refreshSessions(true)
      } catch (error) {
        toast(errorMessage(error, '恢复会话状态失败'), 'error')
      }
    },
    [refreshSessions, toast]
  )

  const handleSocketEvent = useCallback(
    (event) => {
      switch (event.type) {
        case 'ready': {
          if (event.quota) setQuota(event.quota)
          if (event.ai_configured === false && !aiWarnedRef.current) {
            aiWarnedRef.current = true
            toast('服务端未配置 DeepSeek API Key，暂时无法进行 AI 对话', 'warning')
          }
          break
        }
        case 'quota': {
          if (event.quota) setQuota(event.quota)
          break
        }
        case 'session_created': {
          const session = event.session
          setSessions((current) => mergeSessions(current, [session]))
          setActiveSessionId(session.id)
          activeSessionRef.current = session.id
          if (pendingRef.current) pendingRef.current.sessionId = session.id
          window.history.replaceState(null, '', '/')
          break
        }
        case 'user_message': {
          const message = event.message
          setMessages((current) => {
            if (event.client_id) {
              const index = current.findIndex((item) => item.clientId === event.client_id)
              if (index >= 0) {
                const next = [...current]
                next[index] = { ...message, clientId: event.client_id }
                return next
              }
            }
            if (current.some((item) => item.id === message.id)) return current
            return [...current, message]
          })
          if (pendingRef.current && event.client_id === pendingRef.current.clientId) {
            pendingRef.current.acked = true
          }
          break
        }
        case 'assistant_start': {
          const message = event.message
          setMessages((current) =>
            current.some((item) => item.id === message.id) ? current : [...current, message]
          )
          setStreaming(true)
          streamingRef.current = true
          break
        }
        case 'delta': {
          setMessages((current) => {
            let found = false
            const next = current.map((item) => {
              if (item.id !== event.message_id) return item
              found = true
              return { ...item, content: `${item.content || ''}${event.content}`, status: 'streaming' }
            })
            if (!found) {
              next.push({
                id: event.message_id,
                session_id: activeSessionRef.current,
                role: 'assistant',
                content: event.content,
                status: 'streaming',
                created_at: new Date().toISOString(),
              })
            }
            return next
          })
          break
        }
        case 'assistant_done': {
          const message = event.message
          if (message) {
            setMessages((current) =>
              current.some((item) => item.id === message.id)
                ? current.map((item) => (item.id === message.id ? message : item))
                : [...current, message]
            )
          }
          setStreaming(false)
          streamingRef.current = false
          pendingRef.current = null
          refreshSessions(true)
          break
        }
        case 'error': {
          if (event.quota) setQuota(event.quota)
          toast(event.message || '发生未知错误', 'error')
          if (event.message_id) {
            setMessages((current) =>
              current.map((item) =>
                item.id === event.message_id ? { ...item, status: 'error' } : item
              )
            )
          }
          const pending = pendingRef.current
          if (pending && !pending.acked) {
            setMessages((current) =>
              current.map((item) =>
                item.temp && item.clientId === pending.clientId
                  ? { ...item, status: 'failed' }
                  : item
              )
            )
          }
          pendingRef.current = null
          setStreaming(false)
          streamingRef.current = false
          if (event.code === 'session_not_found') {
            setActiveSessionId(null)
            setMessages([])
            refreshSessions(true)
          }
          break
        }
        case 'socket_reconnected': {
          toast('实时连接已恢复', 'success')
          if (activeSessionRef.current) resyncSession(activeSessionRef.current)
          break
        }
        case 'socket_unauthorized': {
          toast('登录已过期，请重新登录', 'error')
          logout()
          break
        }
        default:
          break
      }
    },
    [logout, refreshSessions, resyncSession, toast]
  )

  const { status: socketStatus, send } = useChatSocket({ token, onEvent: handleSocketEvent })

  // 流式期间轮询兜底：WebSocket 抖动或断线重连后，从服务端补齐已落库内容
  useEffect(() => {
    if (!streaming || !activeSessionId) return undefined
    const timer = setInterval(async () => {
      try {
        const response = await api.get(`/sessions/${activeSessionId}/messages`, {
          params: { limit: 100 },
        })
        if (activeSessionRef.current !== activeSessionId) return
        const items = response.data.items || []
        const stillStreaming = items.some(
          (item) => item.role === 'assistant' && item.status === 'streaming'
        )
        if (stillStreaming) {
          setMessages((current) =>
            current.map((item) => {
              const server = items.find((candidate) => candidate.id === item.id)
              if (server && (server.content || '').length > (item.content || '').length) {
                return { ...item, content: server.content, status: server.status }
              }
              return item
            })
          )
        } else {
          setMessages(items)
          setHasMore(Boolean(response.data.has_more))
          setNextBefore(response.data.next_before_id || null)
          setStreaming(false)
          streamingRef.current = false
          pendingRef.current = null
          refreshSessions()
        }
      } catch {
        /* 轮询失败静默，等待下一次 */
      }
    }, 3500)
    return () => clearInterval(timer)
  }, [streaming, activeSessionId, refreshSessions])

  const openSession = useCallback(
    async (sessionId) => {
      if (streamingRef.current) {
        toast('请先停止当前回复，再切换会话', 'warning')
        return
      }
      manualNavRef.current = true
      if (sessionId === activeSessionRef.current) {
        setSidebarOpen(false)
        return
      }
      setSidebarOpen(false)
      setActiveSessionId(sessionId)
      activeSessionRef.current = sessionId
      setMessagesLoading(true)
      setMessages([])
      setHasMore(false)
      setNextBefore(null)
      pendingRef.current = null
      try {
        const response = await api.get(`/sessions/${sessionId}/messages`, {
          params: { limit: 50 },
        })
        if (activeSessionRef.current !== sessionId) return
        setMessages(response.data.items || [])
        setHasMore(Boolean(response.data.has_more))
        setNextBefore(response.data.next_before_id || null)
      } catch (error) {
        toast(errorMessage(error, '加载消息失败'), 'error')
        setActiveSessionId(null)
        activeSessionRef.current = null
      } finally {
        setMessagesLoading(false)
      }
    },
    [toast]
  )

  const handleNewChat = useCallback(() => {
    if (streamingRef.current) {
      toast('请先停止当前回复，再新建对话', 'warning')
      return
    }
    manualNavRef.current = true
    setSidebarOpen(false)
    setActiveSessionId(null)
    activeSessionRef.current = null
    setMessages([])
    setHasMore(false)
    setNextBefore(null)
    setMessagesLoading(false)
    pendingRef.current = null
    window.history.replaceState(null, '', '/')
  }, [toast])

  // 首次进入：拉取会话列表，默认打开最近一次会话
  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      try {
        const [sessionsResponse, quotaResponse] = await Promise.all([
          api.get('/sessions', { params: { limit: 100 } }),
          api.get('/usage/me').catch(() => null),
        ])
        if (cancelled) return
        setSessions((current) => mergeSessions(current, sessionsResponse.data))
        setHasMoreSessions(sessionsResponse.data.length === 100)
        if (quotaResponse) setQuota(quotaResponse.data)

        const wantNew = new URLSearchParams(window.location.search).get('new') === '1'
        if (wantNew) window.history.replaceState(null, '', '/')

        const canAutoOpen =
          !wantNew &&
          !manualNavRef.current &&
          activeSessionRef.current === null &&
          messagesRef.current.length === 0 &&
          !pendingRef.current &&
          sessionsResponse.data.length > 0

        if (canAutoOpen) {
          const target = sessionsResponse.data[0]
          const messagesResponse = await api.get(`/sessions/${target.id}/messages`, {
            params: { limit: 50 },
          })
          if (cancelled || activeSessionRef.current !== null) return
          setActiveSessionId(target.id)
          activeSessionRef.current = target.id
          setMessages(messagesResponse.data.items || [])
          setHasMore(Boolean(messagesResponse.data.has_more))
          setNextBefore(messagesResponse.data.next_before_id || null)
        }
      } catch (error) {
        if (!cancelled) toast(errorMessage(error, '初始化会话失败'), 'error')
      } finally {
        if (!cancelled) setSessionsLoading(false)
      }
    }
    boot()
    return () => {
      cancelled = true
    }
  }, [toast])

  // Ctrl/Cmd + K 新建对话
  useEffect(() => {
    const handler = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        handleNewChat()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleNewChat])

  const sendMessage = useCallback(
    (raw) => {
      const content = String(raw || '').trim()
      if (!content) return false
      if (streamingRef.current) {
        toast('上一条回复还在生成中，请稍候', 'warning')
        return false
      }
      if (socketStatus !== 'connected') {
        toast('实时连接尚未就绪，请稍后重试', 'error')
        return false
      }
      const clientId = makeClientId()
      const tempId = `temp-${clientId}`
      const optimistic = {
        id: tempId,
        role: 'user',
        content,
        status: 'sending',
        created_at: new Date().toISOString(),
        temp: true,
        clientId,
      }
      setMessages((current) => [...current, optimistic])
      setStreaming(true)
      streamingRef.current = true
      pendingRef.current = {
        clientId,
        content,
        acked: false,
        sessionId: activeSessionRef.current,
        tempId,
      }
      const ok = send({
        type: 'chat',
        session_id: activeSessionRef.current,
        content,
        client_id: clientId,
      })
      if (!ok) {
        setMessages((current) => current.filter((item) => item.id !== tempId))
        setStreaming(false)
        streamingRef.current = false
        pendingRef.current = null
        toast('消息发送失败，连接已断开，请稍后重试', 'error')
        return false
      }
      return true
    },
    [send, socketStatus, toast]
  )

  const stopGeneration = useCallback(() => {
    if (!streamingRef.current) return
    const ok = send({ type: 'stop' })
    if (!ok) toast('无法停止：实时连接已断开', 'error')
  }, [send, toast])

  const loadMore = async () => {
    if (!hasMore || !nextBefore || loadingMore) return
    setLoadingMore(true)
    try {
      const response = await api.get(`/sessions/${activeSessionRef.current}/messages`, {
        params: { before_id: nextBefore, limit: 50 },
      })
      setMessages((current) => [...(response.data.items || []), ...current])
      setHasMore(Boolean(response.data.has_more))
      setNextBefore(response.data.next_before_id || null)
    } catch (error) {
      toast(errorMessage(error, '加载更早消息失败'), 'error')
    } finally {
      setLoadingMore(false)
    }
  }

  const requestDelete = (session) => {
    if (streamingRef.current && session.id === activeSessionRef.current) {
      toast('请先停止当前回复，再删除会话', 'warning')
      return
    }
    setDeleteTarget(session)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.delete(`/sessions/${deleteTarget.id}`)
      setSessions((current) => current.filter((item) => item.id !== deleteTarget.id))
      if (activeSessionRef.current === deleteTarget.id) handleNewChat()
      toast('会话已删除，可在设置 → 数据 → 回收站中恢复', 'success')
      setDeleteTarget(null)
    } catch (error) {
      toast(errorMessage(error, '删除会话失败'), 'error')
    } finally {
      setDeleting(false)
    }
  }

  const renameSession = async (session, nextTitle) => {
    try {
      const response = await api.patch(`/sessions/${session.id}`, { title: nextTitle })
      setSessions((current) =>
        current.map((item) => (item.id === session.id ? { ...item, ...response.data } : item))
      )
      toast('会话已重命名', 'success')
    } catch (error) {
      toast(errorMessage(error, '重命名失败'), 'error')
    }
  }

  const downloadCurrent = async (format) => {
    if (!activeSessionId) return
    setExporting(format)
    try {
      await downloadFromApi(
        `/sessions/${activeSessionId}/export?format=${format}`,
        `deepseek-session.${format === 'markdown' ? 'md' : 'json'}`
      )
      toast('导出已开始下载', 'success')
    } catch (error) {
      toast(errorMessage(error, '导出失败'), 'error')
    } finally {
      setExporting('')
    }
  }

  return (
    <div className="chat-app">
      <Sidebar
        sessions={sessions}
        activeId={activeSessionId}
        loading={sessionsLoading}
        hasMore={hasMoreSessions}
        loadingMore={sessionsLoadingMore}
        onLoadMore={loadMoreSessions}
        user={user}
        quota={quota}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNew={handleNewChat}
        onSelect={openSession}
        onDelete={requestDelete}
        onRename={renameSession}
        onOpenSettings={() => {
          setSidebarOpen(false)
          setSettingsOpen(true)
        }}
        onOpenAdmin={() => {
          setSidebarOpen(false)
          setAdminOpen(true)
        }}
        onLogout={logout}
        theme={theme}
        onToggleTheme={onToggleTheme}
        busy={streaming}
      />

      {sidebarOpen ? (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      ) : null}

      <main className="chat-main">
        <header className="chat-header">
          <button
            className="icon-btn mobile-only"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开会话列表"
          >
            <Icon name="menu" size={21} />
          </button>

          <div className="chat-title-block">
            <h1 title={title}>{title}</h1>
            <span className="chat-subtitle">
              {activeSession
                ? `${activeSession.message_count || 0} 条消息 · ${formatRelativeTime(
                    activeSession.updated_at
                  )}`
                : '开始一段新的对话'}
            </span>
          </div>

          <div className="header-actions">
            <ConnectionBadge status={socketStatus} />
            <QuotaChip quota={quota} />
            {activeSessionId ? (
              <details className="export-menu">
                <summary className="icon-btn" title="导出当前会话" aria-label="导出当前会话">
                  <Icon name="download" size={18} />
                </summary>
                <div className="menu-panel">
                  <button
                    onClick={(event) => {
                      event.currentTarget.closest('details')?.removeAttribute('open')
                      downloadCurrent('markdown')
                    }}
                  >
                    <Icon name="fileText" size={15} />
                    导出 Markdown
                  </button>
                  <button
                    onClick={(event) => {
                      event.currentTarget.closest('details')?.removeAttribute('open')
                      downloadCurrent('json')
                    }}
                  >
                    <Icon name="database" size={15} />
                    导出 JSON
                  </button>
                </div>
              </details>
            ) : null}
            <button
              className="icon-btn"
              onClick={() => setSettingsOpen(true)}
              title="设置"
              aria-label="设置"
            >
              <Icon name="settings" size={18} />
            </button>
            {user?.role === 'admin' ? (
              <button
                className="icon-btn"
                onClick={() => setAdminOpen(true)}
                title="管理控制台"
                aria-label="管理控制台"
              >
                <Icon name="shield" size={18} />
              </button>
            ) : null}
          </div>
        </header>

        <MessageList
          key={activeSessionId || 'new'}
          messages={messages}
          loading={messagesLoading}
          hasMore={hasMore}
          loadingMore={loadingMore}
          onLoadMore={loadMore}
          streaming={streaming}
          username={user?.username}
          onSuggestion={sendMessage}
        />

        <Composer
          onSend={sendMessage}
          onStop={stopGeneration}
          streaming={streaming}
          connectionStatus={socketStatus}
          quota={quota}
        />
      </main>

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        user={user}
        quota={quota}
        onQuotaRefresh={setQuota}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onSessionsChanged={() => refreshSessions(true)}
      />

      <AdminPanel
        open={adminOpen}
        onClose={() => setAdminOpen(false)}
        currentUser={user}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除会话"
        message={`确定删除「${deleteTarget?.title || ''}」吗？删除后可在设置 → 数据 → 回收站中恢复。`}
        confirmText="确认删除"
        danger
        loading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {exporting ? (
        <div className="export-indicator">
          <span className="spinner spinner-sm" /> 正在导出…
        </div>
      ) : null}
    </div>
  )
}
