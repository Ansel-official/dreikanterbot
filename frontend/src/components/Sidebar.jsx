import { useMemo, useState } from 'react'
import Icon from './Icons'
import { formatRelativeTime, initialOf, roleLabel } from '../utils'

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

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="会话列表">
      <div className="sidebar-top">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <span>D</span>
          </div>
          <div className="brand-text">
            <strong>Dreikanterbot</strong>
            <span>私人工作台 · V3.3</span>
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
                  <span className="session-time">{formatRelativeTime(session.updated_at)}</span>
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
        <div className="sidebar-actions sidebar-actions-compact">
          <button className="side-action" onClick={onOpenMemory} title="记忆库">
            <Icon name="memory" size={17} />
            <span>记忆库</span>
          </button>
          <button className="side-action" onClick={onOpenPlugins} title="插件">
            <Icon name="plug" size={17} />
            <span>插件</span>
          </button>
          <button className="side-action" onClick={onOpenSettings} title="设置">
            <Icon name="settings" size={17} />
            <span>设置</span>
          </button>
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
      </div>
    </aside>
  )
}
