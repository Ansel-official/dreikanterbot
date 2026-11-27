import { useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { errorMessage, getApiBase, setApiBase } from '../api/client'
import Icon from './Icons'

export default function LoginPage({ theme, onToggleTheme }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [serverUrl, setServerUrl] = useState(() => getApiBase())
  const [showServer, setShowServer] = useState(false)

  const saveServer = () => {
    const value = serverUrl.trim()
    if (!value) {
      setApiBase('')
      window.location.reload()
      return
    }
    if (!/^https?:\/\//i.test(value)) {
      setError('服务器地址需要以 http:// 或 https:// 开头')
      return
    }
    setApiBase(value)
    window.location.reload()
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    setError('')
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(errorMessage(err, '登录失败，请检查账号或密码'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-v3">
      <aside className="login-story">
        <div className="login-story-top">
          <div className="brand-mark" aria-hidden="true">
            <span>D</span>
          </div>
          <span className="login-story-wordmark">DREIKANTERBOT</span>
        </div>

        <div className="login-story-copy">
          <span className="eyebrow">A QUIET WORKSPACE</span>
          <h1>把对话、文件和判断，留在自己手里。</h1>
          <p>
            不是另一个聊天框。V3.3 把云端模型、本地 Ollama、长上下文、记忆库和插件放在同一个工作台里，
            你带自己的 Key，数据留在自己的服务器。
          </p>
        </div>

        <footer className="login-story-foot">
          <span>MIT License</span>
          <span>V3.3</span>
          <span>数据存储于你的服务器</span>
        </footer>
      </aside>

      <main className="login-panel">
        <div className="login-panel-top">
          <span className="login-panel-label">账号登录</span>
          <button
            className="icon-btn"
            onClick={onToggleTheme}
            aria-label={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
            title="切换主题"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
          </button>
        </div>

        <div className="login-panel-inner">
          <h2>继续</h2>
          <p className="login-sub">历史会话和记忆库都在原来的位置。</p>

          <form onSubmit={submit} className="login-form" noValidate>
            <label className="field">
              <span>用户名</span>
              <div className="input-wrap">
                <Icon name="user" size={17} />
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="用户名"
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck="false"
                  autoFocus
                />
              </div>
            </label>

            <label className="field">
              <span>密码</span>
              <div className="input-wrap">
                <Icon name="lock" size={17} />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="密码"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="input-action"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  <Icon name={showPassword ? 'eyeOff' : 'eye'} size={17} />
                </button>
              </div>
            </label>

            {error ? (
              <div className="form-error" role="alert">
                <Icon name="alert" size={15} />
                <span>{error}</span>
              </div>
            ) : null}

            <button className="btn btn-primary btn-lg btn-block" type="submit" disabled={loading}>
              {loading ? <span className="spinner spinner-sm" /> : '进入工作台'}
            </button>
          </form>

          <div className="login-v3-note">
            <Icon name="lock" size={14} />
            首次使用需要在「设置 → AI 接入」填写自己的模型 Key。
          </div>

          <div className="login-server">
            <button type="button" onClick={() => setShowServer((current) => !current)}>
              <Icon name="globe" size={13} />
              桌面 / 安卓客户端：设置服务器地址
            </button>
            {showServer ? (
              <div className="login-server-form">
                <input
                  value={serverUrl}
                  onChange={(event) => setServerUrl(event.target.value)}
                  placeholder="https://your-domain.com/api"
                  spellCheck="false"
                />
                <button className="btn btn-sm btn-ghost" onClick={saveServer}>
                  保存并重载
                </button>
              </div>
            ) : null}
          </div>
        </div>

        <footer className="login-panel-foot">
          <span>账号由管理员创建</span>
          <span>Dreikanterbot 3.3</span>
        </footer>
      </main>
    </div>
  )
}
