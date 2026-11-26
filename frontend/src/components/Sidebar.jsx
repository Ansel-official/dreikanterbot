import { useMemo, useState } from 'react'
import Icon from './Icons'
import { formatRelativeTime, initialOf, roleLabel, truncate } from '../utils'

export default function Sidebar({
  sessions,
  activeId,
  loading,
  hasMore,
  loadingMore,
  onLoadMore,
  user,
  quota,
  open,
  onClose,
  onNew,
  onSelect,
  onDelete,
  onRename,
  onOpenSettings,
  onOpenAdmin,
  onOpenImport,
  onOpenDevice,
  onOpenMemory,
  onOpenPlugins,
  onOpenAi,
  onLogout,
  theme,
  onToggleTheme,
  busy,
}) {
  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editingTitle, setEditingTitle] = useState('')

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return sessions
    return sessions.filter(
      (session) =>
        session.title?.toLowerCase().includes(keyword) ||
        session.last_message?.toLowerCase().includes(keyword)
    )
  }, [sessions, query])

  const beginRename = (event, session) => {
    event.stopPropagation()
    setEditingId(session.id)
    setEditingTitle(session.title)
  }

  const commitRename = async (session) => {
    const title = editingTitle.trim()
    setEditingId(null)
    if (!title || title === session.title) return
    await onRename?.(session, title)
  }

  const quotaText = !quota
    ? '额度加载中'
    : quota.limit == null
      ? '管理员 · 不限量'
      : `今日 ${quota.used} / ${quota.limit} 次`

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="会话列表">
      <div className="sidebar-top">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <span>D</span>
          </div>
          <div className="brand-text">
            <strong>Dreikanterbot</strong>
            <span>私人工作台 · V3.1.1</span>
          </div>
        </div>
        <button className="icon-btn mobile-only" onClick={onClose} aria-label="关闭侧边栏">
          <Icon name="x" size={20} />
        </button>
      </div>

      <button className={`new-chat-btn ${busy ? 'is-busy' : ''}`} onClick={onNew}>
        <span className="new-chat-icon">
          <Icon name="plus" size={18} />
        </span>
        <span>新建对话</span>
        <kbd>Ctrl K</kbd>
      </button>

      <div className="sidebar-search">
        <Icon name="search" size={16} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索历史对话"
          aria-label="搜索历史对话"
        />
        {query ? (
          <button className="search-clear" onClick={() => setQuery('')} aria-label="清空搜索">
            <Icon name="x" size={13} />
          </button>
        ) : null}
      </div>

      <div className="session-section-head">
        <span>最近会话</span>
        <span className="session-count">{filtered.length}</span>
      </div>

      <div className="session-list">
        {loading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <div className="session-skeleton" key={index}>
              <span className="skeleton skeleton-line w70" />
              <span className="skeleton skeleton-line w90" />
            </div>
          ))
        ) : filtered.length === 0 ? (
          <div className="session-empty">
            <Icon name="message" size={22} />
            <p>{query ? '没有匹配的对话' : '还没有对话，开始第一条吧'}</p>
          </div>
        ) : (
          filtered.map((session) => {
            const active = session.id === activeId
            const editing = editingId === session.id
            return (
              <div
                key={session.id}
                className={`session-item ${active ? 'active' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => {
                  if (editing) return
                  onSelect?.(session.id)
                }}
                onKeyDown={(event) => {
                  if (editing) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelect?.(session.id)
                  }
                }}
              >
                <div className="session-content">
                  {editing ? (
                    <input
                      className="session-rename-input"
                      value={editingTitle}
                      autoFocus
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => setEditingTitle(event.target.value)}
                      onBlur={() => commitRename(session)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          commitRename(session)
                        } else if (event.key === 'Escape') {
                          setEditingId(null)
                        }
                      }}
                    />
                  ) : (
                    <div className="session-title" title={session.title}>
                      {session.title || '新对话'}
                      {session.mode === 'reasoner' ? <span className="session-mode-tag">R1</span> : null}
                    </div>
                  )}
                  <div className="session-preview">
                    {session.last_message ? truncate(session.last_message, 42) : '暂无消息'}
                  </div>
                  <div className="session-meta">
                    <span>{formatRelativeTime(session.updated_at)}</span>
                    <span>{session.message_count || 0} 条</span>
                  </div>
                </div>

                <div className="session-actions">
                  <button
                    className="mini-icon-btn"
                    onClick={(event) => beginRename(event, session)}
                    title="重命名"
                    aria-label="重命名会话"
                  >
                    <Icon name="edit" size={14} />
                  </button>
                  <button
                    className="mini-icon-btn danger"
                    onClick={(event) => {
                      event.stopPropagation()
                      onDelete?.(session)
                    }}
                    title="删除"
                    aria-label="删除会话"
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              </div>
            )
          })
        )}

        {hasMore && !loading ? (
          <button
            className="load-more-sessions"
            onClick={onLoadMore}
            disabled={loadingMore}
          >
            {loadingMore ? <span className="spinner spinner-xs" /> : <Icon name="chevronDown" size={14} />}
            {loadingMore ? '加载中…' : '加载更早的会话'}
          </button>
        ) : null}
      </div>

      <div className="sidebar-footer">
        <div className="quota-card">
          <div className="quota-card-head">
            <span>
              <Icon name="barChart" size={14} /> 今日额度
            </span>
            <span>{quota && quota.limit != null ? `${quota.remaining} 剩余` : ''}</span>
          </div>
          {quota && quota.limit != null ? (
            <div className="quota-track">
              <div
                className="quota-fill"
                style={{ width: `${Math.min(100, (quota.used / quota.limit) * 100)}%` }}
              />
            </div>
          ) : null}
          <div className="quota-text">{quotaText}</div>
        </div>

        <div className="user-card">
          <div className="avatar">{initialOf(user?.username)}</div>
          <div className="user-info">
            <div className="user-name">{user?.username}</div>
            <div className={`user-role role-${user?.role}`}>{roleLabel(user?.role)}</div>
          </div>
          <button className="icon-btn" onClick={onLogout} title="退出登录" aria-label="退出登录">
            <Icon name="logout" size={17} />
          </button>
        </div>

        <div className="sidebar-actions">
          <button className="side-action" onClick={onOpenAi}>
            <Icon name="key" size={16} />
            模型接入
          </button>
          <button className="side-action" onClick={onOpenMemory}>
            <Icon name="memory" size={16} />
            记忆库
          </button>
          <button className="side-action" onClick={onOpenPlugins}>
            <Icon name="plug" size={16} />
            插件
          </button>
          <button className="side-action" onClick={onOpenImport}>
            <Icon name="upload" size={16} />
            继续对话
          </button>
          <button className="side-action" onClick={onOpenDevice}>
            <Icon name="download" size={16} />
            下载 App
          </button>
          <button className="side-action" onClick={onOpenSettings}>
            <Icon name="settings" size={16} />
            设置
          </button>
          {user?.role === 'admin' ? (
            <button className="side-action" onClick={onOpenAdmin}>
              <Icon name="shield" size={16} />
              管理
            </button>
          ) : null}
          <button
            className="side-action theme-toggle"
            onClick={onToggleTheme}
            title="切换主题"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />
            {theme === 'dark' ? '浅色' : '深色'}
          </button>
        </div>
      </div>
    </aside>
  )
}
