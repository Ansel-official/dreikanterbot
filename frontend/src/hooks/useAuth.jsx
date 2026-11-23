import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api, { clearToken, getToken, setToken, setUnauthorizedHandler } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setTokenState] = useState(() => getToken())
  const [booting, setBooting] = useState(() => Boolean(getToken()))

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken()
      setTokenState(null)
      setUser(null)
      setBooting(false)
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    if (!token) {
      setBooting(false)
      setUser(null)
      return
    }
    let alive = true
    setBooting(true)
    api
      .get('/auth/me')
      .then((response) => {
        if (alive) setUser(response.data)
      })
      .catch(() => {
        if (alive) {
          clearToken()
          setTokenState(null)
          setUser(null)
        }
      })
      .finally(() => {
        if (alive) setBooting(false)
      })
    return () => {
      alive = false
    }
  }, [token])

  const login = useCallback(async (username, password) => {
    const response = await api.post('/auth/login', { username, password })
    setToken(response.data.access_token)
    setTokenState(response.data.access_token)
    setUser(response.data.user)
    setBooting(false)
    return response.data.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      /* token 可能已过期，本地清理即可 */
    }
    clearToken()
    setTokenState(null)
    setUser(null)
  }, [])

  const refreshUser = useCallback(async () => {
    const response = await api.get('/auth/me')
    setUser(response.data)
    return response.data
  }, [])

  const applyTokenResponse = useCallback((data) => {
    setToken(data.access_token)
    setTokenState(data.access_token)
    setUser(data.user)
  }, [])

  const value = useMemo(
    () => ({ user, token, booting, login, logout, refreshUser, applyTokenResponse }),
    [user, token, booting, login, logout, refreshUser, applyTokenResponse]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return context
}
