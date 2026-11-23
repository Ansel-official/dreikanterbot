const LABELS = {
  connected: '已连接',
  connecting: '连接中',
  disconnected: '已断开',
  unauthorized: '登录失效',
}

export default function ConnectionBadge({ status }) {
  const label = LABELS[status] || '连接中'
  const title =
    status === 'connected'
      ? 'WebSocket 已连接，消息实时推送'
      : status === 'connecting'
        ? '正在建立实时连接…'
        : status === 'unauthorized'
          ? '登录状态失效，请重新登录'
          : '连接已断开，正在自动重连…'
  return (
    <div className={`conn-badge conn-${status}`} title={title}>
      <span className="conn-dot" />
      <span className="conn-text">{label}</span>
    </div>
  )
}
