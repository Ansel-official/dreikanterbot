import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import Icon from './Icons'

const SUGGESTIONS = [
  {
    icon: 'sparkles',
    title: '介绍一下你自己',
    prompt: '介绍一下你能做什么，并给出 3 个适合内部团队的使用建议。',
  },
  {
    icon: 'database',
    title: '设计数据库表结构',
    prompt: '帮我设计一个内部知识库系统的 PostgreSQL 表结构，包含用户、文档、标签和全文检索，给出建表 SQL 和索引建议。',
  },
  {
    icon: 'fileText',
    title: '写一份周报模板',
    prompt: '帮我写一份研发团队周报模板，包含本周完成、进行中、风险与阻塞、下周计划四个部分。',
  },
  {
    icon: 'globe',
    title: '中译英',
    prompt: '把这句话翻译成地道的商务英文：历史对话永不丢失，换设备也能接着聊。',
  },
]

function Welcome({ username, onSuggestion }) {
  return (
    <div className="welcome">
      <div className="brand-mark welcome-mark" aria-hidden="true">
        <span>DS</span>
      </div>
      <h2>{username ? `${username}，你好` : '你好'}</h2>
      <p className="welcome-sub">
        我是部署在内部网络的 DeepSeek 助手。对话会实时保存，随时换设备继续。
      </p>
      <div className="suggestion-grid">
        {SUGGESTIONS.map((item) => (
          <button
            key={item.title}
            className="suggestion-card"
            onClick={() => onSuggestion?.(item.prompt)}
          >
            <span className="suggestion-icon">
              <Icon name={item.icon} size={18} />
            </span>
            <span>{item.title}</span>
            <Icon name="chevronRight" size={15} className="suggestion-arrow" />
          </button>
        ))}
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
}) {
  const scrollRef = useRef(null)
  const endRef = useRef(null)
  const nearBottomRef = useRef(true)
  const lastContentLength = messages.length
    ? (messages[messages.length - 1]?.content || '').length
    : 0

  const scrollToBottom = (smooth = false) => {
    endRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' })
  }

  useEffect(() => {
    if (!loading && nearBottomRef.current) scrollToBottom(false)
  }, [messages.length, loading])

  useEffect(() => {
    if (streaming && nearBottomRef.current) scrollToBottom(false)
  }, [lastContentLength, streaming])

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
          <Welcome username={username} onSuggestion={onSuggestion} />
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
            <p className="chat-disclaimer">AI 生成内容可能有误，重要结论请自行核实。</p>
          </>
        )}
      </div>
    </div>
  )
}
