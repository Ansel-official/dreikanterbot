import { useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { errorMessage } from '../api/client'
import Icon from './Icons'

export default function LoginPage({ theme, onToggleTheme }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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
    <div className="login-page">
      <div className="login-orb login-orb-a" aria-hidden="true" />
      <div className="login-orb login-orb-b" aria-hidden="true" />
      <button
        className="icon-btn login-theme"
        onClick={onToggleTheme}
        aria-label={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
        title="切换主题"
      >
        <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={19} />
      </button>

      <main className="login-card">
        <div className="login-brand">
          <div className="brand-mark" aria-hidden="true">
            <span>D</span>
          </div>
          <div>
            <div className="login-brand-name">Dreikanterbot</div>
            <div className="login-brand-sub">极简 AI 助手</div>
          </div>
        </div>

        <h1>欢迎回来</h1>
        <p className="login-sub">登录后即可继续历史对话，所有设备实时同步。</p>

        <form onSubmit={submit} className="login-form" noValidate>
          <label className="field">
            <span>用户名</span>
            <div className="input-wrap">
              <Icon name="user" size={17} />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入用户名"
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
                placeholder="请输入密码"
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
            {loading ? <span className="spinner spinner-sm" /> : '登录'}
          </button>
        </form>

        <p className="login-note">
          <Icon name="shield" size={14} />
          内部系统 · 账号由管理员统一创建
        </p>
      </main>

      <footer className="login-footer">
        Dreikanterbot · 数据存储于内部服务器 · 支持添加到主屏幕
      </footer>
    </div>
  )
}
