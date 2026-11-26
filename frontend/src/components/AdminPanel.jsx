import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useToast } from './Toast'
import Modal from './Modal'
import ConfirmDialog from './ConfirmDialog'
import Icon from './Icons'
import { formatDateTime, formatNumber, formatRelativeTime, initialOf, roleLabel } from '../utils'

const TABS = [
  { id: 'overview', label: '概览', icon: 'barChart' },
  { id: 'users', label: '用户', icon: 'user' },
  { id: 'keys', label: '密钥审计', icon: 'key' },
]

export default function AdminPanel({ open, onClose, currentUser }) {
  const toast = useToast()
  const [tab, setTab] = useState('overview')
  const [stats, setStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(false)

  const [users, setUsers] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [usersLoading, setUsersLoading] = useState(false)
  const [actionUserId, setActionUserId] = useState(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({ username: '', password: '', role: 'member' })
  const [creating, setCreating] = useState(false)

  const [resetTarget, setResetTarget] = useState(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetting, setResetting] = useState(false)
  const [deactivateTarget, setDeactivateTarget] = useState(null)

  const [keys, setKeys] = useState([])
  const [keysLoading, setKeysLoading] = useState(false)
  const [revokeKeyTarget, setRevokeKeyTarget] = useState(null)
  const [revokingKey, setRevokingKey] = useState(false)

  useEffect(() => {
    if (!open) return
    if (tab === 'overview') loadStats()
    if (tab === 'keys') loadKeys()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab])

  useEffect(() => {
    if (!open || tab !== 'users') return undefined
    const timer = setTimeout(() => {
      loadUsers()
    }, query ? 300 : 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab, page, query, roleFilter, statusFilter])

  async function loadStats() {
    setStatsLoading(true)
    try {
      const response = await api.get('/admin/stats')
      setStats(response.data)
    } catch (error) {
      toast(errorMessage(error, '加载统计失败'), 'error')
    } finally {
      setStatsLoading(false)
    }
  }

  async function loadUsers() {
    setUsersLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (query.trim()) params.q = query.trim()
      if (roleFilter) params.role = roleFilter
      if (statusFilter) params.is_active = statusFilter === 'active'
      const response = await api.get('/admin/users', { params })
      setUsers(response.data.items || [])
      setTotal(response.data.total || 0)
    } catch (error) {
      toast(errorMessage(error, '加载用户列表失败'), 'error')
    } finally {
      setUsersLoading(false)
    }
  }

  async function loadKeys() {
    setKeysLoading(true)
    try {
      const response = await api.get('/admin/keys')
      setKeys(response.data || [])
    } catch (error) {
      toast(errorMessage(error, '加载密钥失败'), 'error')
    } finally {
      setKeysLoading(false)
    }
  }

  const patchUser = async (target, patch) => {
    setActionUserId(target.id)
    try {
      const response = await api.patch(`/admin/users/${target.id}`, patch)
      setUsers((current) =>
        current.map((item) => (item.id === target.id ? { ...item, ...response.data } : item))
      )
      toast('用户信息已更新', 'success')
      loadStats()
    } catch (error) {
      toast(errorMessage(error, '更新失败'), 'error')
    } finally {
      setActionUserId(null)
    }
  }

  const submitCreate = async (event) => {
    event.preventDefault()
    setCreating(true)
    try {
      await api.post('/admin/users', createForm)
      toast('账号创建成功', 'success')
      setCreateForm({ username: '', password: '', role: 'member' })
      setCreateOpen(false)
      setPage(1)
      loadUsers()
      loadStats()
    } catch (error) {
      toast(errorMessage(error, '创建账号失败'), 'error')
    } finally {
      setCreating(false)
    }
  }

  const submitReset = async (event) => {
    event.preventDefault()
    if (!resetTarget) return
    setResetting(true)
    try {
      const response = await api.post(`/admin/users/${resetTarget.id}/reset-password`, {
        new_password: newPassword,
      })
      toast(response.data.message || '密码已重置', 'success')
      setResetTarget(null)
      setNewPassword('')
    } catch (error) {
      toast(errorMessage(error, '重置密码失败'), 'error')
    } finally {
      setResetting(false)
    }
  }

  const confirmDeactivate = async () => {
    if (!deactivateTarget) return
    await patchUser(deactivateTarget, { is_active: false })
    setDeactivateTarget(null)
  }

  const revokeKey = async () => {
    if (!revokeKeyTarget) return
    setRevokingKey(true)
    try {
      await api.delete(`/admin/keys/${revokeKeyTarget.id}`)
      setKeys((current) => current.filter((item) => item.id !== revokeKeyTarget.id))
      toast('API Key 已吊销', 'success')
      setRevokeKeyTarget(null)
    } catch (error) {
      toast(errorMessage(error, '吊销失败'), 'error')
    } finally {
      setRevokingKey(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const maxDaily = Math.max(1, ...(stats?.daily_usage || []).map((item) => item.requests || 0))

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title="管理控制台"
        subtitle="用户、配额与密钥审计"
        size="xl"
      >
        <div className="admin-tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={`admin-tab ${tab === item.id ? 'active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              <Icon name={item.icon} size={16} />
              {item.label}
            </button>
          ))}
        </div>

        {tab === 'overview' ? (
          <section className="admin-section">
            {statsLoading || !stats ? (
              <div className="settings-loading">
                <span className="spinner" /> 加载统计数据…
              </div>
            ) : (
              <>
                <div className="stat-grid">
                  <div className="stat-card">
                    <span className="stat-icon">
                      <Icon name="user" size={18} />
                    </span>
                    <div className="stat-value">{formatNumber(stats.users_total)}</div>
                    <div className="stat-label">用户总数</div>
                  </div>
                  <div className="stat-card">
                    <span className="stat-icon">
                      <Icon name="message" size={18} />
                    </span>
                    <div className="stat-value">{formatNumber(stats.sessions_total)}</div>
                    <div className="stat-label">会话总数</div>
                  </div>
                  <div className="stat-card">
                    <span className="stat-icon">
                      <Icon name="database" size={18} />
                    </span>
                    <div className="stat-value">{formatNumber(stats.messages_total)}</div>
                    <div className="stat-label">消息总数</div>
                  </div>
                  <div className="stat-card">
                    <span className="stat-icon">
                      <Icon name="barChart" size={18} />
                    </span>
                    <div className="stat-value">{formatNumber(stats.usage_today)}</div>
                    <div className="stat-label">今日 AI 调用</div>
                  </div>
                </div>

                <div className="admin-columns">
                  <div className="panel-card">
                    <div className="panel-head">
                      <h3>近 7 天调用量</h3>
                      <span className="panel-sub">聊天 + 语音</span>
                    </div>
                    <div className="mini-chart admin-chart">
                      {stats.daily_usage.map((item) => (
                        <div className="mini-bar-col" key={item.day} title={`${item.day}：${item.requests} 次`}>
                          <div className="mini-bar-track">
                            <div
                              className="mini-bar"
                              style={{ height: `${Math.max(3, (item.requests / maxDaily) * 100)}%` }}
                            />
                          </div>
                          <span>{item.day.slice(5)}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="panel-card">
                    <div className="panel-head">
                      <h3>角色分布</h3>
                    </div>
                    <div className="role-distribution">
                      {['admin', 'member', 'guest'].map((role) => {
                        const value = stats.users_by_role?.[role] || 0
                        const percent = stats.users_total ? Math.round((value / stats.users_total) * 100) : 0
                        return (
                          <div className="role-row" key={role}>
                            <span className={`role-pill role-${role}`}>{roleLabel(role)}</span>
                            <div className="role-bar">
                              <div className={`role-fill role-fill-${role}`} style={{ width: `${percent}%` }} />
                            </div>
                            <span className="role-number">{value}</span>
                          </div>
                        )
                      })}
                    </div>
                    <div className="settings-divider" />
                    <div className="panel-head">
                      <h3>快捷操作</h3>
                    </div>
                    <div className="button-row">
                      <button
                        className="btn btn-ghost"
                        onClick={() => {
                          setTab('users')
                          setCreateOpen(true)
                        }}
                      >
                        <Icon name="plus" size={15} /> 创建账号
                      </button>
                      <button className="btn btn-ghost" onClick={() => setTab('keys')}>
                        <Icon name="key" size={15} /> 查看密钥
                      </button>
                    </div>
                  </div>
                </div>

                <div className="panel-card">
                  <div className="panel-head">
                    <h3>最近创建的用户</h3>
                  </div>
                  <div className="recent-users">
                    {stats.recent_users.map((item) => (
                      <div className="recent-user" key={item.id}>
                        <span className="avatar avatar-sm">{initialOf(item.username)}</span>
                        <span className="recent-name">{item.username}</span>
                        <span className={`role-pill role-${item.role}`}>{roleLabel(item.role)}</span>
                        <span className="recent-date">{formatDateTime(item.created_at)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </section>
        ) : null}

        {tab === 'users' ? (
          <section className="admin-section">
            <div className="admin-toolbar">
              <div className="sidebar-search admin-search">
                <Icon name="search" size={16} />
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value)
                    setPage(1)
                  }}
                  placeholder="搜索用户名"
                />
              </div>
              <select
                className="select"
                value={roleFilter}
                onChange={(event) => {
                  setRoleFilter(event.target.value)
                  setPage(1)
                }}
                aria-label="按角色筛选"
              >
                <option value="">全部角色</option>
                <option value="admin">管理员</option>
                <option value="member">成员</option>
                <option value="guest">访客</option>
              </select>
              <select
                className="select"
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value)
                  setPage(1)
                }}
                aria-label="按状态筛选"
              >
                <option value="">全部状态</option>
                <option value="active">已启用</option>
                <option value="disabled">已禁用</option>
              </select>
              <button
                className="btn btn-primary admin-create-btn"
                onClick={() => setCreateOpen((current) => !current)}
              >
                <Icon name="plus" size={15} />
                创建账号
              </button>
            </div>

            {createOpen ? (
              <form className="create-user-form" onSubmit={submitCreate}>
                <div className="create-user-fields">
                  <label className="field compact">
                    <span>用户名</span>
                    <input
                      value={createForm.username}
                      onChange={(event) =>
                        setCreateForm((current) => ({ ...current, username: event.target.value }))
                      }
                      placeholder="3-32 位字母/数字/._-"
                      autoComplete="off"
                      required
                    />
                  </label>
                  <label className="field compact">
                    <span>初始密码</span>
                    <input
                      type="text"
                      value={createForm.password}
                      onChange={(event) =>
                        setCreateForm((current) => ({ ...current, password: event.target.value }))
                      }
                      placeholder="至少 8 位，含字母和数字"
                      autoComplete="new-password"
                      required
                    />
                  </label>
                  <label className="field compact">
                    <span>角色</span>
                    <select
                      className="select"
                      value={createForm.role}
                      onChange={(event) =>
                        setCreateForm((current) => ({ ...current, role: event.target.value }))
                      }
                    >
                      <option value="member">成员</option>
                      <option value="guest">访客</option>
                      <option value="admin">管理员</option>
                    </select>
                  </label>
                  <button className="btn btn-primary" type="submit" disabled={creating}>
                    {creating ? <span className="spinner spinner-sm" /> : '确认创建'}
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={() => setCreateOpen(false)}>
                    取消
                  </button>
                </div>
              </form>
            ) : null}

            <div className="table-wrap admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>用户</th>
                    <th>角色</th>
                    <th>状态</th>
                    <th>创建时间</th>
                    <th>最近登录</th>
                    <th className="right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {usersLoading ? (
                    <tr>
                      <td colSpan={6} className="table-empty">
                        <span className="spinner spinner-sm" /> 加载中…
                      </td>
                    </tr>
                  ) : users.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="table-empty">
                        没有匹配的用户
                      </td>
                    </tr>
                  ) : (
                    users.map((item) => {
                      const isSelf = item.id === currentUser?.id
                      return (
                        <tr key={item.id} className={item.is_active ? '' : 'row-disabled'}>
                          <td>
                            <div className="table-user">
                              <span className="avatar avatar-sm">{initialOf(item.username)}</span>
                              <div>
                                <div className="table-username">
                                  {item.username}
                                  {isSelf ? <span className="self-tag">我</span> : null}
                                </div>
                                <div className="table-userid">ID {item.id}</div>
                              </div>
                            </div>
                          </td>
                          <td>
                            <select
                              className="select select-sm"
                              value={item.role}
                              disabled={isSelf || actionUserId === item.id}
                              onChange={(event) => patchUser(item, { role: event.target.value })}
                              aria-label={`修改 ${item.username} 的角色`}
                            >
                              <option value="admin">管理员</option>
                              <option value="member">成员</option>
                              <option value="guest">访客</option>
                            </select>
                          </td>
                          <td>
                            <button
                              className={`status-pill ${item.is_active ? 'ok' : 'off'} status-button`}
                              disabled={isSelf || actionUserId === item.id}
                              onClick={() =>
                                item.is_active
                                  ? setDeactivateTarget(item)
                                  : patchUser(item, { is_active: true })
                              }
                            >
                              {item.is_active ? '已启用' : '已禁用'}
                            </button>
                          </td>
                          <td className="muted">{formatDateTime(item.created_at)}</td>
                          <td className="muted">
                            {item.last_login_at ? formatRelativeTime(item.last_login_at) : '从未登录'}
                          </td>
                          <td>
                            <div className="table-actions">
                              <button
                                className="btn btn-sm btn-ghost"
                                onClick={() => {
                                  setResetTarget(item)
                                  setNewPassword('')
                                }}
                                disabled={isSelf}
                              >
                                重置密码
                              </button>
                              {item.is_active ? (
                                <button
                                  className="btn btn-sm btn-danger-ghost"
                                  disabled={isSelf}
                                  onClick={() => setDeactivateTarget(item)}
                                >
                                  禁用
                                </button>
                              ) : (
                                <button
                                  className="btn btn-sm btn-ghost"
                                  onClick={() => patchUser(item, { is_active: true })}
                                >
                                  启用
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="admin-pager">
              <span>
                共 {total} 个用户 · 第 {page} / {totalPages} 页
              </span>
              <div className="pager-actions">
                <button className="btn btn-sm btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  <Icon name="chevronLeft" size={15} /> 上一页
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页 <Icon name="chevronRight" size={15} />
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {tab === 'keys' ? (
          <section className="admin-section">
            <p className="settings-desc">
              展示所有用户的 API Key。管理员只能吊销，无法看到明文；密钥仅创建时展示一次。
            </p>
            {keysLoading ? (
              <div className="settings-loading">
                <span className="spinner" /> 加载密钥…
              </div>
            ) : keys.length === 0 ? (
              <div className="empty-inline">
                <Icon name="key" size={22} />
                <p>系统内还没有 API Key</p>
              </div>
            ) : (
              <div className="table-wrap admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>用户</th>
                      <th>名称</th>
                      <th>前缀</th>
                      <th>状态</th>
                      <th>创建时间</th>
                      <th>最近使用</th>
                      <th className="right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {keys.map((item) => (
                      <tr key={item.id} className={item.is_active ? '' : 'row-disabled'}>
                        <td>{item.username}</td>
                        <td>{item.name}</td>
                        <td>
                          <code>{item.key_prefix}…</code>
                        </td>
                        <td>
                          <span className={`status-pill ${item.is_active ? 'ok' : 'off'}`}>
                            {item.is_active ? '有效' : '已吊销'}
                          </span>
                        </td>
                        <td className="muted">{formatDateTime(item.created_at)}</td>
                        <td className="muted">
                          {item.last_used_at ? formatRelativeTime(item.last_used_at) : '从未使用'}
                        </td>
                        <td className="right">
                          {item.is_active ? (
                            <button
                              className="btn btn-sm btn-danger-ghost"
                              onClick={() => setRevokeKeyTarget(item)}
                            >
                              吊销
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(resetTarget)}
        onClose={() => setResetTarget(null)}
        title="重置用户密码"
        subtitle={resetTarget ? `为 ${resetTarget.username} 设置新密码` : ''}
        size="sm"
      >
        <form className="settings-form" onSubmit={submitReset}>
          <label className="field">
            <span>新密码</span>
            <div className="input-wrap">
              <Icon name="lock" size={16} />
              <input
                type="text"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder="至少 8 位，含字母和数字"
                autoComplete="new-password"
                minLength={8}
                required
                autoFocus
              />
            </div>
          </label>
          <p className="field-hint">
            重置后该用户所有已登录设备都会立即失效，需要使用新密码重新登录。管理员自己的密码请到「设置 → 账号」修改。
          </p>
          <div className="modal-form-actions">
            <button className="btn btn-ghost" type="button" onClick={() => setResetTarget(null)}>
              取消
            </button>
            <button className="btn btn-primary" type="submit" disabled={resetting}>
              {resetting ? <span className="spinner spinner-sm" /> : '确认重置'}
            </button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(deactivateTarget)}
        title="禁用账号"
        message={`确定禁用「${deactivateTarget?.username || ''}」吗？该用户将立即无法登录，历史数据会保留。`}
        confirmText="确认禁用"
        danger
        onConfirm={confirmDeactivate}
        onCancel={() => setDeactivateTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(revokeKeyTarget)}
        title="吊销 API Key"
        message={`确定吊销「${revokeKeyTarget?.name || ''}」吗？相关脚本会立即失去访问权限。`}
        confirmText="确认吊销"
        danger
        loading={revokingKey}
        onConfirm={revokeKey}
        onCancel={() => setRevokeKeyTarget(null)}
      />
    </>
  )
}
