import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import Icon from './Icons'

const SUGGESTIONS = [
  {
    icon: 'fileText',
    title: '把材料整理成结论',
    prompt: '把下面的材料整理成一页结论：先给三句话摘要，再列事实、分歧、风险和建议。缺少信息的地方直接标注，不要猜。\n\n',
  },
  {
    icon: 'brain',
    title: '审查一段代码',
    prompt: '请审查下面这段代码，重点关注正确性、边界条件、并发和错误处理。按阻塞/建议/可选分级，给出可执行的修复。\n\n```\n\n```',
  },
  {
    icon: 'message',
    title: '把一个方案写清楚',
    prompt: '把下面的想法写成可执行的方案：目标、约束、步骤、负责人、验收标准、失败时的退路。不要写空泛的愿景。\n\n',
  },
  {
    icon: 'edit',
    title: '把长文改短',
    prompt: '把下面的文字压缩到一半，保留事实、数字和限定条件；删掉套话、重复和“首先其次最后”的模板。\n\n',
  },
]

function Welcome({ onSuggestion, onImport, onDevice, onMemory, onPlugin, aiReady, onOpenAi }) {
  return (
    <div className="welcome">
      <h2>今天有什么可以帮到你？</h2>
      <p className="welcome-sub">
        DeepSeek V4 与 Kimi K3 · 1M 上下文 · 密钥只留在你的服务器
      </p>
      {!aiReady ? (
        <button className="welcome-key-callout" onClick={onOpenAi}>
          <Icon name="key" size={18} />
          <span>
            <strong>先接入模型 API Key</strong>
            <small>DeepSeek 与 Kimi 两个 Key 可同时保存；接入后即可开始。</small>
          </span>
          <Icon name="chevronRight" size={17} />
        </button>
      ) : null}
      <div className="suggestion-grid">
        {SUGGESTIONS.map((item) => (
          <button
            key={item.title}
            className="suggestion-card"
            onClick={() => onSuggestion?.(item.prompt)}
            disabled={!aiReady}
          >
            <span className="suggestion-icon">
              <Icon name={item.icon} size={17} />
            </span>
            <span>{item.title}</span>
            <Icon name="chevronRight" size={14} className="suggestion-arrow" />
          </button>
        ))}
      </div>
      <div className="welcome-shortcuts">
        <button onClick={onMemory}>
          <Icon name="memory" size={15} />
          记忆库
        </button>
        <button onClick={onPlugin}>
          <Icon name="plug" size={15} />
          插件
        </button>
        <button onClick={onImport}>
          <Icon name="upload" size={15} />
          继续 DeepSeek 对话
        </button>
        <button onClick={onDevice}>
          <Icon name="download" size={15} />
          下载与设备
        </button>
      </div>
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
