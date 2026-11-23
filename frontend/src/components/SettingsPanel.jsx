import { useEffect, useState } from 'react'
import api, { downloadFromApi, errorMessage } from '../api/client'
import { useAuth } from '../hooks/useAuth'
import { useToast } from './Toast'
import Modal from './Modal'
import ConfirmDialog from './ConfirmDialog'
import Icon from './Icons'
import {
  copyText,
  formatDateTime,
  formatNumber,
  formatRelativeTime,
  roleLabel,
} from '../utils'

const TABS = [
  { id: 'account', label: '账号', icon: 'user' },
  { id: 'keys', label: 'API Keys', icon: 'key' },
  { id: 'usage', label: '用量', icon: 'barChart' },
  { id: 'data', label: '数据', icon: 'database' },
]

export default function SettingsPanel({
  open,
  onClose,
  user,
  quota,
  onQuotaRefresh,
  theme,
  onToggleTheme,
  onSessionsChanged,
}) {
  const toast = useToast()
  const { applyTokenResponse, logout } = useAuth()
  const [tab, setTab] = useState('account')

  const [passwordForm, setPasswordForm] = useState({ old_password: '', new_password: '', confirm: '' })
  const [changingPassword, setChangingPassword] = useState(false)

  const [keys, setKeys] = useState([])
  const [keysLoading, setKeysLoading] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [creatingKey, setCreatingKey] = useState(false)
  const [newKey, setNewKey] = useState('')
  const [revokeTarget, setRevokeTarget] = useState(null)
  const [revoking, setRevoking] = useState(false)

  const [usage, setUsage] = useState(null)
  const [history, setHistory] = useState([])
  const [usageLoading, setUsageLoading] = useState(false)

  const [exporting, setExporting] = useState('')
  const [deleted, setDeleted] = useState([])
  const [deletedLoading, setDeletedLoading] = useState(false)
  const [restoringId, setRestoringId] = useState(null)

  useEffect(() => {
    if (!open) return
    if (tab === 'keys') loadKeys()
    if (tab === 'usage') loadUsage()
    if (tab === 'data') loadDeleted()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab])

  async function loadKeys() {
    setKeysLoading(true)
    try {
      const response = await api.get('/keys')
      setKeys(response.data)
    } catch (error) {
      toast(errorMessage(error, '加载 API Key 失败'), 'error')
    } finally {
      setKeysLoading(false)
    }
  }

  async function loadUsage() {
    setUsageLoading(true)
    try {
      const [quotaResponse, historyResponse] = await Promise.all([
        api.get('/usage/me'),
        api.get('/usage/me/history?days=14'),
      ])
      setUsage(quotaResponse.data)
      setHistory(historyResponse.data.items || [])
      onQuotaRefresh?.(quotaResponse.data)
    } catch (error) {
      toast(errorMessage(error, '加载用量失败'), 'error')
    } finally {
      setUsageLoading(false)
    }
  }

  async function loadDeleted() {
    setDeletedLoading(true)
    try {
      const response = await api.get('/sessions', { params: { include_deleted: true } })
      setDeleted((response.data || []).filter((item) => item.is_deleted))
    } catch (error) {
      toast(errorMessage(error, '加载回收站失败'), 'error')
    } finally {
      setDeletedLoading(false)
    }
  }

  const changePassword = async (event) => {
    event.preventDefault()
    if (passwordForm.new_password !== passwordForm.confirm) {
      toast('两次输入的新密码不一致', 'error')
      return
    }
    setChangingPassword(true)
    try {
      const response = await api.post('/auth/change-password', {
        old_password: passwordForm.old_password,
        new_password: passwordForm.new_password,
      })
      applyTokenResponse(response.data)
      setPasswordForm({ old_password: '', new_password: '', confirm: '' })
      toast('密码已修改，当前会话已续签；其他设备需要重新登录', 'success')
    } catch (error) {
      toast(errorMessage(error, '修改密码失败'), 'error')
    } finally {
      setChangingPassword(false)
    }
  }

  const createKey = async (event) => {
    event.preventDefault()
    if (!keyName.trim()) return
    setCreatingKey(true)
    try {
      const response = await api.post('/keys', { name: keyName.trim() })
      setKeys((current) => [response.data, ...current])
      setNewKey(response.data.key)
      setKeyName('')
      toast('API Key 已创建，请立即复制保存', 'success')
    } catch (error) {
      toast(errorMessage(error, '创建 API Key 失败'), 'error')
    } finally {
      setCreatingKey(false)
    }
  }

  const revokeKey = async () => {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await api.delete(`/keys/${revokeTarget.id}`)
      setKeys((current) =>
        current.map((item) => (item.id === revokeTarget.id ? { ...item, is_active: false } : item))
      )
      toast('API Key 已吊销，立即生效', 'success')
      setRevokeTarget(null)
    } catch (error) {
      toast(errorMessage(error, '吊销失败'), 'error')
    } finally {
      setRevoking(false)
    }
  }

  const copyNewKey = async () => {
    const ok = await copyText(newKey)
    toast(ok ? '已复制到剪贴板' : '复制失败，请手动选择', ok ? 'success' : 'error')
  }

  const exportAll = async (format) => {
    setExporting(format)
    try {
      await downloadFromApi(
        `/sessions/export?format=${format}`,
        `deepseek-chat-export.${format === 'markdown' ? 'md' : 'json'}`
      )
      toast('导出已开始下载', 'success')
    } catch (error) {
      toast(errorMessage(error, '导出失败'), 'error')
    } finally {
      setExporting('')
    }
  }

  const restoreSession = async (session) => {
    setRestoringId(session.id)
    try {
      await api.post(`/sessions/${session.id}/restore`)
      setDeleted((current) => current.filter((item) => item.id !== session.id))
      onSessionsChanged?.()
      toast('会话已恢复', 'success')
    } catch (error) {
      toast(errorMessage(error, '恢复失败'), 'error')
    } finally {
      setRestoringId(null)
    }
  }

  const currentQuota = usage || quota
  const usagePercent =
    currentQuota && currentQuota.limit
      ? Math.min(100, (currentQuota.used / currentQuota.limit) * 100)
      : 0
  const maxRequests = Math.max(1, ...history.map((item) => item.requests || 0))
  const totalRequests = history.reduce((sum, item) => sum + (item.requests || 0), 0)
  const totalTokens = history.reduce((sum, item) => sum + (item.tokens || 0), 0)

  return (
    <>
      <Modal open={open} onClose={onClose} title="设置" subtitle="账号、密钥与数据管理" size="lg">
        <div className="settings-layout">
          <nav className="settings-tabs" aria-label="设置分类">
            {TABS.map((item) => (
              <button
                key={item.id}
                className={`settings-tab ${tab === item.id ? 'active' : ''}`}
                onClick={() => setTab(item.id)}
              >
                <Icon name={item.icon} size={16} />
                {item.label}
              </button>
            ))}
          </nav>

          <div className="settings-content">
            {tab === 'account' ? (
              <section className="settings-section">
                <div className="account-card">
                  <div className="avatar avatar-lg">{user?.username?.charAt(0).toUpperCase()}</div>
                  <div>
                    <div className="account-name">{user?.username}</div>
                    <div className="account-meta">
                      <span className={`role-pill role-${user?.role}`}>{roleLabel(user?.role)}</span>
                      <span>注册于 {formatDateTime(user?.created_at)}</span>
                    </div>
                  </div>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-label">界面主题</div>
                    <div className="setting-desc">深色模式适合夜间使用，设置保存在本机。</div>
                  </div>
                  <button className="btn btn-ghost" onClick={onToggleTheme}>
                    <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />
                    {theme === 'dark' ? '切换浅色' : '切换深色'}
                  </button>
                </div>

                <div className="settings-divider" />

                <h3 className="settings-heading">修改密码</h3>
                <form className="settings-form" onSubmit={changePassword}>
                  <label className="field">
                    <span>当前密码</span>
                    <div className="input-wrap">
                      <Icon name="lock" size={16} />
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={passwordForm.old_password}
                        onChange={(event) =>
                          setPasswordForm((current) => ({ ...current, old_password: event.target.value }))
                        }
                        required
                      />
                    </div>
                  </label>
                  <label className="field">
                    <span>新密码</span>
                    <div className="input-wrap">
                      <Icon name="lock" size={16} />
                      <input
                        type="password"
                        autoComplete="new-password"
                        minLength={8}
                        value={passwordForm.new_password}
                        onChange={(event) =>
                          setPasswordForm((current) => ({ ...current, new_password: event.target.value }))
                        }
                        required
                      />
                    </div>
                    <small className="field-hint">至少 8 位，必须同时包含字母和数字</small>
                  </label>
                  <label className="field">
                    <span>确认新密码</span>
                    <div className="input-wrap">
                      <Icon name="lock" size={16} />
                      <input
                        type="password"
                        autoComplete="new-password"
                        value={passwordForm.confirm}
                        onChange={(event) =>
                          setPasswordForm((current) => ({ ...current, confirm: event.target.value }))
                        }
                        required
                      />
                    </div>
                  </label>
                  <button className="btn btn-primary" type="submit" disabled={changingPassword}>
                    {changingPassword ? <span className="spinner spinner-sm" /> : '更新密码'}
                  </button>
                </form>

                <div className="settings-divider" />
                <div className="setting-row">
                  <div>
                    <div className="setting-label">退出登录</div>
                    <div className="setting-desc">退出后本机将清除登录凭证，服务端历史不受影响。</div>
                  </div>
                  <button
                    className="btn btn-danger-ghost"
                    onClick={async () => {
                      await logout()
                      onClose?.()
                    }}
                  >
                    <Icon name="logout" size={16} />
                    退出登录
                  </button>
                </div>
              </section>
            ) : null}

            {tab === 'keys' ? (
              <section className="settings-section">
                <p className="settings-desc">
                  为脚本或外部系统创建 API Key。调用时放在
                  <code>Authorization: Bearer sk-chat-...</code> 中，权限与你的账号一致。
                </p>

                <form className="inline-form" onSubmit={createKey}>
                  <div className="input-wrap">
                    <Icon name="key" size={16} />
                    <input
                      value={keyName}
                      onChange={(event) => setKeyName(event.target.value)}
                      placeholder="密钥名称，例如：n8n 自动化"
                      maxLength={100}
                    />
                  </div>
                  <button className="btn btn-primary" type="submit" disabled={creatingKey || !keyName.trim()}>
                    {creatingKey ? <span className="spinner spinner-sm" /> : '生成密钥'}
                  </button>
                </form>

                {newKey ? (
                  <div className="new-key-panel">
                    <div className="new-key-head">
                      <Icon name="alert" size={16} />
                      <strong>仅显示这一次，请立即复制保存</strong>
                      <button className="icon-btn" onClick={() => setNewKey('')} aria-label="关闭">
                        <Icon name="x" size={15} />
                      </button>
                    </div>
                    <div className="new-key-value">
                      <code>{newKey}</code>
                      <button className="btn btn-sm btn-ghost" onClick={copyNewKey}>
                        <Icon name="copy" size={14} />
                        复制
                      </button>
                    </div>
                  </div>
                ) : null}

                <div className="key-list">
                  {keysLoading ? (
                    <div className="settings-loading">
                      <span className="spinner" /> 加载密钥…
                    </div>
                  ) : keys.length === 0 ? (
                    <div className="empty-inline">
                      <Icon name="key" size={22} />
                      <p>还没有 API Key</p>
                    </div>
                  ) : (
                    keys.map((item) => (
                      <div className={`key-item ${item.is_active ? '' : 'revoked'}`} key={item.id}>
                        <div className="key-icon">
                          <Icon name="key" size={18} />
                        </div>
                        <div className="key-main">
                          <div className="key-name">
                            {item.name}
                            <span className={`status-pill ${item.is_active ? 'ok' : 'off'}`}>
                              {item.is_active ? '有效' : '已吊销'}
                            </span>
                          </div>
                          <div className="key-meta">
                            <code>{item.key_prefix}…</code>
                            <span>创建于 {formatRelativeTime(item.created_at)}</span>
                            {item.last_used_at ? <span>最近使用 {formatRelativeTime(item.last_used_at)}</span> : null}
                          </div>
                        </div>
                        {item.is_active ? (
                          <button
                            className="btn btn-sm btn-danger-ghost"
                            onClick={() => setRevokeTarget(item)}
                          >
                            吊销
                          </button>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              </section>
            ) : null}

            {tab === 'usage' ? (
              <section className="settings-section">
                {usageLoading ? (
                  <div className="settings-loading">
                    <span className="spinner" /> 加载用量…
                  </div>
                ) : (
                  <>
                    <div className="usage-summary">
                      <div>
                        <div className="usage-label">今日已用</div>
                        <div className="usage-value">
                          {currentQuota?.limit == null ? '不限量' : `${currentQuota?.used ?? 0} 次`}
                        </div>
                      </div>
                      <div>
                        <div className="usage-label">今日剩余</div>
                        <div className="usage-value">
                          {currentQuota?.limit == null ? '∞' : `${currentQuota?.remaining ?? 0} 次`}
                        </div>
                      </div>
                      <div>
                        <div className="usage-label">近 14 天请求</div>
                        <div className="usage-value">{formatNumber(totalRequests)}</div>
                      </div>
                      <div>
                        <div className="usage-label">近 14 天 tokens</div>
                        <div className="usage-value">{formatNumber(totalTokens)}</div>
                      </div>
                    </div>

                    <div className="quota-track quota-track-lg">
                      <div className="quota-fill" style={{ width: `${usagePercent}%` }} />
                    </div>
                    <p className="settings-desc">
                      {currentQuota?.limit == null
                        ? '管理员账号不限制每日调用次数。'
                        : `每日 ${currentQuota?.limit} 次，次日 00:00（北京时间）自动重置。聊天与语音识别共用额度。`}
                    </p>

                    <h3 className="settings-heading">近 14 天用量</h3>
                    <div className="mini-chart" role="img" aria-label="近 14 天请求量柱状图">
                      {history.map((item) => (
                        <div className="mini-bar-col" key={item.day} title={`${item.day}：${item.requests} 次`}>
                          <div className="mini-bar-track">
                            <div
                              className="mini-bar"
                              style={{ height: `${Math.max(3, (item.requests / maxRequests) * 100)}%` }}
                            />
                          </div>
                          <span>{item.day.slice(5)}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </section>
            ) : null}

            {tab === 'data' ? (
              <section className="settings-section">
                <h3 className="settings-heading">导出全部对话</h3>
                <p className="settings-desc">导出文件包含所有未删除会话及消息，可用于归档或迁移。</p>
                <div className="button-row">
                  <button
                    className="btn btn-ghost"
                    onClick={() => exportAll('json')}
                    disabled={Boolean(exporting)}
                  >
                    {exporting === 'json' ? <span className="spinner spinner-sm" /> : <Icon name="download" size={16} />}
                    导出 JSON
                  </button>
                  <button
                    className="btn btn-ghost"
                    onClick={() => exportAll('markdown')}
                    disabled={Boolean(exporting)}
                  >
                    {exporting === 'markdown' ? (
                      <span className="spinner spinner-sm" />
                    ) : (
                      <Icon name="fileText" size={16} />
                    )}
                    导出 Markdown
                  </button>
                </div>

                <div className="settings-divider" />
                <h3 className="settings-heading">回收站</h3>
                <p className="settings-desc">
                  删除的会话会保留在服务端，可在此恢复。消息不会被物理删除。
                </p>
                {deletedLoading ? (
                  <div className="settings-loading">
                    <span className="spinner" /> 加载回收站…
                  </div>
                ) : deleted.length === 0 ? (
                  <div className="empty-inline">
                    <Icon name="trash" size={22} />
                    <p>回收站是空的</p>
                  </div>
                ) : (
                  <div className="deleted-list">
                    {deleted.map((item) => (
                      <div className="deleted-item" key={item.id}>
                        <div>
                          <div className="deleted-title">{item.title}</div>
                          <div className="deleted-meta">
                            更新于 {formatDateTime(item.updated_at)} · {item.message_count} 条消息
                          </div>
                        </div>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => restoreSession(item)}
                          disabled={restoringId === item.id}
                        >
                          {restoringId === item.id ? <span className="spinner spinner-sm" /> : <Icon name="refresh" size={14} />}
                          恢复
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="settings-divider" />
                <h3 className="settings-heading">离线使用</h3>
                <p className="settings-desc">
                  本应用支持 PWA。用手机浏览器打开后选择“添加到主屏幕”，即可像 App
                  一样使用；弱网下仍能打开界面，但新消息需要联网才能发送。
                </p>
              </section>
            ) : null}
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="吊销 API Key"
        message={`确定吊销「${revokeTarget?.name || ''}」吗？使用该密钥的脚本会立即失去访问权限。`}
        confirmText="确认吊销"
        danger
        loading={revoking}
        onConfirm={revokeKey}
        onCancel={() => setRevokeTarget(null)}
      />
    </>
  )
}
