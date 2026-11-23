import { useEffect } from 'react'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { useTheme } from './hooks/useTheme'
import { ToastProvider, useToast } from './components/Toast'
import LoginPage from './components/LoginPage'
import ChatPage from './components/ChatPage'
import Splash from './components/Splash'

function Shell() {
  const { user, booting } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const toast = useToast()

  useEffect(() => {
    const handler = () => {
      toast('应用已更新，刷新页面即可使用新版本', 'info')
    }
    window.addEventListener('dc:sw-updated', handler)
    return () => window.removeEventListener('dc:sw-updated', handler)
  }, [toast])

  if (booting && !user) return <Splash />
  if (!user) return <LoginPage theme={theme} onToggleTheme={toggleTheme} />
  return <ChatPage theme={theme} onToggleTheme={toggleTheme} />
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </ToastProvider>
  )
}
