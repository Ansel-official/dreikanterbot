import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import Icon from './Icons'

function Welcome({ aiReady, onOpenAi }) {
  return (
    <div className="welcome">
      <h2>今天有什么可以帮到你？</h2>
      <p className="welcome-sub">DeepSeek、Kimi 或本地模型。直接输入，或先拖入一份材料。</p>
      {!aiReady ? (
        <button className="welcome-key-callout" onClick={onOpenAi}>
          <Icon name="key" size={18} />
          <span>
            <strong>先接入模型</strong>
            <small>云端 Key 或本机 Ollama，设置里一分钟完成。</small>
          </span>
          <Icon name="chevronRight" size={17} />
        </button>
      ) : null}
    </div>
  )
}

function Skeleton() {
  return (
    <div className="skeleton-list" aria-label="正在加载消息">
      <div className="skeleton-row assistant">
        <div className="skeleton skeleton-avatar" />
        <div className="skeleton skeleton-bubble" />
      </div>
      <div className="skeleton-row user">
        <div className="skeleton skeleton-bubble short" />
      </div>
      <div className="skeleton-row assistant">
        <div className="skeleton skeleton-avatar" />
        <div className="skeleton skeleton-bubble tall" />
      </div>
    </div>
  )
}

export default function MessageList({
  messages,
  loading,
  hasMore,
  loadingMore,
  onLoadMore,
  streaming,
  username,
  onSuggestion,
  onImport,
  onDevice,
  onMemory,
  onPlugin,
  aiReady,
  onOpenAi,
}) {
  const scrollRef = useRef(null)
  const endRef = useRef(null)
  const nearBottomRef = useRef(true)
  const lastContentLength = messages.length
    ? (messages[messages.length - 1]?.content || '').length
    : 0
  const lastReasoningLength = messages.length
    ? (messages[messages.length - 1]?.reasoning || '').length
    : 0

  const scrollToBottom = (smooth = false) => {
    endRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' })
  }

  useEffect(() => {
    if (!loading && nearBottomRef.current) scrollToBottom(false)
  }, [messages.length, loading])

  useEffect(() => {
    if (streaming && nearBottomRef.current) scrollToBottom(false)
  }, [lastContentLength, lastReasoningLength, streaming])

  const handleScroll = () => {
    const element = scrollRef.current
    if (!element) return
    nearBottomRef.current =
      element.scrollHeight - element.scrollTop - element.clientHeight < 160
  }

  return (
    <div className="messages" ref={scrollRef} onScroll={handleScroll}>
      <div className="messages-inner">
        {loading ? (
          <Skeleton />
        ) : messages.length === 0 ? (
          <Welcome
            username={username}
            onSuggestion={onSuggestion}
            onImport={onImport}
            onDevice={onDevice}
            onMemory={onMemory}
            onPlugin={onPlugin}
            aiReady={aiReady}
            onOpenAi={onOpenAi}
          />
        ) : (
          <>
            {hasMore ? (
              <div className="load-more-wrap">
                <button className="load-more" onClick={onLoadMore} disabled={loadingMore}>
                  {loadingMore ? <span className="spinner spinner-xs" /> : <Icon name="clock" size={14} />}
                  {loadingMore ? '加载中…' : '加载更早的消息'}
                </button>
              </div>
            ) : null}

            <div className="message-stack">
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  streaming={streaming && message.status === 'streaming' && message.role === 'assistant'}
                />
              ))}
            </div>
            <div ref={endRef} />
            <p className="chat-disclaimer">内容由模型生成。涉及事实、数字和法律结论时，请回到来源核对。</p>
          </>
        )}
      </div>
    </div>
  )
}
